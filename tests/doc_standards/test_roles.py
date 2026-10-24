# =============================================================================
# tests/doc_standards/test_roles.py — does this role exist, and which is meant?
#
# The properties that matter: only EXISTING roles are ever suggested; a job
# title is not a role; a field name is not a role; a good suggestion is the
# one a person would pick, with a reason they can read.
# =============================================================================

import pytest

from doc_standards.roles import Role, RoleBook, is_placeholder, names_several, norm, similarity

ROLES = RoleBook([
    Role("1", "Information Security Officer", ("ISO", "Infosec Officer")),
    Role("2", "Chief Compliance Officer", ()),
    Role("3", "Head of IT and Infrastructure", ("Head of IT",)),
    Role("4", "Compliance Executive (QMS & NDPA)", ()),
    Role("5", "HR Manager", ()),
    Role("6", "Managing Director / CEO", ()),
])


def test_a_role_is_found_by_its_name_whatever_the_case_spacing_or_punctuation():
    assert ROLES.find("Information Security Officer").group_id == "1"
    assert ROLES.find("  information   SECURITY officer. ").group_id == "1"
    assert ROLES.find("Managing Director / CEO").group_id == "6"
    assert ROLES.find("Managing Director and CEO").group_id == "6"       # "/" and "and" read alike


def test_an_agreed_alias_finds_its_role():
    assert ROLES.find("Head of IT").group_id == "3"
    assert ROLES.find("Infosec Officer").group_id == "1"


def test_something_that_is_not_a_role_is_not_found():
    for text in ("Chief Technology Officer", "", "Control Owner", "Information Security"):
        assert ROLES.find(text) is None


@pytest.mark.parametrize("written,expected", [
    ("Info Sec Officer", "1"),                       # abbreviated words
    ("Information Security Manager", "1"),           # close, not the same
    ("Chief Compliance Officr", "2"),                # typo
    ("CCO", "2"),                                    # initials
    ("Head of IT & Infrastructure", "3"),
    ("Compliance Executive", "4"),                   # without the bracketed part
    ("HR Mgr", "5"),
])
def test_the_role_a_person_means_is_the_first_suggestion(written, expected):
    suggestions = ROLES.suggest(written)
    assert suggestions and suggestions[0].role.group_id == expected, [(s.role.name, s.score) for s in suggestions]
    assert suggestions[0].reason


def test_only_roles_that_exist_are_ever_suggested():
    names = {r.name for r in ROLES.roles}
    for written in ("Info Sec Officer", "Chief Compliance Officr", "Marketing Lead", "Janitor"):
        assert {s.role.name for s in ROLES.suggest(written)} <= names


def test_nothing_is_suggested_when_nothing_is_close():
    assert ROLES.suggest("Marketing Lead") == [] and ROLES.suggest("Janitor") == []


def test_a_field_name_is_not_a_role_and_gets_no_suggestion():
    for text in ("Control Owner", "Document Owner", "Custodian Role", "control owner."):
        assert is_placeholder(text) and ROLES.suggest(text) == []
    assert not is_placeholder("Information Security Officer")


def test_at_most_three_suggestions_best_first_one_per_role():
    book = RoleBook([Role(str(i), f"Compliance Officer {i}") for i in range(6)] + [Role("x", "Compliance Executive")])
    out = book.suggest("Compliance Officer")
    assert len(out) == 3 and [s.score for s in out] == sorted((s.score for s in out), reverse=True)
    assert len({s.role.group_id for s in out}) == 3


def test_a_suggestion_through_an_alias_says_so():
    s = ROLES.suggest("Infosec Officr")[0]
    assert s.role.group_id == "1"


def test_two_roles_in_one_value_are_noticed_but_a_name_with_and_or_slash_is_one_role():
    assert names_several("Information Security Officer; IT owners")
    assert not names_several("Managing Director / CEO") and not names_several("Head of IT and Infrastructure")


def test_an_empty_role_book_suggests_nothing_and_finds_nothing():
    empty = RoleBook()
    assert len(empty) == 0 and empty.find("Information Security Officer") is None and empty.suggest("ISO") == []


def test_the_book_is_built_from_org_roles_groups_ignoring_nameless_ones():
    book = RoleBook.from_groups([{"id": "9", "name": "Legal Counsel", "aliases": ["GC", " "]}, {"id": "8", "name": ""}])
    assert [r.name for r in book.roles] == ["Legal Counsel"] and book.find("GC").group_id == "9"


def test_similarity_is_symmetric_enough_to_trust_and_bounded():
    for a, b in (("Info Sec Officer", "Information Security Officer"), ("HR Mgr", "HR Manager")):
        assert 0 <= similarity(a, b)[0] <= 100 and similarity(a, b)[0] > 50
    assert similarity("", "x")[0] == 0 and norm("A & B / C") == "a and b and c"


def test_a_phrase_describing_kinds_of_roles_is_not_a_role_and_gets_no_suggestions():
    from doc_standards.roles import describes_a_group
    assert describes_a_group("Requester, approver, reviewer and owner roles")
    assert not describes_a_group("Lead, Assessment Research, Psychometrics and AI")
    assert not describes_a_group("Records Governance")
