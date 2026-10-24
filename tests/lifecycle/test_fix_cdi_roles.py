# =============================================================================
# tests/lifecycle/test_fix_cdi_roles.py — role problems are fixed in "Fix CDI issues"
#
# V07's findings appear in the same plan as the old checker's, and are applied with
# the scoped, proven role edit (never a blind find-and-replace over the whole file).
# =============================================================================

import io
from unittest.mock import AsyncMock, patch

from docx import Document

import lifecycle.router as lr
from doc_standards.roles import RoleBook
from tests.cdi.builders import DocBuilder

OLD, NEW = "Info Sec Officer", "Information Security Officer"
BOOK = RoleBook.from_groups([{"id": "g1", "name": NEW, "aliases": []}])


def doc_bytes():
    b = DocBuilder()
    b.control_block(title="T", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="Chief Compliance Officer", classification="c")
    b.control("TST-01", "One", requirement="The Info Sec Officer shall review it.", trigger="Creation.")
    b.para(f"Control owner: {OLD}.")
    return b.bytes()


def fix(**kw):
    return lr.ConfirmedFix(**{"fix_id": "V07-role-0", "check_id": "V07", "find": OLD, "replace": NEW, **kw})


def test_a_role_fix_changes_the_role_field_and_not_the_running_text():
    out, outcomes = lr._apply_role_fixes(doc_bytes(), [fix()], BOOK)
    assert [o.status for o in outcomes] == ["applied"]
    text = "\n".join(p.text for p in Document(io.BytesIO(out)).paragraphs)
    assert f"Control owner: {NEW}." in text and "The Info Sec Officer shall review it." in text


def test_a_role_that_is_not_in_org_roles_is_rejected_and_the_file_is_untouched():
    data = doc_bytes()
    out, outcomes = lr._apply_role_fixes(data, [fix(replace="Chief Wizard")], BOOK)
    assert [o.status for o in outcomes] == ["rejected"] and out == data


def test_one_fix_that_cannot_be_made_does_not_stop_the_others():
    good = fix()
    missing = lr.ConfirmedFix(fix_id="V07-role-1", check_id="V07", find="Nobody Anywhere", replace=NEW)
    out, outcomes = lr._apply_role_fixes(doc_bytes(), [missing, good], BOOK)
    assert [o.status for o in outcomes] == ["skipped_not_found", "applied"]


async def test_the_plan_lists_a_missing_role_with_the_roles_that_exist_to_choose_from():
    report = {"report": {"results": [{"id": "V07", "findings": [{
        "message": "“Info Sec Officer” is not a role in Org Roles (Control owner).", "where": "TST-01", "fix": "Did you mean…",
        "data": {"kind": "role", "role": OLD, "locations": ["TST-01"], "placeholder": False, "group": False,
                 "suggestions": [{"name": NEW}]}}]}]}, "available": True}
    groups = [{"id": "g1", "name": NEW}, {"id": "g2", "name": "Chief Compliance Officer"}]
    with patch.object(lr.standard_gate, "evaluate_item", new=AsyncMock(return_value=report)), \
         patch("groups.service.list_groups", new=AsyncMock(return_value=groups)):
        findings = await lr._role_findings_for_fix_plan({"id": "1"})
    assert len(findings) == 1
    f = findings[0]
    assert f["check_id"] == "V07" and f["find"] == OLD and f["replace"] == NEW
    assert f["choices"][0] == NEW and "Chief Compliance Officer" in f["choices"] and f["can_apply"]


async def test_a_group_description_is_shown_but_cannot_be_applied():
    report = {"report": {"results": [{"id": "V07", "findings": [{
        "message": "describes a group", "where": "Roles",
        "data": {"kind": "role", "role": "Requester and owner roles", "locations": [], "group": True, "suggestions": []}}]}]},
        "available": True}
    with patch.object(lr.standard_gate, "evaluate_item", new=AsyncMock(return_value=report)), \
         patch("groups.service.list_groups", new=AsyncMock(return_value=[])):
        findings = await lr._role_findings_for_fix_plan({"id": "1"})
    assert findings[0]["can_apply"] is False


async def test_if_the_role_check_cannot_run_the_plan_just_has_no_role_findings():
    with patch.object(lr.standard_gate, "evaluate_item", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await lr._role_findings_for_fix_plan({"id": "1"}) == []
