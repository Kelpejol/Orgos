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


def procedure(code="DRG-ISMS-PRO-TST", restates=("TST-01",), cites=()) -> bytes:
    b = DocBuilder()
    b.control_block(title="Test Procedure", code=code, owner="CTO", layer="Layer 4")
    for cid in restates:                    # the short copy procedures carry
        b.control(cid, "Change logging", requirement="The CTO shall log every change.",
                  evidence="REC-0001 Change log.", risk="Unlogged change.")
    if cites:
        b.para(f"This procedure implements {', '.join(cites)}.")
    return b.bytes()


def parsed(data: bytes, name: str):
    from cdi.parser import parse_document
    return parse_document(data, name)


def row(n, code, status="Active", url=None):
    return {"id": str(n), "fields": {"DocumentCode": code, "Status": status, "Modified": "m1",
                                     "SharePointUrl": url if url is not None else
                                     f"https://x/Lifecycle%20Documents/{n}/{code}.docx"}}


class _Owners:
    def resolve(self, role):
        return {"kind": "group"}


async def _run(register_docs, files, focus="", apply=True, download_error=None, folder=()):
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
         patch.object(al, "load_library_folder", new=AsyncMock(return_value=(list(folder), []))), \
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


# ── who defines what: the library folder; what it says: approved documents ──

async def test_a_procedure_approved_before_its_standard_raises_nothing_from_its_copy():
    folder = [parsed(standard(), "std.docx")]               # the Standard, still a draft
    result, _ = await _run([row(1, "DRG-ISMS-PRO-TST")], {"PRO-TST": procedure()},
                           focus="DRG-ISMS-PRO-TST", folder=folder)
    assert result["new_or_changed"] == 0
    assert result["awaiting_definition"] == {"TST-01": "DRG-ISMS-STD-TST"}
    assert result["focus"]["awaiting"] == {"DRG-ISMS-STD-TST": ["TST-01"]}


async def test_the_lifecycle_note_names_the_standard_the_controls_wait_for():
    import lifecycle.router as lr
    folder = [parsed(standard(), "std.docx")]
    result, _ = await _run([row(1, "DRG-ISMS-PRO-TST")], {"PRO-TST": procedure()},
                           focus="DRG-ISMS-PRO-TST", folder=folder)
    note = lr._extraction_outcome_note(result)
    assert "TST-01" in note and "DRG-ISMS-STD-TST" in note


async def test_once_the_standard_is_approved_its_definition_is_raised():
    folder = [parsed(standard(), "std.docx"), parsed(procedure(), "pro.docx")]
    result, _ = await _run([row(1, "DRG-ISMS-PRO-TST"), row(2, "DRG-ISMS-STD-TST")],
                           {"PRO-TST": procedure(), "STD-TST": standard()},
                           focus="DRG-ISMS-STD-TST", folder=folder)
    assert result["awaiting_definition"] == {} and result["new_or_changed"] == 1
    assert result["focus"]["raised_for_review"] == 1


async def test_citing_a_control_whose_standard_is_still_in_lifecycle_is_not_a_finding():
    folder = [parsed(standard(), "std.docx")]
    result, _ = await _run([row(1, "DRG-ISMS-PRO-CIT")],
                           {"PRO-CIT": procedure("DRG-ISMS-PRO-CIT", restates=(), cites=("TST-01",))},
                           folder=folder)
    assert result["findings_raised"] == 0


async def test_citing_a_control_no_document_defines_is_still_a_finding():
    result, _ = await _run([row(1, "DRG-ISMS-PRO-CIT")],
                           {"PRO-CIT": procedure("DRG-ISMS-PRO-CIT", restates=(), cites=("GONE-01",))})
    assert result["findings_raised"] == 1


async def test_a_procedure_restating_its_standard_defines_nothing():
    folder = [parsed(standard(), "std.docx"), parsed(procedure(), "pro.docx")]
    result, _ = await _run([row(1, "DRG-ISMS-PRO-TST"), row(2, "DRG-ISMS-STD-TST")],
                           {"PRO-TST": procedure(), "STD-TST": standard()},
                           focus="DRG-ISMS-PRO-TST", folder=folder)
    assert result["focus"]["defines"] == 0 and result["focus"]["states"] == 1
