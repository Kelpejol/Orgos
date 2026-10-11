# =============================================================================
# tests/lifecycle/test_cover_suggest_endpoint.py
#
# GET /documents/{id}/cover/suggest exposes the suggestion engine to the
# Cover & control facts panel. The engine itself is covered by
# test_cover_suggest.py; what matters here is the endpoint's contract:
#
#   * it writes NOTHING (CDI-014 reserves approving/publishing to people —
#     the values land on the document only when somebody saves them), and
#   * it degrades rather than fails, because a panel that won't open is
#     worse than a panel with some fields left for the reviewer to fill.
# =============================================================================

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

import lifecycle.router as lr
from lifecycle.cover_suggest import library_path_from_url
from auth.validator import CurrentUser
from lifecycle.domains import Domain
from lifecycle.schemas import CdtCoverFacts

COMPLIANCE_USER = CurrentUser(oid="compliance-oid", name="Compliance Officer",
                              email="c@dragnet.com", tenant_id="t", roles=["compliance"])


def _document_read(code: str, title: str, cover: CdtCoverFacts | None = None):
    from grc.schemas import DocumentRead, DocumentStatus, DocumentType
    return DocumentRead(
        id="1", document_code=code, title=title, type=DocumentType.STANDARD,
        department="ISMS", current_version="R02", effective_date=date(2026, 1, 1),
        status=DocumentStatus.ACTIVE, cdt_cover=cover,
    )


def _lifecycle_fields(**overrides) -> dict:
    base = {
        "Title": "Control of Documented Information Procedure",
        "DocumentCode": "DRG-QI-PRO-CDI",
        "DocumentType": "Procedure",
        "Department": "Quality",
        "OwnerEntraId": "owner-oid",
        "Owner": "Jane Doe",
        "SharePointFileUrl": "",
        "CDTCoverFacts": "",
        "RevisionHistory": json.dumps([]),
    }
    base.update(overrides)
    return base


# -----------------------------------------------------------------------------
#  The endpoint proposes; it never writes
# -----------------------------------------------------------------------------

async def test_suggesting_writes_nothing():
    """The whole point of the panel is that a person confirms the facts. If
    this endpoint saved them, the confirmation step would be decorative."""
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": _lifecycle_fields()}
        mock_docs.return_value = []

        await lr.suggest_cover("10", user=COMPLIANCE_USER)

    mock_update.assert_not_called()


async def test_response_carries_provenance_for_every_field():
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": _lifecycle_fields()}
        mock_docs.return_value = []

        result = await lr.suggest_cover("10", user=COMPLIANCE_USER)

    assert result["document_id"] == "10"
    for field, suggestion in result["suggestions"].items():
        assert set(suggestion) == {"value", "source", "confidence", "note"}, field
        assert suggestion["source"], f"{field} proposes a value with no stated source"


async def test_parent_in_the_register_resolves_the_approval_route():
    """The real CDI chain: the Procedure's parent Standard carries the domain,
    and the domain decides who approves. One lookup, whole chain."""
    parent = _document_read(
        "DRG-QI-STD-CDI", "Control of Documented Information Standard",
        CdtCoverFacts(domain="Quality & Compliance"),
    )
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": _lifecycle_fields()}
        mock_docs.return_value = [parent]

        s = (await lr.suggest_cover("10", user=COMPLIANCE_USER))["suggestions"]

    assert s["domain"]["value"] == Domain.QUALITY_COMPLIANCE.value
    assert s["first_pass_approval"]["value"] == "Chief Compliance Officer"
    assert s["final_approval"]["value"] == "Managing Director / CEO"
    assert "DRG-QI-STD-CDI" in s["parent_document"]["value"]


async def test_unresolved_fields_are_named_so_the_panel_can_flag_them():
    fields = _lifecycle_fields(DocumentCode="DRG-ZZZ-PRO-ABC", Owner="Jane Doe")
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": fields}
        mock_docs.return_value = []

        result = await lr.suggest_cover("10", user=COMPLIANCE_USER)

    assert "domain" in result["unresolved"]
    assert result["suggestions"]["domain"]["value"] == ""


# -----------------------------------------------------------------------------
#  Degrading instead of failing
# -----------------------------------------------------------------------------

async def test_register_failure_still_returns_suggestions():
    """Without the Register we lose the parent signal only — the function code
    still resolves the domain for most documents, so the panel must open."""
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": _lifecycle_fields()}
        mock_docs.side_effect = RuntimeError("Graph is down")

        s = (await lr.suggest_cover("10", user=COMPLIANCE_USER))["suggestions"]

    assert s["domain"]["value"] == Domain.QUALITY_COMPLIANCE.value
    assert s["domain"]["confidence"] == "medium"


async def test_approval_date_drives_the_dates():
    fields = _lifecycle_fields(ApprovedDate="2026-03-15T00:00:00Z")
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": fields}
        mock_docs.return_value = []

        s = (await lr.suggest_cover("10", user=COMPLIANCE_USER))["suggestions"]

    assert s["effective_date"]["value"] == "March 2026"
    assert s["next_review_due"]["value"] == "March 2027"


async def test_unapproved_document_gets_no_effective_date():
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": _lifecycle_fields(ApprovedDate="")}
        mock_docs.return_value = []

        s = (await lr.suggest_cover("10", user=COMPLIANCE_USER))["suggestions"]

    assert s["effective_date"]["value"] == ""


async def test_confirmed_domain_survives_a_file_move():
    """The reason the folder is only ever a hint: once a person has confirmed
    the domain, moving the file must not silently re-route the document."""
    fields = _lifecycle_fields(
        CDTCoverFacts=CdtCoverFacts(domain="Data Protection & Privacy").to_json(),
        SharePointFileUrl="https://sp/sites/everybody/LIB/Access%20Control/doc.docx",
    )
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_get.return_value = {"id": "10", "fields": fields}
        mock_docs.return_value = []

        s = (await lr.suggest_cover("10", user=COMPLIANCE_USER))["suggestions"]

    assert s["domain"]["value"] == Domain.DATA_PROTECTION_PRIVACY.value


# -----------------------------------------------------------------------------
#  library_path_from_url — the folder hint, recovered without counting segments
# -----------------------------------------------------------------------------

def test_family_recovered_from_a_sharepoint_url():
    path = library_path_from_url(
        "https://dragnetnigeria.sharepoint.com/sites/everybody/"
        "GRC%20MASTERY%20LIBRARY/Access%20Control/01%20Policy.docx"
    )
    assert path == "Access Control/01 Policy.docx"


def test_family_found_at_any_depth():
    """Staging nests families a level deeper; the library's display name in
    the URL differs from the drive's. Counting segments would break on both."""
    path = library_path_from_url(
        "https://x/sites/everybody/LIB/00%20WORK%20IN%20PROGRESS/"
        "Programme%20Assurance/Access%20Control/draft.docx"
    )
    assert path == "Access Control/draft.docx"


@pytest.mark.parametrize("url", [
    "https://x/sites/everybody/LIB/Some%20Unmapped%20Folder/doc.docx",
    "",
    "not a url at all",
])
def test_no_known_family_yields_no_hint_rather_than_a_misleading_one(url):
    assert library_path_from_url(url) == ""


# -----------------------------------------------------------------------------
#  GET /cdi/domains — the controlled list the panel offers
# -----------------------------------------------------------------------------

async def test_domain_list_is_annex_b_with_routes():
    """V05 blocks approval unless the domain comes from Annex B, so the panel
    must be able to offer the real list — with each domain's route, so First
    Pass / Final Approval follow from it instead of being asked for twice."""
    rows = await lr.list_cdi_domains(user=COMPLIANCE_USER)

    assert len(rows) == 14
    assert {r["domain"] for r in rows} == {d.value for d in Domain}
    for row in rows:
        assert row["first_pass_approval"] and row["final_approval"]
        assert row["first_pass_approval"] != row["final_approval"]
