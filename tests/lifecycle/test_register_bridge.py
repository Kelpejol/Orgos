# =============================================================================
# tests/lifecycle/test_register_bridge.py — Document Register ↔ CDT (v06)
#
# Proves the register wiring end to end WITHOUT live SharePoint:
#   • the register read path surfaces the bundled CDTCoverFacts JSON column,
#   • the write path serialises cdt_cover/RevisionHistory as JSON,
#   • the register→MergeContext bridge maps fields correctly, and
#   • the full chain SP item → DocumentRead → MergeContext → merge → published.
# Graph calls are mocked at the grc.service seam (house pattern).
#
# v06: CDTCoverFacts is ONE bundled JSON column (not one column per fact) —
# see lifecycle/schemas.py's module comment for why.
# =============================================================================

import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from docx import Document

import grc.service as svc
from grc.schemas import DocumentCreate, DocumentUpdate
from lifecycle.merge import merge, scan_markers
from lifecycle.schemas import CdtCoverFacts, MergeContext, RevisionHistoryEntry, StandardEntry


# -----------------------------------------------------------------------------
#  Fixtures / helpers
# -----------------------------------------------------------------------------

_COVER = CdtCoverFacts(
    domain="Quality & Compliance",
    parent_document="Control of Documented Information Policy (Layer 2)",
    type_layer="Procedure (Layer 4)",
    classification="Internal use only",
    distribution="All staff",
    owner="Compliance Senior Executive",
    first_pass_approval="Compliance Senior Executive",
    final_approval="Chief Compliance Officer",
    version="06",
    standards=[StandardEntry(name="ISO 9001:2015", reference="Clause 7.5")],
)

_HISTORY = [
    {"version": "05", "date": "June 2026", "purpose": "Full rewrite", "approved_by": "Chief Compliance Officer"},
    {"version": "06", "date": "August 2026", "purpose": "Approval authority moved", "approved_by": "Chief Compliance Officer"},
]


def _sp_item(**field_overrides) -> dict:
    fields = {
        "DocumentCode": "DRG-QI-PRO-CDI",
        "Title": "Control of Documented Information Procedure",
        "DocumentType": "Procedure",
        "Department": "Quality & Compliance",
        "CurrentVersion": "R06",
        "EffectiveDate": "2026-08-01",
        "Status": "Active",
        "CDTCoverFacts": _COVER.to_json(),
        "RevisionHistory": json.dumps(_HISTORY),
    }
    fields.update(field_overrides)
    return {"id": "42", "createdDateTime": "2026-08-01T00:00:00Z",
            "lastModifiedDateTime": "2026-08-02T00:00:00Z", "fields": fields}


def _add_loop(table, *, loop_var: str, iterable: str, cols: list[str]):
    for_row = table.add_row()
    for_row.cells[0].text = f"{{%tr for {loop_var} in {iterable} %}}"
    data_row = table.add_row()
    for i, field in enumerate(cols):
        data_row.cells[i].text = f"{{{{ {loop_var}.{field} }}}}"
    end_row = table.add_row()
    end_row.cells[0].text = "{%tr endfor %}"


def _mini_template() -> bytes:
    """Cover markers + a revision-history loop (control-row layout)."""
    doc = Document()
    ctbl = doc.add_table(rows=1, cols=2)
    ctbl.cell(0, 0).paragraphs[0].add_run("{{ doc_code }} — {{ title }} · {{ doc_type }}")
    ctbl.cell(0, 1).paragraphs[0].add_run(
        "Version {{ version }} · By {{ final_approval }} · {{ classification }} · {{ distribution }}"
    )
    _add_loop(ctbl, loop_var="s", iterable="standards", cols=["name", "reference"])
    htbl = doc.add_table(rows=0, cols=4)
    _add_loop(htbl, loop_var="r", iterable="revision_history",
              cols=["version", "date", "purpose", "approved_by"])
    doc.add_paragraph("Body — no markers.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -----------------------------------------------------------------------------
#  Register READ path
# -----------------------------------------------------------------------------

async def test_read_surfaces_cdt_fields():
    with patch("grc.service.resolve_user", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"display_name": "Owner", "email": "o@dragnet.com"}
        doc = await svc._sp_item_to_doc(_sp_item())
    assert doc.cdt_cover.domain == "Quality & Compliance"
    assert doc.cdt_cover.final_approval == "Chief Compliance Officer"
    assert doc.cdt_cover.version == "06"
    assert doc.cdt_cover.standards[0].name == "ISO 9001:2015"
    assert len(doc.revision_history) == 2
    assert doc.revision_history[0]["version"] == "05"


async def test_read_tolerates_missing_and_malformed_cdt_fields():
    # A pre-CDT document (or one whose CDTCoverFacts column doesn't exist yet)
    # has neither new column; a malformed history → [].
    with patch("grc.service.resolve_user", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"display_name": "Owner", "email": "o@dragnet.com"}
        item = _sp_item(RevisionHistory="{not json}")
        for col in ("CDTCoverFacts",):
            item["fields"].pop(col)
        doc = await svc._sp_item_to_doc(item)
    assert doc.cdt_cover.domain == ""       # defaults, not an error
    assert doc.cdt_cover.standards == []
    assert doc.revision_history == []


# -----------------------------------------------------------------------------
#  Register WRITE path
# -----------------------------------------------------------------------------

async def test_create_serialises_cdt_fields_and_history_json():
    with patch("grc.service.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("grc.service.resolve_user", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"display_name": "Owner", "email": "o@dragnet.com"}
        mock_create.return_value = _sp_item()  # what SP echoes back
        doc = DocumentCreate(
            document_code="DRG-QI-PRO-CDI", title="Control of Documented Information Procedure",
            type="Procedure", department="Quality & Compliance", current_version="R06",
            effective_date="2026-08-01", owner_id="oid-1",
            cdt_cover=_COVER, revision_history=_HISTORY,
        )
        await svc.create_document(doc)

    sent = mock_create.call_args.args[2]  # fields dict (3rd positional arg)
    sent_cover = json.loads(sent["CDTCoverFacts"])
    assert sent_cover["final_approval"] == "Chief Compliance Officer"
    assert sent_cover["distribution"] == "All staff"
    parsed_history = json.loads(sent["RevisionHistory"])
    assert parsed_history[0]["version"] == "05" and parsed_history[1]["purpose"] == "Approval authority moved"


async def test_update_writes_only_provided_cdt_fields():
    with patch("grc.service.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("grc.service.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.resolve_user", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"display_name": "Owner", "email": "o@dragnet.com"}
        mock_get.return_value = _sp_item()
        new_cover = CdtCoverFacts(version="07")
        await svc.update_document("42", DocumentUpdate(cdt_cover=new_cover))

    sent = mock_update.call_args.args[3]  # fields dict (4th positional arg)
    assert set(sent.keys()) == {"CDTCoverFacts"}  # nothing else touched
    assert json.loads(sent["CDTCoverFacts"])["version"] == "07"


# -----------------------------------------------------------------------------
#  The register → MergeContext bridge
# -----------------------------------------------------------------------------

async def test_bridge_maps_all_fields():
    with patch("grc.service.resolve_user", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"display_name": "Owner", "email": "o@dragnet.com"}
        doc = await svc._sp_item_to_doc(_sp_item())
    ctx = MergeContext.from_document_read(doc)
    assert ctx.doc_code == "DRG-QI-PRO-CDI"
    assert ctx.doc_type == "Procedure"          # enum → value
    assert ctx.domain == "Quality & Compliance"
    assert ctx.version == "06"
    assert ctx.final_approval == "Chief Compliance Officer"
    # effective_date is a real `date` on the register — formatted here, not
    # duplicated as a separate free-text field.
    assert ctx.effective_date == "August 2026"
    assert isinstance(ctx.revision_history[0], RevisionHistoryEntry)
    assert ctx.revision_history[0].version == "05"
    assert ctx.standards[0].name == "ISO 9001:2015"


def test_bridge_handles_none_scalars_and_empty_history():
    class Bare:
        document_code = "DRG-QI-PRO-CDI"
        type = "Policy"
        title = "T"
        # everything else absent / None — including cdt_cover / effective_date
    ctx = MergeContext.from_document_read(Bare())
    assert ctx.version == "" and ctx.final_approval == "" and ctx.distribution == ""
    assert ctx.effective_date == ""
    assert ctx.revision_history == []
    assert ctx.standards == []


def test_bridge_formats_real_date_when_cover_blank():
    """Draft-stage documents may have cdt_cover.effective_date="" but the
    register's real `effective_date` populated once approved — the real date
    wins and is formatted, never left blank when a real value exists."""
    class Doc:
        document_code = "DRG-QI-PRO-CDI"
        type = "Procedure"
        title = "T"
        cdt_cover = CdtCoverFacts()  # blank
        revision_history = []
        from datetime import date
        effective_date = date(2026, 8, 1)
        next_review_date = date(2027, 8, 1)
    ctx = MergeContext.from_document_read(Doc())
    assert ctx.effective_date == "August 2026"
    assert ctx.next_review_due == "August 2027"


# -----------------------------------------------------------------------------
#  Full chain: SP item → DocumentRead → MergeContext → merge → published
# -----------------------------------------------------------------------------

async def test_full_register_to_published_chain():
    with patch("grc.service.resolve_user", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"display_name": "Owner", "email": "o@dragnet.com"}
        doc = await svc._sp_item_to_doc(_sp_item())          # read from "SharePoint"
    ctx = MergeContext.from_document_read(doc)                # bridge
    result = merge(_mini_template(), ctx)                     # merge

    assert scan_markers(result.document) == []               # nothing left over
    d = Document(io.BytesIO(result.document))
    cover_text = " ".join(c.text for row in d.tables[0].rows for c in row.cells)
    assert "DRG-QI-PRO-CDI" in cover_text and "Version 06" in cover_text
    assert "ISO 9001:2015" in cover_text
    history = d.tables[1]
    assert len(history.rows) == 2  # two history entries, no header row in this mini table
