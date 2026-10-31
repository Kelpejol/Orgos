# =============================================================================
# tests/control_register/test_no_longer_defined.py — a control a document drops is not left live
#
# It is raised for a person (withdraw it, or keep it), once; the item closes itself if the
# control is defined again. A procedure's short copy never becomes the definition of a
# control its Standard used to define.
# =============================================================================

import json

from control_register.approved_library import _keep_standard_definitions, plan_no_longer_defined
from control_register.sync import SyncAction, SyncPlan

REGISTER = [{"id": "41", "fields": {"ControlId": "TST-01", "Status": "Active", "SourceDocument": "DRG-ISMS-STD-TST",
                                    "DefinitionJson": json.dumps({"defined_in": {"code": "DRG-ISMS-STD-TST"}})}}]


def test_a_dropped_control_is_raised_once_for_a_decision():
    [action] = plan_no_longer_defined(["TST-01"], REGISTER, [])
    assert action.kind == "create_item" and action.control_id == "NO-LONGER-DEFINED:TST-01"
    assert action.fields["OrphanClassification"] == "CONTROL_NO_LONGER_DEFINED"
    assert action.fields["ControlId"] == "TST-01"
    pending = [{"id": "9", "fields": {"ResolutionKey": "NO-LONGER-DEFINED:TST-01", "ReviewStatus": "Pending Review"}}]
    assert plan_no_longer_defined(["TST-01"], REGISTER, pending) == []          # not raised twice


def test_the_item_closes_itself_when_the_control_is_defined_again():
    pending = [{"id": "9", "fields": {"ResolutionKey": "NO-LONGER-DEFINED:TST-01", "ReviewStatus": "Pending Review"}}]
    [action] = plan_no_longer_defined([], REGISTER, pending)
    assert action.kind == "close_item" and action.queue_item_id == "9"


def test_a_withdrawn_control_is_not_raised():
    withdrawn = [{"id": "41", "fields": {**REGISTER[0]["fields"], "Status": "Withdrawn"}}]
    assert plan_no_longer_defined(["TST-01"], withdrawn, []) == []


def test_a_procedure_copy_does_not_take_over_a_standards_control():
    plan = SyncPlan()
    plan.actions = [SyncAction("update_item", "TST-01", {"defined_in": {"code": "DRG-ISMS-PRO-TST"}}),
                    SyncAction("update_item", "TST-02", {"defined_in": {"code": "DRG-ISMS-STD-TST"}})]
    plan.no_longer_defined = []
    _keep_standard_definitions(plan, REGISTER)
    assert [a.control_id for a in plan.actions] == ["TST-02"] and plan.no_longer_defined == ["TST-01"]
