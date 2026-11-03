# =============================================================================
# tests/lifecycle/test_approval_cdt.py — CDT wiring inside approval (v06)
#
# _finalize_document_approval is the highest-risk CDT logic: it advances the
# cover version, appends a revision-history row, stamps the cover onto the
# document's ONE file (saved over it: SharePoint keeps the draft in its
# history), and links the Document Register entry to that same file — with a
# hard rule: a merge problem must NEVER block approval itself. The file lives
# in the fake library (tests/lifecycle/conftest.py).
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest

import lifecycle.router as lr
from lifecycle.schemas import CdtCoverFacts, RevisionHistoryEntry

SOURCE = "https://sp/source.docx"


@pytest.fixture
def live_writes():
    with patch.object(type(lr.settings), "document_writes_live", property(lambda self: True)):
        yield


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
#  _finalize_document_approval — merge SUCCEEDS
# -----------------------------------------------------------------------------

async def test_approval_stamps_the_cover_onto_the_document_s_own_file(library, live_writes):
    library.add(SOURCE, b"SOURCE-BYTES", "cdi.docx")
    doc = _lifecycle_doc()
    merged_bytes = b"MERGED-DOCX-BYTES"

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("lifecycle.router.resolve_user", new_callable=AsyncMock) as mock_resolve, \
         patch("lifecycle.router.merge") as mock_merge, \
         patch("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock):

        mock_resolve.return_value = {"display_name": "Jane Approver", "email": "jane@x.com"}
        mock_merge.return_value = type("R", (), {"document": merged_bytes, "sha256": "x", "doc_code": "DRG-QI-PRO-CDI"})()
        mock_create.return_value = {"id": "99", "fields": {}}

        register_id, _ = await lr._finalize_document_approval(
            "10", doc, approver_oid="approver-oid", approver_email="",
            change_summary="First issue of the procedure under the CDI v06 control pattern.",
        )

    assert register_id == "99"

    # The register was created WITH the advanced cover + appended history.
    create_fields = mock_create.call_args.args[2]
    cover = CdtCoverFacts.from_json(create_fields["CDTCoverFacts"])
    assert cover.version == "01"                      # a first issue is 01, whatever the cover had typed
    assert cover.final_approval == ""                  # a role field: never filled with a person's name
    history = RevisionHistoryEntry.list_from_json(create_fields["RevisionHistory"])
    assert len(history) == 2                          # original + the new approval row
    assert history[-1].version == "01"
    assert history[-1].purpose.startswith("First issue of the procedure")   # the change summary, not "Approved for use"
    assert history[-1].approved_by == "Jane Approver"

    # The merge was invoked with the file's bytes, and its output saved over THAT file:
    # no published copy anywhere else.
    mock_merge.assert_called_once()
    assert mock_merge.call_args.args[0] == b"SOURCE-BYTES"
    assert library.saves == [(SOURCE, merged_bytes)] and library.created == []

    # find the update_list_item call that set SharePointUrl on the register
    register_url_calls = [
        c for c in mock_update.call_args_list
        if c.args[1] == "Document Register" and "SharePointUrl" in c.args[3]
    ]
    assert register_url_calls, "expected a Document Register SharePointUrl update"
    assert register_url_calls[0].args[3]["SharePointUrl"] == SOURCE

    # The version the file had before approval is remembered, so a reversal can put it back.
    states = [json.loads(c.args[3]["FileState"]) for c in mock_update.call_args_list if "FileState" in c.args[3]]
    assert states and states[-1]["before_approval"] == "before"


# -----------------------------------------------------------------------------
#  _finalize_document_approval — merge FAILS: must not block approval
# -----------------------------------------------------------------------------

async def test_approval_falls_back_to_source_when_merge_fails(library, live_writes):
    library.add(SOURCE, b"CORRUPT-BYTES", "cdi.docx")
    doc = _lifecycle_doc()

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock) as mock_get, \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock) as mock_update, \
         patch("lifecycle.router.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("lifecycle.router.resolve_user", new_callable=AsyncMock) as mock_resolve, \
         patch("lifecycle.router.merge") as mock_merge, \
         patch("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock):

        mock_resolve.return_value = {"display_name": "Jane Approver", "email": "jane@x.com"}
        mock_merge.side_effect = Exception("bad template — cannot merge")
        mock_create.return_value = {"id": "99", "fields": {}}

        register_id, extraction = await lr._finalize_document_approval(
            "10", doc, approver_oid="approver-oid", approver_email="",
            change_summary="First issue of the procedure under the CDI v06 control pattern.",
        )

    # Approval SUCCEEDS despite the merge failure — this is the hard rule.
    assert register_id == "99"
    assert extraction["started"] is True

    # The file was not touched (the merge failed before that step).
    assert library.saves == []

    # Falls back to the ORIGINAL source URL for the register link.
    register_url_calls = [
        c for c in mock_update.call_args_list
        if c.args[1] == "Document Register" and "SharePointUrl" in c.args[3]
    ]
    assert register_url_calls[0].args[3]["SharePointUrl"] == SOURCE

    # The cover/history still advance — a merge/render problem must not lose
    # the underlying data, only the "clean copy" convenience.
    create_fields = mock_create.call_args.args[2]
    cover = CdtCoverFacts.from_json(create_fields["CDTCoverFacts"])
    assert cover.version == "01"


# -----------------------------------------------------------------------------
#  Approval sets the review date, not just the effective date
# -----------------------------------------------------------------------------

async def test_approval_sets_next_review_due_from_the_effective_date(library):
    """A document is published with a review date already on its cover: the
    effective date is the day it was approved, and the review falls a review
    period later. Leaving it for someone to type is how documents end up
    published with the PREVIOUS revision's review date — i.e. overdue on day
    one."""
    from datetime import date, timedelta
    from lifecycle.cover_suggest import REVIEW_PERIOD_DAYS

    library.add(SOURCE, b"SOURCE-BYTES", "cdi.docx")
    doc = _lifecycle_doc()
    # A stale date carried over from the last revision must be replaced.
    stale = CdtCoverFacts.from_json(doc["CDTCoverFacts"])
    stale.next_review_due = "January 2020"
    doc["CDTCoverFacts"] = stale.to_json()

    with patch("lifecycle.router.get_list_item", new_callable=AsyncMock), \
         patch("lifecycle.router.update_list_item", new_callable=AsyncMock), \
         patch("lifecycle.router.create_list_item", new_callable=AsyncMock) as mock_create, \
         patch("lifecycle.router.resolve_user", new_callable=AsyncMock) as mock_resolve, \
         patch("lifecycle.router.merge") as mock_merge, \
         patch("lifecycle.router._background_extract_and_flag", new_callable=AsyncMock):

        mock_resolve.return_value = {"display_name": "Jane Approver", "email": "jane@x.com"}
        mock_merge.return_value = type("R", (), {"document": b"M", "sha256": "x", "doc_code": "DRG-QI-PRO-CDI"})()
        mock_create.return_value = {"id": "99", "fields": {}}

        await lr._finalize_document_approval("10", doc, approver_oid="approver-oid", approver_email="",
                                             change_summary="First issue of the procedure under the CDI v06 control pattern.")

    cover = CdtCoverFacts.from_json(mock_create.call_args.args[2]["CDTCoverFacts"])
    today = date.today()
    assert cover.effective_date == today.strftime("%B %Y")
    assert cover.next_review_due == (today + timedelta(days=REVIEW_PERIOD_DAYS)).strftime("%B %Y")
