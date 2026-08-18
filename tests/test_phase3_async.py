# =============================================================================
# tests/test_phase3_async.py — Phase 3 async/perf refactors
#
# The classifier's O(n²) scans and the standards-map traffic-light calc are now
# pure, thread-offloadable functions — so they're directly unit-testable.
# =============================================================================

from agents.classifier.service import _scan_conflict_pairs, _scan_near_duplicate_pairs
from standards_map.router import _calculate_traffic_light


# -----------------------------------------------------------------------------
#  Classifier scan helpers (A2)
# -----------------------------------------------------------------------------

def test_near_duplicate_scan_flags_similar_cross_source_pair():
    controls = [
        {"id": "1", "statement": "The CX Officer shall log all candidate calls", "source": "DOC-A", "origin": "queue"},
        {"id": "2", "statement": "The CX Officer shall log all candidate calls", "source": "DOC-B", "origin": "queue"},
    ]
    findings = _scan_near_duplicate_pairs(controls, 0.80)
    assert len(findings) == 1
    assert findings[0]["id_a"] == "1" and findings[0]["id_b"] == "2"


def test_near_duplicate_scan_skips_same_source():
    controls = [
        {"id": "1", "statement": "Access shall be reviewed quarterly", "source": "DOC-A", "origin": "queue"},
        {"id": "2", "statement": "Access shall be reviewed quarterly", "source": "DOC-A", "origin": "queue"},
    ]
    assert _scan_near_duplicate_pairs(controls, 0.80) == []


def test_near_duplicate_length_prefilter_skips_very_different_lengths():
    controls = [
        {"id": "1", "statement": "Log calls", "source": "A", "origin": "queue"},
        {"id": "2", "statement": "Log calls " + "x" * 500, "source": "B", "origin": "queue"},
    ]
    # min/max length ratio < 0.5 → skipped before the expensive compare.
    assert _scan_near_duplicate_pairs(controls, 0.80) == []


def test_conflict_scan_flags_frequency_difference():
    controls = [
        {"id": "1", "ControlStatement": "Access reviews shall be performed monthly",
         "SourceDocumentCode": "DOC-A", "ProposedOwnerRole": "ISM"},
        {"id": "2", "ControlStatement": "Access reviews shall be performed quarterly",
         "SourceDocumentCode": "DOC-B", "ProposedOwnerRole": "ISM"},
    ]
    findings = _scan_conflict_pairs(controls, 0.60)
    assert len(findings) == 1
    assert "frequency differs" in findings[0]["reason"]


# -----------------------------------------------------------------------------
#  Standards-map traffic light (A4 — now takes pre-scoped clause_evidence)
# -----------------------------------------------------------------------------

_CTRL = {"id": "c1", "OwnerEntraId": "oid", "Status": "Active"}


def test_traffic_red_when_no_controls():
    assert _calculate_traffic_light([], []) == "Red"


def test_traffic_red_when_owner_unassigned():
    assert _calculate_traffic_light([{"id": "c1", "OwnerEntraId": "", "Status": "Active"}], []) == "Red"


def test_traffic_amber_when_control_but_no_evidence():
    assert _calculate_traffic_light([_CTRL], []) == "Amber"


def test_traffic_amber_when_evidence_submitted_not_verified():
    assert _calculate_traffic_light([_CTRL], [{"Status": "Submitted"}]) == "Amber"


def test_traffic_red_when_evidence_overdue_or_rejected():
    assert _calculate_traffic_light([_CTRL], [{"Status": "Overdue"}]) == "Red"
    assert _calculate_traffic_light([_CTRL], [{"Status": "Rejected"}]) == "Red"


def test_traffic_green_when_all_evidence_accepted():
    assert _calculate_traffic_light([_CTRL], [{"Status": "Accepted"}]) == "Green"
