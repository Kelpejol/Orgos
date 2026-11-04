# =============================================================================
# tests/doc_standards/test_role_check_on_entry.py — wrong roles are flagged when a file arrives
#
# The role check runs on every file change and its problems are stored beside the CDI
# result. A role that OWNS something (a Control owner, the Document owner, an approver) is an
# error: the card is Failed until it is fixed. A role only named in the Roles table is a
# warning. Neither depends on the gate mode. If Org Roles can't be read, nothing is added.
# =============================================================================

import json
from unittest.mock import AsyncMock, patch

from doc_standards.role_check import with_role_problems
from tests.cdi.builders import DocBuilder

GROUPS = [{"id": "g1", "name": "Information Security Officer", "aliases": []}]


def doc(owner="Accountable Department Head"):
    b = DocBuilder()
    b.control_block(title="T", code="DRG-ISMS-STD-TST", layer="Layer 3 Standard", domain="d",
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


async def test_a_role_only_described_in_the_roles_table_is_a_warning():
    from doc_standards import role_check
    rows = role_check.as_stored([{"message": "x", "fix": "", "where": "roles section",
                                  "data": {"role": "All staff", "kinds": ["Roles section"], "uses": []}}])
    assert rows[0]["severity"] == "warning"
    owns = role_check.as_stored([{"message": "x", "fix": "", "where": "cover",
                                  "data": {"role": "X", "kinds": ["Roles section", "Final approval"], "uses": []}}])
    assert owns[0]["severity"] == "error"


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
    rows = json.loads(failures)
    assert status == "Failed" and len(rows) == 1
    assert rows[0]["severity"] == "error" and rows[0]["fixable"] == "manual"
    assert [u["where"] for u in rows[0]["uses"]] == ["TST-01", "TST-02"]


async def test_a_procedure_is_not_failed_for_it_because_it_may_only_restate_the_control():
    status, failures = await run("advisory", data=ownerless("DRG-ISMS-PRO-TST", "Layer 4 Procedure"))
    assert (status, failures) == ("Passed", "")
