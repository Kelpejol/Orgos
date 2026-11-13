# =============================================================================
# tests/lifecycle/test_one_file.py — a document has ONE file, in the library
#
#   • OrgOS saves its changes over that file and never makes a copy;
#   • a file changed outside OrgOS (in Word, or straight in SharePoint) is
#     noticed and checked again, and what it says about itself (code, title,
#     type, standards) replaces what the card said;
#   • so a code corrected in SharePoint is the code approval checks.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

import pytest

import lifecycle.router as lr
from auth.validator import ROLE_COMPLIANCE, CurrentUser
from lifecycle import document_file
from lifecycle.document_file import DocFile
from tests.cdi.builders import DocBuilder

OWNER = CurrentUser(oid="owner", name="Owner", email="o@x", tenant_id="t", roles=[])
COMPLIANCE = CurrentUser(oid="c", name="Compliance", email="c@x", tenant_id="t", roles=[ROLE_COMPLIANCE])
FILE = "https://x.sharepoint.com/sites/everybody/ORGOS LIBRARY/Context/Context Policy.docx"


def policy(code="DRG-QI-POL-CIP", title="Context and Interested Parties Policy", body="Body.") -> bytes:
    b = DocBuilder()
    b.control_block(title=title, code=code, layer="Layer 2 Policy", domain="d",
                    owner="Chief Compliance Officer", classification="c", standards="ISO 9001 Clause 4.1")
    b.para(body)
    return b.bytes()


class Item:
    """A Lifecycle item whose list writes are kept, so a test reads what the card says now."""

    def __init__(self, **fields):
        self.fields = {"Stage": "Review", "OwnerEntraId": "owner", "SharePointFileUrl": FILE,
                       "DocumentCode": "DRG-QI-POL-MIMS-01-26", "Title": "Context Policy", **fields}

    async def get(self, list_id, name, item_id):
        return {"id": item_id, "fields": dict(self.fields)}

    async def update(self, list_id, name, item_id, fields):
        if name == lr._LIST_NAME:
            self.fields.update(fields)

    def patches(self):
        return (patch.object(lr, "get_list_item", new=AsyncMock(side_effect=self.get)),
                patch.object(lr, "update_list_item", new=AsyncMock(side_effect=self.update)),
                patch.object(lr, "_audit_lifecycle_action", new=AsyncMock()),
                patch("doc_standards.role_check.with_role_problems",
                      new=AsyncMock(side_effect=lambda status, failures, *a: (status, failures))))


def run(item: Item):
    from contextlib import ExitStack
    stack = ExitStack()
    mocks = [stack.enter_context(p) for p in item.patches()]
    return stack, mocks


# ── the file's fingerprint ──────────────────────────────────────────────────

def test_sharepoint_s_own_properties_are_not_an_edit():
    import io
    import zipfile
    original = policy()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(buf, "w") as out:
        for name in src.namelist():
            data = src.read(name)
            out.writestr(name, data + b"<!-- touched -->" if name.startswith("docProps/") else data)
    assert document_file.content_digest(buf.getvalue()) == document_file.content_digest(original)
    assert document_file.content_digest(policy(body="Changed.")) != document_file.content_digest(original)


def test_a_change_is_noticed_by_the_tag_or_without_one_by_the_date():
    f = DocFile(drive_id="d", item_id="i", name="n", web_url="u", ctag="c2", modified="2026-11-02T10:00:00Z")
    assert document_file.may_have_changed(f, {"FileState": json.dumps({"ctag": "c1"})})
    assert not document_file.may_have_changed(f, {"FileState": json.dumps({"ctag": "c2"})})
    assert document_file.may_have_changed(f, {"Modified": "2026-11-01T09:00:00Z"})
    assert not document_file.may_have_changed(f, {"Modified": "2026-11-03T09:00:00Z"})


# ── a file changed in SharePoint is checked again ───────────────────────────

async def test_an_unchanged_file_is_not_checked_again(library):
    library.add(FILE, policy(), "Context Policy.docx")
    item = Item(FileState=json.dumps({"item": FILE, "ctag": "ctag-1", "digest": document_file.content_digest(policy())}))
    stack, _ = run(item)
    with stack, patch.object(lr, "run_cdi_check", new=AsyncMock()) as check:
        assert await lr._sync_with_file("42", item.fields) is False
    check.assert_not_awaited()


async def test_an_edit_in_sharepoint_is_checked_again_and_the_code_is_read_from_the_file(library):
    library.add(FILE, policy(), "Context Policy.docx")
    library.files[FILE]["version"] = 2                                   # saved in SharePoint since
    item = Item(FileState=json.dumps({"item": FILE, "ctag": "ctag-1", "digest": "old"}))
    stack, (_, _, audit, _) = run(item)
    with stack, patch.object(lr, "run_cdi_check",
                             new=AsyncMock(return_value={"passed": True, "checks": [], "fail_count": 0})) as check:
        assert await lr._sync_with_file("42", item.fields) is True
    assert check.await_args.args[2] == "DRG-QI-POL-CIP"                  # checked against the file's own code
    assert item.fields["DocumentCode"] == "DRG-QI-POL-CIP"
    assert item.fields["Title"] == "Context and Interested Parties Policy"
    assert item.fields["DocumentType"] == "Policy" and item.fields["Department"] == "QI"
    assert item.fields["StandardsMapping"] == "ISO 9001"
    assert item.fields["CDIStatus"] == "Passed" and item.fields["Revised"] is True
    assert json.loads(item.fields["FileState"])["ctag"] == "ctag-2"      # remembered: not checked twice
    actions = [c.args[2] for c in audit.await_args_list]
    assert "Read from the document" in actions and "Changed in SharePoint" in actions


async def test_a_file_that_states_no_code_keeps_the_card_s_code(library):
    library.add(FILE, policy(code="Not assigned"), "Context Policy.docx")
    item = Item(DocumentCode="DRG-QI-POL-CIP")
    stack, _ = run(item)
    with stack, patch.object(lr, "run_cdi_check", new=AsyncMock(return_value={"passed": True, "checks": []})):
        await lr._sync_with_file("42", item.fields, force=True)
    assert item.fields["DocumentCode"] == "DRG-QI-POL-CIP"


async def test_a_file_that_cannot_be_reached_leaves_the_card_as_it_was():
    item = Item(SharePointFileUrl="https://x/gone.docx", CDIStatus="Failed")
    stack, _ = run(item)
    with stack:
        assert await lr._sync_with_file("42", item.fields, force=True) is False
    assert item.fields["CDIStatus"] == "Failed"


async def test_the_scheduled_check_skips_approved_documents(library):
    library.add(FILE, policy(), "Context Policy.docx")
    rows = [{"id": "1", "fields": {"ApprovalStatus": "Approved", "SharePointFileUrl": FILE}},
            {"id": "2", "fields": {"Stage": "Review", "SharePointFileUrl": FILE}}]
    with patch.object(lr, "get_list_items", new=AsyncMock(return_value=rows)), \
         patch.object(lr, "_sync_with_file", new=AsyncMock(return_value=True)) as sync:
        out = await lr.sync_open_documents()
    assert out == {"checked": 1, "changed": 1} and sync.await_args.args[0] == "2"


# ── the user's case: the code was fixed in SharePoint, then approval ────────

async def test_approval_preview_uses_the_code_corrected_in_sharepoint(library):
    library.add(FILE, policy(), "Context Policy.docx")
    item = Item(Stage="Approval", DocumentCode="Not assigned", FileState=json.dumps({"item": FILE, "ctag": "ctag-0"}),
                VersionDecision="new", ChangeSummary="First issue of the context policy for the library.")
    stack, _ = run(item)
    with stack, patch.object(lr, "run_cdi_check", new=AsyncMock(return_value={"passed": True, "checks": []})):
        impact = await lr.approval_impact("42", user=COMPLIANCE)
    assert not impact["blocked"], impact["blocked_reason"]
    assert "DRG-QI-POL-CIP" in impact["summary"]


# ── OrgOS's own changes go into the same file ───────────────────────────────

class _Upload:
    def __init__(self, name, data):
        self.filename, self._data = name, data

    async def read(self):
        return self._data


async def _upload(item, name, data):
    stack, _ = run(item)
    with stack, patch.object(type(lr.settings), "document_writes_live", property(lambda s: True)), \
         patch.object(lr, "_cdi_check_file", new=AsyncMock(return_value=("Passed", ""))), \
         patch.object(lr, "_sp_to_doc", new=AsyncMock(side_effect=lambda i: dict(i["fields"]))):
        return await lr.upload_doc_file("42", _Upload(name, data), OWNER)


async def test_an_upload_replaces_the_content_of_the_same_file(library):
    library.add(FILE, policy(), "Context Policy.docx")
    out = await _upload(Item(), "my edit.docx", b"NEW")
    assert library.saves == [(FILE, b"NEW")] and library.created == []
    assert out["SharePointFileUrl"] == FILE and "version history" in out["UploadNote"]


async def test_a_word_version_of_a_pdf_is_saved_beside_it_not_over_it(library):
    library.add(FILE, b"%PDF", "Context Policy.pdf")
    out = await _upload(Item(), "Context Policy.docx", b"WORD")
    assert library.saves == [] and len(library.created) == 1
    assert out["SharePointFileUrl"] == library.created[0]


async def test_a_document_with_no_file_gets_one_in_the_library(library):
    out = await _upload(Item(SharePointFileUrl=""), "New Policy.docx", b"WORD")
    assert library.created == ["https://x.sharepoint.com/New documents/New Policy.docx"]
    assert out["SharePointFileUrl"] == library.created[0]


async def test_nothing_is_saved_while_writes_are_off(library):
    library.add(FILE, policy(), "Context Policy.docx")
    stack, _ = run(Item())
    with stack, patch.object(type(lr.settings), "document_writes_live", property(lambda s: False)):
        with pytest.raises(Exception) as e:
            await lr.upload_doc_file("42", _Upload("x.docx", b"NEW"), OWNER)
    assert getattr(e.value, "status_code", None) == 409 and library.saves == []


async def test_a_fix_cdi_change_is_saved_over_the_document_s_file(library):
    library.add(FILE, policy(body="Owner: Head of Stuff."), "Context Policy.docx")
    item = Item()
    stack, _ = run(item)
    fix = lr.ConfirmedFix(fix_id="f1", check_id="CDI-07", find="Head of Stuff", replace="Head of Things")
    with stack, patch.object(type(lr.settings), "document_writes_live", property(lambda s: True)), \
         patch.object(lr, "_cdi_check_file", new=AsyncMock(return_value=("Passed", ""))), \
         patch("agents.cdi_checker.service.validate_fix_content", return_value=(True, "")), \
         patch.object(lr, "_audit_cdi_fixes", new=AsyncMock()):
        out = await lr.cdi_fix_apply("42", lr.ApplyCdiFixes(fixes=[fix]), OWNER)
    assert out["applied_count"] == 1 and out["sharepoint_url"] == FILE
    assert [url for url, _ in library.saves] == [FILE] and library.created == []


async def test_a_code_the_header_reader_misses_is_still_found_where_cdi_01_looks():
    """A header table in a layout the parser does not know: the card must still get the file's code."""
    import io
    from docx import Document
    d = Document()
    d.add_paragraph("Some Policy")
    t = d.add_table(rows=0, cols=2)
    for a, b in (("Attribute", "Info"), ("Reference", "DRG-QI-POL-CIP"), ("Colour", "x"), ("Shape", "y"), ("Size", "z")):
        row = t.add_row().cells; row[0].text, row[1].text = a, b
    buf = io.BytesIO(); d.save(buf)
    fields = {"DocumentCode": None, "Title": "Some Policy"}
    with patch.object(lr, "update_list_item", new=AsyncMock()):
        changes = await lr._refresh_from_file("42", fields, buf.getvalue(), "Some Policy.docx")
    assert fields["DocumentCode"] == "DRG-QI-POL-CIP" and any("code" in c for c in changes)


# ── a file someone has locked ───────────────────────────────────────────────

async def test_a_fix_on_a_locked_file_changes_nothing_and_says_what_to_do(library):
    library.add(FILE, policy(body="Owner: Head of Stuff."), "Context Policy.docx")
    item = Item()
    stack, _ = run(item)
    fix = lr.ConfirmedFix(fix_id="f1", check_id="CDI-07", find="Head of Stuff", replace="Head of Things")
    with stack, patch.object(type(lr.settings), "document_writes_live", property(lambda s: True)), \
         patch("agents.cdi_checker.service.validate_fix_content", return_value=(True, "")), \
         patch.object(lr, "_audit_cdi_fixes", new=AsyncMock()), \
         patch.object(lr.document_file, "save", new=AsyncMock(side_effect=lr.document_file.FileLocked("“x” is open for editing in Word."))):
        with pytest.raises(Exception) as e:
            await lr.cdi_fix_apply("42", lr.ApplyCdiFixes(fixes=[fix]), OWNER)
    assert getattr(e.value, "status_code", None) == 409 and "Nothing was changed" in e.value.detail
