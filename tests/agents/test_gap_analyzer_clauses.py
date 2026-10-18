# =============================================================================
# tests/agents/test_gap_analyzer_clauses.py — gaps from the shared catalogue
# =============================================================================

from agents.gap_analyzer.service import _find_gaps
from cdi.model import StandardsRef


class _Owners:
    def has_owner(self, role):
        return bool(role)


def control(cid, *refs, owner="CISO"):
    return {"id": cid, "statement": f"Control {cid}", "refs": list(refs),
            "owner_role": owner, "status": "Active"}


def gap_keys(gaps, category):
    return {(g["standard"], g["clause"]) for g in gaps if g["gap_category"] == category}


def test_a_control_on_a_neighbouring_clause_does_not_cover_another():
    gaps = _find_gaps([control("1", StandardsRef("ISO 27001", "A.5.18"))], [], _Owners())
    missing = gap_keys(gaps, "Missing artefact")
    assert ("ISO 27001", "A.5.18") not in missing
    assert ("ISO 27001", "A.5.15") in missing       # A.5.18 is no longer read as covering it


def test_iso_27001_and_9001_clauses_are_checked_separately():
    gaps = _find_gaps([control("1", StandardsRef("ISO 27001", "9.2"))], [], _Owners())
    assert ("ISO 9001", "9.2") in gap_keys(gaps, "Missing artefact")


def test_any_of_several_records_satisfies_the_record_requirement():
    c = control("1", StandardsRef("ISO 27001", "A.5.18"))
    records = [{"linked_ctrl": "1"}, {"linked_ctrl": "1"}]
    assert ("ISO 27001", "A.5.18") not in gap_keys(_find_gaps([c], records, _Owners()), "Evidence gap")
    assert ("ISO 27001", "A.5.18") in gap_keys(_find_gaps([c], [], _Owners()), "Evidence gap")


def test_a_clause_with_no_title_still_reads_well():
    gaps = _find_gaps([], [], _Owners())
    ndpa = next(g for g in gaps if g["standard"] == "NDPA" and g["clause"] == "S.24")
    assert "NDPA S.24" in ndpa["finding"]
