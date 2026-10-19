# =============================================================================
# tests/control_register/test_approved_library.py — controls enter on approval
#
# Only documents the Document Register holds as current are read; a failed
# download writes nothing; approval reports what it found in the document.
# =============================================================================

from unittest.mock import AsyncMock, patch

import control_register.approved_library as al
from tests.cdi.builders import DocBuilder


def standard(code="DRG-ISMS-STD-TST", ids=("TST-01",)) -> bytes:
    b = DocBuilder()
    b.control_block(title="Test Standard", code=code, owner="CTO", layer="Layer 3")
    for cid in ids:
        b.control(cid, "Change logging", requirement="The CTO shall log every change.",
                  trigger="A change.", responsibility="CTO.", evidence="REC-0001 Change log.")
    return b.bytes()


def prose(code="DRG-ISMS-POL-TST") -> bytes:
    b = DocBuilder()
    b.control_block(title="Test Policy", code=code, owner="CTO", layer="Layer 1")
    b.para("Dragnet is committed to keeping its information secure.")
    return b.bytes()


def row(n, code, status="Active", url=None):
    return {"id": str(n), "fields": {"DocumentCode": code, "Status": status, "Modified": "m1",
                                     "SharePointUrl": url if url is not None else
                                     f"https://x/Lifecycle%20Documents/{n}/{code}.docx"}}


class _Owners:
    def resolve(self, role):
        return {"kind": "group"}


async def _run(register_docs, files, focus="", apply=True, download_error=None):
    al._parsed.clear()

    async def lists(list_id, name, *a, **k):
        return {"Document Register": register_docs}.get(name, [])

    async def download(url):
        if download_error and download_error in url:
            raise RuntimeError("timeout")
        return next(data for key, data in files.items() if key in url), "application/vnd"

    with patch("graph.client.get_list_items", new=AsyncMock(side_effect=lists)), \
         patch("graph.client.download_file_from_sharepoint", new=AsyncMock(side_effect=download)), \
         patch("ownership.resolver.get_ownership_index", new=AsyncMock(return_value=_Owners())), \
         patch.object(al, "_catalogue", new=AsyncMock(return_value=None)), \
         patch("control_register.sync.apply_sync", new=AsyncMock(return_value=[])) as write:
        result = await al.sync_approved_library(focus_code=focus, apply=apply)
    return result, write


async def test_only_current_register_documents_are_read():
    result, write = await _run(
        [row(1, "DRG-ISMS-STD-TST"), row(2, "DRG-ISMS-STD-OLD", status="Withdrawn"),
         row(3, "DRG-ISMS-STD-REV", status="Under Review")],
        {"STD-TST": standard(), "STD-OLD": standard("DRG-ISMS-STD-OLD", ("OLD-01",)),
         "STD-REV": standard("DRG-ISMS-STD-REV", ("REV-01",))})
    assert result["documents_read"] == 2                  # Withdrawn is not part of it
    assert result["controls_defined"] == 2 and result["new_or_changed"] == 2
    assert write.await_count == 1


async def test_approval_reports_what_it_found_in_the_document():
    result, _ = await _run([row(1, "DRG-ISMS-STD-TST")], {"STD-TST": standard(ids=("TST-01", "TST-02"))},
                           focus="DRG-ISMS-STD-TST")
    assert result["focus"]["defines"] == 2 and result["focus"]["raised_for_review"] == 2


async def test_a_failed_download_writes_nothing():
    result, write = await _run([row(1, "DRG-ISMS-STD-TST"), row(2, "DRG-ISMS-STD-TWO")],
                               {"STD-TST": standard(), "STD-TWO": standard("DRG-ISMS-STD-TWO", ("TWO-01",))},
                               download_error="STD-TWO")
    assert result["written"] is False and "could not be downloaded" in result["reason"]
    write.assert_not_awaited()


async def test_a_document_with_no_control_pattern_is_flagged_on_its_lifecycle_item():
    import lifecycle.router as lr
    result, _ = await _run([row(1, "DRG-ISMS-POL-TST")], {"POL-TST": prose()}, focus="DRG-ISMS-POL-TST")
    assert result["focus"]["defines"] == 0
    assert "No controls found" in lr._extraction_outcome_note(result)


async def test_a_clean_approval_needs_no_note():
    import lifecycle.router as lr
    result, _ = await _run([row(1, "DRG-ISMS-STD-TST")], {"STD-TST": standard()}, focus="DRG-ISMS-STD-TST")
    assert lr._extraction_outcome_note(result) == ""


async def test_a_current_document_without_a_published_copy_is_reported():
    result, _ = await _run([row(1, "DRG-ISMS-STD-TST", url="")], {})
    assert result["no_published_copy"] == ["DRG-ISMS-STD-TST"] and result["documents_read"] == 0
