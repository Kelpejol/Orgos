# =============================================================================
# tests/doc_standards/test_role_check_on_entry.py — wrong roles are flagged when a file arrives
#
# The role check runs on every file change and its problems are stored beside the CDI
# result: a warning under the advisory gate, an error that stops the document when the
# gate is enforced. If Org Roles can't be read, nothing is added — never a false verdict.
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


async def test_a_wrong_role_is_a_warning_under_the_advisory_gate():
    status, failures = await run("advisory")
    rows = json.loads(failures)
    assert status == "Passed"
    assert [(r["check_id"], r["severity"], r["role"]) for r in rows] == [("V07", "warning", "Accountable Department Head")]
    assert rows[0]["uses"] == [{"kind": "Control owner", "where": "TST-01"}]


async def test_a_wrong_role_stops_the_document_when_the_gate_is_enforced():
    status, failures = await run("enforce")
    assert status == "Failed" and json.loads(failures)[0]["severity"] == "error"


async def test_a_document_whose_roles_all_exist_adds_nothing():
    status, failures = await run("enforce", data=doc("Information Security Officer"))
    assert (status, failures) == ("Passed", "")


async def test_the_old_checks_are_kept_and_a_previous_role_result_is_replaced():
    old = json.dumps([{"check_id": "CDI-05", "severity": "error"}, {"check_id": "V07", "role": "stale"}])
    _, failures = await run("advisory", status="Failed", failures=old)
    ids = [(r["check_id"], r.get("role")) for r in json.loads(failures)]
    assert ids == [("CDI-05", None), ("V07", "Accountable Department Head")]


async def test_if_org_roles_cannot_be_read_nothing_is_added():
    with patch("groups.service.list_groups", new=AsyncMock(side_effect=RuntimeError("down"))):
        assert await with_role_problems("Passed", "", doc(), "T.docx") == ("Passed", "")
