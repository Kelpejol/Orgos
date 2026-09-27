# =============================================================================
# tests/lifecycle/test_templates.py — CDT Template Manager tests (v06)
#
# Structural validation is pure (no Graph) and gets the bulk of coverage.
# The fetch path is exercised with graph.client mocked at the templates seam.
#
# v06: no header/footer zone (confirmed empty) — everything lives in the
# cover table (+ its standards tail) and the revision-history table.
# =============================================================================

import io
from unittest.mock import AsyncMock, patch

import pytest
from docx import Document

from lifecycle.templates import (
    InvalidTemplateError,
    TemplateNotFoundError,
    fetch_master_template,
    load_master_template,
    template_filename_for,
    validate_template,
)


# -----------------------------------------------------------------------------
#  Template builders
# -----------------------------------------------------------------------------

def _add_loop(table, *, loop_var: str, iterable: str, cols: list[str]):
    """The 3-row docxtpl row-loop pattern: dedicated for-row/data-row/endfor-row."""
    for_row = table.add_row()
    for_row.cells[0].text = f"{{%tr for {loop_var} in {iterable} %}}"
    data_row = table.add_row()
    for i, field in enumerate(cols):
        data_row.cells[i].text = f"{{{{ {loop_var}.{field} }}}}"
    end_row = table.add_row()
    end_row.cells[0].text = "{%tr endfor %}"


def _build_template(
    *,
    include_doc_code: bool = True,
    unknown_marker: bool = False,
    marker_in_body: bool = False,
    include_recommended: bool = True,
    include_history: bool = True,
) -> bytes:
    doc = Document()

    # Cover table (identity + recommended scalars)
    ctbl = doc.add_table(rows=1, cols=2)
    bits0, bits1 = [], []
    if include_doc_code:
        bits0.append("{{ doc_code }}")
    bits0.append("Version {{ version }}")
    ctbl.cell(0, 0).paragraphs[0].add_run(" | ".join(bits0))
    if include_recommended:
        bits1 = ["{{ title }} — {{ doc_type }}", "By {{ final_approval }} · {{ effective_date }}",
                 "{{ classification }} · {{ distribution }}", "Domain {{ domain }}"]
        ctbl.cell(0, 1).paragraphs[0].add_run(" | ".join(bits1))
    if unknown_marker:
        ctbl.cell(0, 1).paragraphs[0].add_run("  Typo: {{ versoin }}")  # not in vocabulary
    if include_recommended:
        _add_loop(ctbl, loop_var="s", iterable="standards", cols=["name", "reference"])

    # Revision-history loop
    if include_history:
        _add_loop(doc.add_table(rows=0, cols=4), loop_var="r", iterable="revision_history",
                  cols=["version", "date", "purpose", "approved_by"])

    # Body — should have NO markers
    doc.add_paragraph("1.0 PURPOSE. Ordinary body prose.")
    if marker_in_body:
        doc.add_paragraph("Leaked into body: {{ title }}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -----------------------------------------------------------------------------
#  Validation — happy path
# -----------------------------------------------------------------------------

def test_valid_template_passes():
    result = validate_template(_build_template())
    assert result.ok, result.summary()
    assert {"doc_code", "version", "revision_history", "standards"} <= result.present
    assert result.missing_required == []
    assert result.unknown == []
    assert result.markers_in_body == []


def test_loop_iterables_recognised_loop_vars_not_flagged():
    # `revision_history`/`standards` must be seen as referenced; `r`/`s` must
    # NOT be "unknown" (they're declared by their own loop).
    result = validate_template(_build_template())
    assert "revision_history" in result.present
    assert "standards" in result.present
    assert "r" not in result.unknown
    assert "s" not in result.unknown


# -----------------------------------------------------------------------------
#  Validation — failure modes
# -----------------------------------------------------------------------------

def test_unknown_marker_is_flagged():
    result = validate_template(_build_template(unknown_marker=True))
    assert not result.ok
    assert "versoin" in result.unknown  # the typo


def test_marker_in_body_is_flagged():
    result = validate_template(_build_template(marker_in_body=True))
    assert not result.ok
    assert any("title" in m for m in result.markers_in_body)

def test_marker_before_cover_table_is_allowed():
    """
    The confirmed v06 cover isn't purely tabular — a brand block, the dynamic
    "{{ domain }} · {{ doc_type }}" subtitle, and the title itself sit in
    plain paragraphs BEFORE the cover table, not inside it. Those must NOT be
    flagged — only prose AFTER the last cover/history table counts as body.
    """
    doc = Document()
    preamble = doc.add_paragraph()
    preamble.add_run("DRAGNET SOLUTIONS")
    subtitle = doc.add_paragraph()
    subtitle.add_run("{{ domain }} · {{ doc_type }}")
    title_heading = doc.add_paragraph()
    title_heading.add_run("{{ title }}")

    ctbl = doc.add_table(rows=1, cols=2)
    ctbl.cell(0, 0).paragraphs[0].add_run("{{ doc_code }} | Version {{ version }}")
    _add_loop(ctbl, loop_var="s", iterable="standards", cols=["name", "reference"])
    _add_loop(doc.add_table(rows=0, cols=4), loop_var="r", iterable="revision_history",
              cols=["version", "date", "purpose", "approved_by"])

    doc.add_paragraph("1.0 PURPOSE. Ordinary body prose — no markers here.")

    buf = io.BytesIO()
    doc.save(buf)
    result = validate_template(buf.getvalue())
    assert result.markers_in_body == [], result.markers_in_body
    assert result.ok, result.summary()


def test_missing_required_marker_is_flagged():
    result = validate_template(_build_template(include_doc_code=False))
    assert not result.ok
    assert "doc_code" in result.missing_required


def test_missing_recommended_is_warning_not_failure():
    # Has required (doc_code/version) but omits recommended scalars.
    result = validate_template(
        _build_template(include_recommended=False, include_history=False)
    )
    assert result.ok  # still valid
    assert "distribution" in result.missing_recommended
    assert "revision_history" in result.missing_recommended
    assert "standards" in result.missing_recommended


def test_summary_text_reflects_state():
    assert "OK" in validate_template(_build_template()).summary()
    assert "Invalid" in validate_template(_build_template(unknown_marker=True)).summary()


def test_template_filename_for():
    assert template_filename_for("Procedure") == "Procedure.docx"
    assert template_filename_for("SOP") == "SOP.docx"


# -----------------------------------------------------------------------------
#  Fetch / load (Graph mocked)
# -----------------------------------------------------------------------------

async def test_fetch_requests_correct_drive_path():
    good = _build_template()
    with patch("lifecycle.templates.resolve_compliance_drive", new_callable=AsyncMock) as mock_drive, \
         patch("lifecycle.templates.download_drive_item_by_path", new_callable=AsyncMock) as mock_dl:
        mock_drive.return_value = ("site-id", "drive-id")
        mock_dl.return_value = good
        result = await fetch_master_template("Procedure")
    assert result == good
    mock_dl.assert_awaited_once()
    drive_arg, path_arg = mock_dl.call_args.args
    assert drive_arg == "drive-id"
    assert path_arg == "Templates/Procedure.docx"


async def test_fetch_missing_raises_template_not_found():
    with patch("lifecycle.templates.resolve_compliance_drive", new_callable=AsyncMock) as mock_drive, \
         patch("lifecycle.templates.download_drive_item_by_path", new_callable=AsyncMock) as mock_dl:
        mock_drive.return_value = ("site-id", "drive-id")
        mock_dl.side_effect = Exception("404 Not Found")
        with pytest.raises(TemplateNotFoundError):
            await fetch_master_template("Procedure")


async def test_load_master_template_rejects_invalid_structure():
    bad = _build_template(unknown_marker=True)
    with patch("lifecycle.templates.fetch_master_template", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = bad
        with pytest.raises(InvalidTemplateError) as exc:
            await load_master_template("Procedure")
    assert "versoin" in exc.value.validation.unknown


async def test_load_master_template_returns_valid_bytes():
    good = _build_template()
    with patch("lifecycle.templates.fetch_master_template", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = good
        result = await load_master_template("Procedure")
    assert result == good
