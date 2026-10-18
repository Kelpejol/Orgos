# =============================================================================
# tests/lifecycle/test_parent_document_link.py
#
# When a document moves Review → Sensitisation, stakeholders get notified
# (Power Automate) that it needs review. The cover's "Parent Document" field
# is free text (lifecycle/schemas.py's CdtCoverFacts.parent_document — there
# is no real link from a document to its parent) — these tests cover
# resolving that text against the Document Register into a real link, and
# that the progress action never blocks on a failed/absent lookup (same
# fallback philosophy as the CDT cover-facts seeding elsewhere in this file).
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest

import lifecycle.router as lr
from auth.validator import CurrentUser
from lifecycle.schemas import CdtCoverFacts

COMPLIANCE_USER = CurrentUser(oid="compliance-oid", name="Compliance Officer",
                               email="c@dragnet.com", tenant_id="t", roles=["compliance"])


def _document_read(**overrides):
    from datetime import date
    from grc.schemas import DocumentRead, DocumentStatus, DocumentType
    base = dict(
        id="1", document_code="DRG-ISMS-POL-SEC", title="Information Security Policy",
        type=DocumentType.POLICY, department="ISMS", current_version="R02",
        effective_date=date(2026, 1, 1), status=DocumentStatus.ACTIVE,
        sharepoint_url="https://sp/register/InfoSecPolicy.docx",
    )
    base.update(overrides)
    return DocumentRead(**base)


def _lifecycle_doc(**overrides) -> dict:
    base = {
        "id": "10", "Title": "Acceptable Use Standard", "DocumentCode": "DRG-ISMS-STD-AU",
        "DocumentType": "Standard", "Department": "Information Security",
        "OwnerEntraId": "owner-oid", "OwnerName": "Owner Person",
        "SharePointFileUrl": "https://sp/source.docx", "Revised": True, "CDIStatus": "Passed",
        "RevisionOf": "", "Notes": "", "StandardsMapping": "", "SensitisationDeadline": "",
        "CDTCoverFacts": CdtCoverFacts(parent_document="Information Security Policy (Layer 2)").to_json(),
        "RevisionHistory": json.dumps([]),
    }
    base.update(overrides)
    return base


# -----------------------------------------------------------------------------
#  _normalize_doc_title — pure
# -----------------------------------------------------------------------------

def test_normalize_strips_layer_suffix_and_case():
    assert lr._normalize_doc_title("Information Security Policy (Layer 2)") == "information security policy"
    assert lr._normalize_doc_title("  Information Security Policy  ") == "information security policy"
    assert lr._normalize_doc_title("") == ""


# -----------------------------------------------------------------------------
#  _resolve_parent_document_link
# -----------------------------------------------------------------------------

async def test_resolve_matches_by_normalized_title():
    with patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_docs.return_value = [_document_read()]
        title, url = await lr._resolve_parent_document_link("Information Security Policy (Layer 2)")

    assert title == "Information Security Policy"
    assert url == "https://sp/register/InfoSecPolicy.docx"


async def test_resolve_falls_back_to_document_code_match():
    with patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_docs.return_value = [_document_read()]
        title, url = await lr._resolve_parent_document_link("DRG-ISMS-POL-SEC")

    assert title == "Information Security Policy"
    assert url == "https://sp/register/InfoSecPolicy.docx"


async def test_resolve_returns_blank_when_no_match():
    with patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_docs.return_value = [_document_read()]
        title, url = await lr._resolve_parent_document_link("Some Unrelated Document")

    assert (title, url) == ("", "")


async def test_resolve_returns_blank_on_lookup_failure():
    with patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        mock_docs.side_effect = Exception("Graph is down")
        title, url = await lr._resolve_parent_document_link("Information Security Policy")

    assert (title, url) == ("", "")


async def test_resolve_blank_input_short_circuits():
    with patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:
        title, url = await lr._resolve_parent_document_link("")

    assert (title, url) == ("", "")
    mock_docs.assert_not_called()


# -----------------------------------------------------------------------------
#  progress_doc — Review → Sensitisation writes the parent link separately
# -----------------------------------------------------------------------------

async def test_progress_writes_parent_link_as_separate_best_effort_call():
    doc = _lifecycle_doc()
    body = lr.ProgressDoc(current_stage="Review", stakeholders=[{"oid": "s1", "name": "Stakeholder One"}])

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_view_only_link", new_callable=AsyncMock) as mock_link, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:

        mock_link.return_value = "https://sp/readonly/source.docx"

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_docs.return_value = [_document_read()]

        await lr.progress_doc("10", body, user=COMPLIANCE_USER)

    # Two separate update_list_item calls: the critical Stage/Stakeholders
    # write, then the best-effort parent-link write — never bundled into one.
    assert mock_update.call_count == 2
    critical_call, parent_call = mock_update.call_args_list
    assert critical_call.args[3]["Stage"] == "Sensitisation"
    assert "ParentDocumentTitle" not in critical_call.args[3]

    assert parent_call.args[3]["ParentDocumentTitle"] == "Information Security Policy"
    assert parent_call.args[3]["ParentDocumentUrl"] == "https://sp/register/InfoSecPolicy.docx"
    # The Teams notification must link to a link that cannot edit the source.
    assert parent_call.args[3]["ReadOnlyFileUrl"] == "https://sp/readonly/source.docx"
    mock_link.assert_awaited_once_with("https://sp/source.docx")


async def test_progress_still_succeeds_when_parent_link_column_missing():
    doc = _lifecycle_doc()
    body = lr.ProgressDoc(current_stage="Review", stakeholders=[{"oid": "s1", "name": "Stakeholder One"}])

    progressed_doc = {**doc, "Stage": "Sensitisation"}
    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_view_only_link", new_callable=AsyncMock) as mock_link, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:

        mock_link.return_value = "https://sp/readonly/source.docx"

        mock_get.side_effect = [
            {"id": "10", "fields": doc},             # initial read
            {"id": "10", "fields": progressed_doc},  # final re-fetch after update
        ]
        mock_docs.return_value = [_document_read()]
        # Critical write succeeds; the follow-up parent-link write fails
        # (e.g. the columns don't exist yet) — must not raise.
        mock_update.side_effect = [None, Exception("SharePoint: field does not exist")]

        result = await lr.progress_doc("10", body, user=COMPLIANCE_USER)

    assert result["Stage"] == "Sensitisation"


async def test_progress_writes_parent_title_only_when_no_url_match():
    doc = _lifecycle_doc(CDTCoverFacts=CdtCoverFacts(parent_document="Some Unrelated Document").to_json())
    body = lr.ProgressDoc(current_stage="Review", stakeholders=[{"oid": "s1", "name": "Stakeholder One"}])

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_view_only_link", new_callable=AsyncMock) as mock_link, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:

        mock_link.return_value = "https://sp/readonly/source.docx"

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_docs.return_value = [_document_read()]

        await lr.progress_doc("10", body, user=COMPLIANCE_USER)

    _, parent_call = mock_update.call_args_list
    assert parent_call.args[3] == {
        "ReadOnlyFileUrl": "https://sp/readonly/source.docx",
        "ParentDocumentTitle": "Some Unrelated Document",
    }


async def test_progress_skips_parent_lookup_when_no_parent_document_set():
    doc = _lifecycle_doc(CDTCoverFacts=CdtCoverFacts().to_json())
    body = lr.ProgressDoc(current_stage="Review", stakeholders=[{"oid": "s1", "name": "Stakeholder One"}])

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_view_only_link", new_callable=AsyncMock) as mock_link, \
         patch("grc.service.get_documents", new_callable=AsyncMock) as mock_docs:

        mock_link.return_value = "https://sp/readonly/source.docx"

        mock_get.return_value = {"id": "10", "fields": doc}

        await lr.progress_doc("10", body, user=COMPLIANCE_USER)

    mock_docs.assert_not_called()
    # The best-effort write still happens — it now also carries the read-only
    # link for the Teams notification — but with no Parent Document fields.
    assert mock_update.call_count == 2
    _, best_effort = mock_update.call_args_list
    assert best_effort.args[3] == {"ReadOnlyFileUrl": "https://sp/readonly/source.docx"}


async def test_progress_still_succeeds_when_the_read_only_link_cannot_be_made():
    """Tenant policy can forbid sharing links. That must not block the stage."""
    doc = _lifecycle_doc(CDTCoverFacts=CdtCoverFacts().to_json())
    body = lr.ProgressDoc(current_stage="Review", stakeholders=[{"oid": "s1", "name": "S One"}])

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_view_only_link", new_callable=AsyncMock) as mock_link:

        mock_get.return_value = {"id": "10", "fields": doc}
        mock_link.side_effect = RuntimeError("Sharing is disabled for this tenant")

        await lr.progress_doc("10", body, user=COMPLIANCE_USER)

    # Only the critical write; nothing optional was written, nothing raised.
    assert mock_update.call_count == 1
    assert mock_update.call_args_list[0].args[3]["Stage"] == "Sensitisation"
