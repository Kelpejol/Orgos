# tests/grc/test_user_search.py — the people search also finds mail-enabled groups (everybody@…)

from unittest.mock import AsyncMock, patch

from auth.validator import CurrentUser
from grc import router

USER = CurrentUser(oid="u", name="U", email="u@x", tenant_id="t", roles=[])


def graph(users, groups, groups_fail=False):
    async def fake(method, url, params=None, context=""):
        if url.endswith("/groups"):
            if groups_fail:
                raise RuntimeError("403 Group.Read.All missing")
            return {"value": groups}
        return {"value": users}
    return patch("graph.client._request", new=AsyncMock(side_effect=fake))


async def test_a_group_address_is_found_beside_people():
    with graph([{"id": "1", "displayName": "Eve Ryan", "mail": "eve@x.com"}],
               [{"id": "g", "displayName": "Everybody", "mail": "everybody@dragnet-solutions.com"},
                {"id": "h", "displayName": "No mail group", "mail": None}]):
        out = await router.search_users_endpoint(q="every", user=USER)
    assert [(r["email"], r["is_group"]) for r in out] == [
        ("eve@x.com", False), ("everybody@dragnet-solutions.com", True)]


async def test_people_still_come_back_when_groups_cannot_be_read():
    with graph([{"id": "1", "displayName": "Eve", "mail": "eve@x.com"}], [], groups_fail=True):
        out = await router.search_users_endpoint(q="eve", user=USER)
    assert [r["email"] for r in out] == ["eve@x.com"]
