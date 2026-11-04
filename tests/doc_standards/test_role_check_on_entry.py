# =============================================================================
# tests/doc_standards/test_role_check_on_entry.py — wrong roles are flagged when a file arrives
#
# The role check runs on every file change and its problems are stored beside the CDI
# result. EVERY role problem is an error: the card is Failed until it is fixed, whatever the
# gate mode. If Org Roles can't be read, nothing is added.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

from doc_standards.role_check import with_role_problems
from tests.cdi.builders import DocBuilder

GROUPS = [{"id": "g1", "name": "Information Security Officer", "aliases": []}]


def doc(owner="Accountable Department Head"):
    b = DocBuilder()
    b.control_block(title="T", code="DRG-ISMS-PRO-TST", layer="Layer 4 Procedure", domain="d",
                    owner="Information Security Officer", classification="c")
    b.control("TST-01", "One", requirement="R.", trigger="T.")
    b.para(f"Control owner: {owner}.")
    return b.bytes()


async def run(mode, data=None, groups=GROUPS, status="Passed", failures=""):
    with patch("groups.service.list_groups", new=AsyncMock(return_value=groups)), \
         patch("doc_standards.gate.mode", return_value=mode):
        return await with_role_problems(status, failures, data or doc(), "T.docx")


async def test_a_wrong_control_owner_is_an_error_whatever_the_gate_says():
    for mode in ("off", "advisory", "enforce"):
        status, failures = await run(mode)
        rows = json.loads(failures)
        assert status == "Failed"
        assert [(r["check_id"], r["severity"], r["role"]) for r in rows] == [("V07", "error", "Accountable Department Head")]
        assert rows[0]["uses"] == [{"kind": "Control owner", "where": "TST-01"}]


def roles_table_doc():
    b = DocBuilder()
    b.control_block(title="T", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
                    owner="Information Security Officer", classification="c")
    b.control("TST-01", "One", requirement="R.", trigger="T.")
    b.para("Control owner: Information Security Officer.")
    return b.bytes()


async def test_a_role_only_named_in_the_roles_table_is_an_error_too():
    from doc_standards import role_check
    rows = role_check.as_stored([{"message": "x", "fix": "", "where": "roles section",
                                  "data": {"role": "All staff", "kinds": ["Roles section"], "uses": []}}])
    assert rows[0]["severity"] == "error"


async def test_a_document_whose_roles_all_exist_adds_nothing():
    status, failures = await run("enforce", data=doc("Information Security Officer"))
    assert (status, failures) == ("Passed", "")


async def test_the_old_checks_are_kept_and_a_previous_role_result_is_replaced():
    old = json.dumps([{"check_id": "CDI-05", "severity": "error"}, {"check_id": "V07", "role": "stale"}])
    _, failures = await run("off", status="Failed", failures=old)
    ids = [(r["check_id"], r.get("role")) for r in json.loads(failures)]
    assert ids == [("CDI-05", None), ("V07", "Accountable Department Head")]


async def test_if_org_roles_cannot_be_read_nothing_is_added():
    with patch("groups.service.list_groups", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await with_role_problems("Passed", "", doc(), "T.docx") == ("Passed", "")


def ownerless(code="DRG-ISMS-STD-TST", layer="Layer 3 Standard"):
    b = DocBuilder()
    b.control_block(title="T", code=code, layer=layer, domain="d", owner="Information Security Officer",
                    classification="c")
    for cid in ("TST-01", "TST-02"):       # three fields: fewer, and the block is not read as a control
        b.control(cid, cid, requirement="R.", trigger="T.", risk="A risk may happen because of X.")
    return b.bytes()


async def test_a_standard_whose_controls_name_no_owner_is_failed_with_one_row_per_control():
    status, failures = await run("advisory", data=ownerless())
    rows = [r for r in json.loads(failures) if r["check_id"] == "V07"]
    assert status == "Failed" and len(rows) == 1
    assert rows[0]["severity"] == "error" and rows[0]["fixable"] == "manual"
    assert [u["where"] for u in rows[0]["uses"]] == ["TST-01", "TST-02"]


async def test_a_standards_incomplete_controls_block_the_card_one_row_per_check():
    status, failures = await run("off", data=ownerless())
    rows = {r["check_id"]: r for r in json.loads(failures)}
    assert status == "Failed"
    assert {"V08", "V22"} <= set(rows) and all(rows[c]["severity"] == "error" for c in ("V08", "V22"))
    assert [u["where"] for u in rows["V22"]["uses"]] == ["TST-01", "TST-02"]


async def test_a_procedures_control_problems_do_not_block_the_card():
    # it may only be restating a Standard's control: Fix CDI lists them as warnings once the library is known
    status, failures = await run("off", data=ownerless("DRG-ISMS-PRO-TST", "Layer 4 Procedure"))
    assert (status, failures) == ("Passed", "")


async def test_a_procedure_is_not_failed_for_it_because_it_may_only_restate_the_control():
    status, failures = await run("advisory", data=ownerless("DRG-ISMS-PRO-TST", "Layer 4 Procedure"))
    assert (status, failures) == ("Passed", "")


# ── giving an ownerless control an owner, from Fix CDI ─────────────────────────

def row_table_standard() -> bytes:
    import io
    from docx import Document
    d = Document()
    d.add_heading("3.0 Control requirements", 1)
    t = d.add_table(rows=3, cols=4)
    for i, h in enumerate(["ID", "Mandatory control requirement", "Required evidence / monitoring", "Risk statement"]):
        t.rows[0].cells[i].text = h
    for r, cid in ((1, "TST-01"), (2, "TST-02")):
        for i, v in enumerate([cid, "A system MUST be assessed.", "Assessment record REC-0001.",
                               "If it is not assessed, a weakness may go unnoticed because nobody looks."]):
            t.rows[r].cells[i].text = v
    out = io.BytesIO(); d.save(out)
    return out.getvalue()


def test_a_control_table_gets_an_owner_column_and_each_control_its_own_role():
    from cdi.parser import parse_document
    from doc_standards.role_fix import set_control_owner
    data = row_table_standard()
    assert [c.responsibility for c in parse_document(data, "t.docx").controls] == [None, None]
    data = set_control_owner(data, "TST-01", "Information Security Officer").data
    data = set_control_owner(data, "TST-02", "Chief Compliance Officer").data
    owners = {c.control_id: c.responsibility.accountable for c in parse_document(data, "t.docx").controls}
    assert owners == {"TST-01": "Information Security Officer", "TST-02": "Chief Compliance Officer"}


def test_giving_an_owner_changes_nothing_else_and_a_taken_cell_is_refused():
    import pytest
    from cdi.parser import parse_document
    from doc_standards.role_fix import RoleFixError, set_control_owner
    data = row_table_standard()
    once = set_control_owner(data, "TST-01", "Information Security Officer").data
    before, after = parse_document(data, "t.docx"), parse_document(once, "t.docx")
    assert [c.requirement for c in before.controls] == [c.requirement for c in after.controls]
    assert [c.risk for c in before.controls] == [c.risk for c in after.controls]
    with pytest.raises(RoleFixError):
        set_control_owner(once, "TST-01", "Chief Compliance Officer")      # already owned: use "Use this role"
    with pytest.raises(RoleFixError):
        set_control_owner(data, "NOPE-01", "Information Security Officer")


async def test_the_plan_row_for_an_ownerless_control_is_a_choice_that_can_be_applied():
    from lifecycle import router as lr
    from unittest.mock import AsyncMock, patch
    report = {"report": {"results": [{"id": "V07", "findings": [{
        "message": "2 control(s) name no Control owner (TST-01, TST-02).", "where": "TST-01, TST-02",
        "fix": "x", "data": {"kind": "missing-owner", "uses": [{"kind": "Control owner", "where": "TST-01"},
                                                              {"kind": "Control owner", "where": "TST-02"}]}}]}]},
              "available": True}
    with patch.object(lr.standard_gate, "evaluate_item", new=AsyncMock(return_value=report)), \
         patch("groups.service.list_groups", new=AsyncMock(return_value=GROUPS)):
        rows = await lr._role_findings_for_fix_plan({"id": "1"})
    assert [(r["scope_where"], r["fixable"], r["can_apply"], r["severity"]) for r in rows] == [
        ("TST-01", "choice", True, "error"), ("TST-02", "choice", True, "error")]
    assert rows[0]["choices"] == ["Information Security Officer"]


def test_applying_the_owner_choice_through_the_role_fix_path():
    from doc_standards.roles import RoleBook
    from lifecycle import router as lr
    from cdi.parser import parse_document
    book = RoleBook.from_groups(GROUPS)
    fix = lr.ConfirmedFix(fix_id="f", check_id="V07", find="", replace="information security officer",
                          scope_kind="Control owner", scope_where="TST-02")
    data, outcomes, _ = lr._apply_role_fixes(row_table_standard(), [fix], book)
    assert outcomes[0].status == "applied" and outcomes[0].after == "Information Security Officer"
    owners = {c.control_id: c.responsibility and c.responsibility.accountable for c in parse_document(data, "t.docx").controls}
    assert owners == {"TST-01": None, "TST-02": "Information Security Officer"}
