# =============================================================================
# tests/standards_map/test_catalogue.py — the clause list and how controls
# are matched to clauses
#
# Three bugs this replaces: the Standards Map counted a control mapped to
# A.5.18 under A.5.1 as well (prefix matching); it matched clause numbers with
# no regard to the standard, so ISO 9001 7.5 and ISO 27001 7.5 were one row;
# and it kept its own clause list, which had drifted from the Gap Analyzer's.
# =============================================================================

import json
from collections import Counter

from cdi.model import StandardsRef
from standards_map import catalogue
from standards_map.catalogue import clause, control_mapping, covers


def test_iso_27001_2022_annex_a_has_all_93_controls_in_four_themes():
    annex = [c for c in catalogue.CLAUSES.values()
             if c.standard == "ISO 27001" and c.clause.startswith("A.") and c.clause.count(".") == 2]
    assert len(annex) == 93
    assert Counter(c.clause.split(".")[1] for c in annex) == {"5": 37, "6": 8, "7": 14, "8": 34}


def test_a_neighbouring_clause_is_not_counted_as_its_prefix():
    assert not covers(clause("ISO 27001", "A.5.1"), StandardsRef("ISO 27001", "A.5.18"))
    assert covers(clause("ISO 27001", "A.5.18"), StandardsRef("ISO 27001", "A.5.18"))


def test_a_sub_clause_counts_towards_its_parent():
    assert covers(clause("ISO 27001", "7.5"), StandardsRef("ISO 27001", "7.5.2"))


def test_the_same_clause_number_in_two_standards_is_two_clauses():
    assert not covers(clause("ISO 27001", "7.5"), StandardsRef("ISO 9001", "7.5"))


def test_a_mapping_to_a_whole_standard_counts_towards_no_single_clause():
    assert not covers(clause("ISO 27001", "A.5.1"), StandardsRef("ISO 27001", ""))


def test_clauses_resolve_to_their_nearest_listed_parent_or_nothing():
    assert clause("ISO 9001", "7.5.3.2").clause == "7.5.3"
    assert clause("ISO 27001", "11.9") is None             # not in the standard
    assert clause("NDPA", "S.61").key == "NDPA S.61"       # a law accepts any section
    assert clause("ISO 27001", "A.5.29").title == "Information security during disruption"


def test_structured_mapping_is_preferred_to_the_free_text_field():
    fields = {"MappingJson": json.dumps([{"standard": "ISO 22301", "clause": "8.2"}]),
              "ISOClause": "A.5.1"}
    assert [r.key for r in control_mapping(fields)] == ["ISO 22301 8.2"]


def test_a_bare_clause_is_placed_only_where_unambiguous():
    assert [r.key for r in control_mapping({"ISOClause": "A.5.18"})] == ["ISO 27001 A.5.18"]
    assert [r.key for r in control_mapping({"ISOClause": "S.24"})] == ["NDPA S.24"]
    # 7.5 is in ISO 27001, 9001 and 22301 alike: left unplaced, not guessed.
    assert control_mapping({"ISOClause": "7.5"}) == []


def test_the_applicable_list_keeps_every_clause_both_old_lists_had():
    keys = {f"{s} {c}": r for s, c, r in catalogue.APPLICABLE}
    assert len(keys) == 23
    assert keys["ISO 27001 A.5.1"] == "policy"
    assert keys["ISO 27001 A.8.24"] == "control+record"
    assert keys["ISO 9001 7.5"] == "policy"
    # The five the map showed but the gap check skipped now require a control.
    for k in ("ISO 27001 A.7.1", "ISO 9001 8.4", "ISO 9001 9.1", "NDPA S.24", "NDPA S.30"):
        assert keys[k] == "control"
