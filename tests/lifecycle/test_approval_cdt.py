# =============================================================================
# tests/lifecycle/test_approval_cdt.py — CDT wiring inside approval (v06)
#
# _finalize_document_approval is the highest-risk new CDT logic: it advances
# the cover version, appends a revision-history row, attempts to produce the
# PUBLISHED (marker-free) copy, and links both the lifecycle item and the
# Document Register entry to it — with a hard rule: a merge problem must
# NEVER block approval itself (fail loud only for genuinely bad document
# codes, which was already the case before CDT). These tests prove the
# happy path and the merge-failure fallback both work, with Graph mocked at
# the lifecycle.router seam (house pattern — see test_register_bridge.py).
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest

import lifecycle.router as lr
from lifecycle.schemas import CdtCoverFacts, RevisionHistoryEntry


def _lifecycle_doc(**overrides) -> dict:
    base = {
        "id": "10", "Title": "Control of Documented Information Procedure",
        "DocumentCode": "DRG-QI-PRO-CDI", "DocumentType": "Procedure",
        "Department": "Quality & Compliance", "OwnerEntraId": "owner-oid",
        "OwnerName": "Owner Person", "SharePointFileUrl": "https://sp/source.docx",
        "RevisionOf": "", "Notes": "", "StandardsMapping": "", "SensitisationDeadline": "",
        "CDTCoverFacts": CdtCoverFacts(
            domain="Quality & Compliance", version="05",
        ).to_json(),
        "RevisionHistory": json.dumps([
            {"version": "05", "date": "June 2026", "purpose": "Full rewrite", "approved_by": "CCO"},
        ]),
    }
    base.update(overrides)
    return base


# -----------------------------------------------------------------------------
#  _next_cdt_version — pure
# -----------------------------------------------------------------------------

def test_next_cdt_version_draft_becomes_01():
    assert lr._next_cdt_version("Draft") == "01"
    assert lr._next_cdt_version("") == "01"


def test_next_cdt_version_increments_numeric():
    assert lr._next_cdt_version("05") == "06"
    assert lr._next_cdt_version("9") == "10"


# -----------------------------------------------------------------------------
#  _finalize_document_approval — merge SUCCEEDS
# -----------------------------------------------------------------------------

async def test_approval_advances_cover_and_uses_published_copy():
    doc = _lifecycle_doc()
    merged_bytes = b"MERGED-DOCX-BYTES"

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.resolve_user", new_callable=AsyncMock) as mock_resolve, \
         patch("lifecycle.router._upload_to_sharepoint", new_callable=AsyncMock) as mock_upload, \
         patch("lifecycle.router.merge") as mock_merge, \
         patch("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock):

        mock_resolve.return_value = {"display_name": "Jane Approver", "email": "jane@x.com"}
        mock_dl.return_value = (b"SOURCE-BYTES", "cdi.docx")
        mock_merge.return_value = type("R", (), {"document": merged_bytes, "sha256": "x", "doc_code": "DRG-QI-PRO-CDI"})()
        mock_upload.return_value = "https://sp/published.docx"
        mock_create.return_value = {"id": "99", "fields": {}}

        register_id, _ = await lr._finalize_document_approval(
            "10", doc, approver_oid="approver-oid", approver_email="",
        )

    assert register_id == "99"

    # The register was created WITH the advanced cover + appended history.
    create_fields = mock_create.call_args.args[2]
    cover = CdtCoverFacts.from_json(create_fields["CDTCoverFacts"])
    assert cover.version == "06"                      # 05 → 06
    assert cover.final_approval == "Jane Approver"     # auto-populated
    history = RevisionHistoryEntry.list_from_json(create_fields["RevisionHistory"])
    assert len(history) == 2                          # original + the new approval row
    assert history[-1].version == "06"
    assert history[-1].approved_by == "Jane Approver"

    # The merge was actually invoked with the SOURCE bytes, and its output
    # was uploaded and used as the register's SharePointUrl (not the raw
    # source) — the "published, marker-free copy" guarantee.
    mock_merge.assert_called_once()
    assert mock_merge.call_args.args[0] == b"SOURCE-BYTES"
    mock_upload.assert_called_once()

    # find the update_list_item call that set SharePointUrl on the register
    register_url_calls = [
        c for c in mock_update.call_args_list
        if c.args[1] == "Document Register" and "SharePointUrl" in c.args[3]
    ]
    assert register_url_calls, "expected a Document Register SharePointUrl update"
    assert register_url_calls[0].args[3]["SharePointUrl"] == "https://sp/published.docx"


# -----------------------------------------------------------------------------
#  _finalize_document_approval — merge FAILS: must not block approval
# -----------------------------------------------------------------------------

async def test_approval_falls_back_to_source_when_merge_fails():
    doc = _lifecycle_doc()

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("lifecycle.router.download_file_from_sharepoint", new_callable=AsyncMock) as mock_dl, \
         patch("lifecycle.router.resolve_user", new_callable=AsyncMock) as mock_resolve, \
         patch("lifecycle.router._upload_to_sharepoint", new_callable=AsyncMock) as mock_upload, \
         patch("lifecycle.router.merge") as mock_merge, \
         patch("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock):

        mock_resolve.return_value = {"display_name": "Jane Approver", "email": "jane@x.com"}
        mock_dl.return_value = (b"CORRUPT-BYTES", "cdi.docx")
        mock_merge.side_effect = Exception("bad template — cannot merge")
        mock_create.return_value = {"id": "99", "fields": {}}

        register_id, extraction = await lr._finalize_document_approval(
            "10", doc, approver_oid="approver-oid", approver_email="",
        )

    # Approval SUCCEEDS despite the merge failure — this is the hard rule.
    assert register_id == "99"
    assert extraction["started"] is True

    # Never uploaded a published copy (merge failed before that step).
    mock_upload.assert_not_called()

    # Falls back to the ORIGINAL source URL for the register link.
    register_url_calls = [
        c for c in mock_update.call_args_list
        if c.args[1] == "Document Register" and "SharePointUrl" in c.args[3]
    ]
    assert register_url_calls[0].args[3]["SharePointUrl"] == "https://sp/source.docx"

    # The cover/history still advance — a merge/render problem must not lose
    # the underlying data, only the "clean copy" convenience.
    create_fields = mock_create.call_args.args[2]
    cover = CdtCoverFacts.from_json(create_fields["CDTCoverFacts"])
    assert cover.version == "06"
