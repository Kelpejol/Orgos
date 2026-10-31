# =============================================================================
# tests/ownership/test_resolver.py — Org Roles is the one role authority
#
# The resolver decides whether a control is Active and who may act on a record.
# It must match role names exactly as the role check (V07) does, let an agreed
# alias win over a job title, and never treat a job title as a role.
# =============================================================================

from ownership.resolver import OwnershipIndex

PERSON = {"oid": "p1", "display_name": "P", "email": "p@x"}
GROUPS = [{"name": "IT and Security Lead", "aliases": ["IT Manager"], "members": [PERSON]},
          {"name": "Empty Role", "aliases": [], "members": []}]
TITLES = {"IT Manager": [{"oid": "t1"}], "Head of Sales": [{"oid": "t2"}]}


def test_spellings_v07_accepts_resolve_to_the_role():
    idx = OwnershipIndex(GROUPS, TITLES)
    for spelling in ("IT & Security Lead", "it/security lead", "IT and Security-Lead"):
        hit = idx.resolve(spelling)
        assert hit["kind"] == "group" and hit["canonical"] == "IT and Security Lead"


def test_an_agreed_alias_wins_over_a_job_title_with_the_same_words():
    hit = OwnershipIndex(GROUPS, TITLES).resolve("IT Manager")
    assert hit["kind"] == "group" and hit["via_alias"] and hit["people"] == [PERSON]


def test_a_job_title_is_a_hint_and_never_an_owner():
    idx = OwnershipIndex(GROUPS, TITLES)
    hit = idx.resolve("Head of Sales")
    assert hit["kind"] == "job_title" and not hit["resolved"] and hit["people"] == []
    assert not idx.has_owner("Head of Sales") and not idx.owns("Head of Sales", "t2")


def test_a_role_with_no_members_is_a_role_but_has_no_owner_yet():
    idx = OwnershipIndex(GROUPS, TITLES)
    assert idx.resolve("Empty Role")["kind"] == "group" and not idx.has_owner("Empty Role")


def test_roles_for_a_user_come_from_org_roles_only():
    idx = OwnershipIndex(GROUPS, TITLES)
    assert idx.roles_for_user("t2") == set()
    assert "it and security lead" in idx.roles_for_user("p1")


async def test_statuses_are_not_rejudged_when_org_roles_cannot_be_read(monkeypatch):
    from unittest.mock import AsyncMock
    from control_register import status
    from ownership import resolver
    monkeypatch.setattr(resolver, "get_ownership_index",
                        AsyncMock(return_value=OwnershipIndex([], TITLES, groups_loaded=False)))
    monkeypatch.setattr(status.settings, "control_register_list_id", "cr")
    out = await status.recheck_control_statuses()
    assert out["changed"] == 0 and "not re-checked" in out["failures"][0]
