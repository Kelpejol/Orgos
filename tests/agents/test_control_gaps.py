# =============================================================================
# tests/agents/test_control_gaps.py — gaps in the controls themselves
#
# Every control confirmed from a defining document is checked whether or not it
# maps to a clause, and gaps are grouped where one fix clears them, so the Gap
# register holds work items rather than one row per symptom.
# =============================================================================

import json

from agents.classifier.service import _scan_conflict_pairs, _scan_near_duplicate_pairs
from agents.gap_analyzer.control_gaps import find_control_gaps
from agents.gap_analyzer.service import _find_gaps


def control(cid, doc="DRG-ISMS-STD-TST", status="Active", accountable="CTO", ambiguous=False,
            implemented=True, evidence=({"record_id": "REC-0001", "name": "Log"},), missing=(),
            refs=()):
    return {
        "id": cid, "control_id": cid, "status": status, "statement": "x", "owner_role": accountable,
        "blocked_reason": "" if status == "Active" else f"“{accountable}” is not a role in Org Roles.",
        "refs": list(refs),
        "definition": {
            "control_id": cid, "title": "T", "accountable": accountable,
            "responsibility_as_written": accountable, "responsibility_ambiguous": ambiguous,
            "defined_in_label": doc, "evidence": list(evidence),
            "evidence_as_written": "REC-0001 Log." if evidence else "",
            "implemented_in": [{"document": "DRG-ISMS-PRO-TST", "section": "4.0"}] if implemented else [],
            "missing_fields": list(missing),
        },
    }


def by(gaps, category):
    return [g for g in gaps if g["gap_category"] == category]


def test_a_complete_owned_implemented_control_has_no_gap():
    assert find_control_gaps([control("TST-01")]) == []


def test_blocked_controls_are_one_ownership_gap_per_document_listing_each_role():
    gaps = find_control_gaps([
        control("TST-01", status="Blocked", accountable="DPO"),
        control("TST-02", status="Blocked", accountable="DPO"),
        control("TST-03", status="Blocked", accountable="DPO / CCO", ambiguous=True),
        control("OTH-01", doc="DRG-ISMS-STD-OTH", status="Blocked", accountable="DPO"),
    ])
    own = by(gaps, "Ownership gap")
    assert [g["gap_key"] for g in own] == ["CDI|OWN:DRG-ISMS-STD-OTH|Ownership gap",
                                           "CDI|OWN:DRG-ISMS-STD-TST|Ownership gap"]
    finding = own[1]["finding"]
    assert "“DPO” (2)" in finding and "1 name no Control owner, or name more than one (TST-03)" in finding


def test_a_control_no_procedure_carries_out_is_its_own_gap():
    [gap] = find_control_gaps([control("TST-01", implemented=False)])
    assert (gap["gap_category"], gap["clause"], gap["severity"]) == ("Implementation gap", "TST-01", "Minor")


def test_incomplete_definitions_and_unidentified_records_are_grouped_per_document():
    gaps = find_control_gaps([
        control("TST-01", missing=("Trigger", "Mapping")),
        control("TST-02", missing=("Mapping",), evidence=({"record_id": None, "name": "Audit report"},)),
    ])
    [incomplete] = by(gaps, "Control gap")
    assert "2 of 2" in incomplete["finding"] and "Mapping (2); Trigger (1)" in incomplete["finding"]
    [unidentified] = by(gaps, "Evidence gap")
    assert unidentified["gap_key"] == "CDI|DOC:DRG-ISMS-STD-TST|Evidence gap"


def test_a_control_stating_no_evidence_at_all_is_a_major_gap():
    [gap] = find_control_gaps([control("TST-01", evidence=())])
    assert (gap["gap_category"], gap["severity"]) == ("Evidence gap", "Major")


def test_control_gaps_carry_a_stated_remediation_not_a_model_one():
    [gap] = find_control_gaps([control("TST-01", implemented=False)])
    package = json.loads(gap["stated"]["remediation_json"])
    assert "TST-01" in package["document"] and package["target_date"]


def test_the_clause_check_leaves_defined_controls_to_the_control_check():
    ref = {"standard": "ISO 27001", "clause": "A.5.1"}
    from standards_map import catalogue
    refs = catalogue.control_mapping({"MappingJson": json.dumps([ref])})
    blocked = control("TST-01", status="Blocked", accountable="Nobody", refs=refs)

    class Owners:
        def has_owner(self, role):
            return False
    gaps = _find_gaps([blocked], [], Owners())
    assert not [g for g in gaps if g.get("clause") == "A.5.1" and g["gap_category"] == "Ownership gap"]


# ── harmonisation: one Control ID is one control ───────────────────────────

def test_two_statements_of_one_control_are_never_reported_as_duplicates():
    same = "The CTO shall log every change in the change register."
    rows = [
        {"id": "1", "statement": same, "source": "DRG-ISMS-STD-IT", "control_id": "IT-01", "origin": "register"},
        {"id": "2", "statement": same + " Weekly.", "source": "DRG-IT-PRO-SRS", "control_id": "IT-01", "origin": "queue"},
        {"id": "3", "statement": same, "source": "DRG-QI-STD-OTH", "control_id": "OTH-07", "origin": "queue"},
    ]
    pairs = {(p["id_a"], p["id_b"]) for p in _scan_near_duplicate_pairs(rows, 0.8)}
    assert ("1", "2") not in pairs                  # same ID: the library sync diffs it
    assert ("1", "3") in pairs                      # different IDs, same words: still found


def test_a_changed_definition_is_not_reported_as_a_conflict_with_itself():
    a = {"id": "1", "ControlStatement": "The CTO shall review access monthly.",
         "SourceDocumentCode": "A", "ProposedOwnerRole": "CTO", "ControlId": "AC-01"}
    b = {**a, "id": "2", "ControlStatement": "The CTO shall review access quarterly.",
         "SourceDocumentCode": "B", "ProposedOwnerRole": "CISO"}
    assert _scan_conflict_pairs([a, b], 0.72) == []
    assert len(_scan_conflict_pairs([a, {**b, "ControlId": ""}], 0.72)) == 1


async def test_an_open_control_gap_closes_once_its_condition_is_gone_and_clause_gaps_stay():
    from unittest.mock import AsyncMock, patch
    import agents.gap_analyzer.service as svc
    items = [
        {"id": "1", "fields": {"Standard": "CDI", "GapKey": "CDI|TST-01|Implementation gap", "Status": "Open"}},
        {"id": "2", "fields": {"Standard": "CDI", "GapKey": "CDI|TST-02|Implementation gap", "Status": "Open"}},
        {"id": "3", "fields": {"Standard": "ISO 27001", "GapKey": "ISO 27001|A.5.1|Missing artefact", "Status": "Open"}},
    ]
    with patch.object(type(svc.settings), "is_list_configured", return_value=True), \
         patch.object(svc, "get_list_items", new=AsyncMock(return_value=items)), \
         patch("graph.client.update_list_item", new=AsyncMock()) as update:
        closed = await svc._close_resolved_control_gaps({"CDI|TST-02|Implementation gap"})
    assert closed == 1
    [call] = update.call_args_list
    assert call.args[2] == "1" and call.args[3]["Status"] == "Closed"
