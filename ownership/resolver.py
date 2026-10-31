# =============================================================================
# ownership/resolver.py — resolve an owner ROLE to real people.
#
# WHY THIS EXISTS
#   OrgOS expresses ownership as a role STRING on the record:
#       Control Register / Record Tracker → OwnerRole  ("ISMS Lead",
#       "Compliance team", …) and OwnerEntraId is left empty.
#   Everything that asks "is this owned?" or "can this user act?" must
#   therefore resolve the role to people. Testing OwnerEntraId directly is
#   always wrong — it is never populated by the accept cascade.
#
#   Org Roles is the ONLY role authority (Bobby: a job title alone is never a role):
#     1. an Org Roles entry — by its name OR an agreed alias → its members.
#        Names are matched exactly as the role check (V07) matches them
#        (doc_standards/roles.norm: case, punctuation, "&" / "/" read as "and"),
#        so a role the check accepts is a role here too.
#     2. an Entra job title is only a HINT: it is reported (kind "job_title",
#        with the people as `hint_people`) so a screen can say "this is a job
#        title, not a role", but it resolves to nobody and never makes a control
#        Active or a person its owner. A name or alias in Org Roles always wins.
#
# The index is built once and cached (roles/groups change rarely), so batch
# callers (Standards Map, Gap Analyzer) resolve hundreds of controls without
# extra Graph calls.
# =============================================================================

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from config import settings
from graph.auth import get_graph_access_token

logger = logging.getLogger(__name__)

_TTL_SECONDS = 300  # 5 minutes
_cache: dict = {"index": None, "expires_at": 0.0}


def _norm(s: str) -> str:
    from doc_standards.roles import norm
    return norm(s)


class OwnershipIndex:
    """
    An immutable snapshot mapping role names → people. Lookups are synchronous
    so callers can resolve many records cheaply.

    people entries: {"oid", "display_name", "email"}
    """

    def __init__(self, groups: list[dict], job_titles: dict[str, list[dict]], *, groups_loaded: bool = True):
        # role key (normalised) → (kind, canonical_name, people)
        self._map: dict[str, tuple[str, str, list[dict]]] = {}
        # False when Org Roles could not be read: nothing may be judged Blocked on this index.
        self.groups_loaded = groups_loaded

        # Org Roles first: every name, then every agreed alias (a name beats another role's alias,
        # and the first role to claim a spelling keeps it — the same rule as RoleBook).
        for g in groups:
            name = g.get("name") or ""
            if name:
                self._map.setdefault(_norm(name), ("group", name, g.get("members") or []))
        for g in groups:
            name = g.get("name") or ""
            for alias in (g.get("aliases") or []):
                key = _norm(alias)
                if name and key:
                    self._map.setdefault(key, ("group", name, g.get("members") or []))
        # A job title only where no role claims the spelling — and only as a hint.
        for title, people in job_titles.items():
            self._map.setdefault(_norm(title), ("job_title", title, people))

    def resolve(self, role: str) -> dict:
        """
        Resolve a role string. Always returns a dict:
          {resolved, kind, canonical, via_alias, people}
        kind: "group" | "job_title" | "unresolved"
        """
        key = _norm(role)
        if not key:
            return {"resolved": False, "kind": "unresolved", "canonical": "",
                    "via_alias": False, "people": []}
        hit = self._map.get(key)
        if not hit:
            return {"resolved": False, "kind": "unresolved", "canonical": role,
                    "via_alias": False, "people": []}
        kind, canonical, people = hit
        if kind == "job_title":
            # Not a role: nobody is its owner. The people are only a hint for the screen.
            return {"resolved": False, "kind": "job_title", "canonical": canonical,
                    "via_alias": False, "people": [], "hint_people": people}
        return {
            "resolved": True,
            "kind": kind,
            "canonical": canonical,
            "via_alias": _norm(canonical) != key,
            "people": people,
        }

    def has_owner(self, role: str) -> bool:
        """True if the role resolves to at least one real person."""
        return bool(self.resolve(role)["people"])

    def owns(self, role: str, oid: str) -> bool:
        """True if `oid` is one of the people the role resolves to."""
        if not oid:
            return False
        return any((p.get("oid") or "") == oid for p in self.resolve(role)["people"])

    def roles_for_user(self, oid: str) -> set[str]:
        """Every role key (normalised) this user holds — for bulk filtering."""
        out: set[str] = set()
        if not oid:
            return out
        for key, (kind, _canon, people) in self._map.items():
            if kind == "group" and any((p.get("oid") or "") == oid for p in people):
                out.add(key)
        return out


async def _load_job_title_people() -> dict[str, list[dict]]:
    """Entra job title → the enabled users holding it."""
    titles: dict[str, list[dict]] = {}
    token = await get_graph_access_token()
    headers = {"Authorization": f"Bearer {token}", "ConsistencyLevel": "eventual"}
    url: Optional[str] = f"{settings.graph_base_url}/users"
    params: Optional[dict] = {
        "$select": "id,displayName,mail,userPrincipalName,jobTitle",
        "$filter": "accountEnabled eq true and jobTitle ne null",
        "$count": "true",
        "$top": "999",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            for u in data.get("value", []):
                title = (u.get("jobTitle") or "").strip()
                if not title:
                    continue
                titles.setdefault(title, []).append({
                    "oid": u.get("id", ""),
                    "display_name": u.get("displayName", ""),
                    "email": u.get("mail") or u.get("userPrincipalName", ""),
                })
            url = data.get("@odata.nextLink")
            params = None
    return titles


async def get_ownership_index(force: bool = False) -> OwnershipIndex:
    """Build (or reuse) the role→people index. Never raises — on failure it
    returns whatever it could load, so callers degrade instead of breaking."""
    now = time.time()
    if not force and _cache["index"] is not None and now < _cache["expires_at"]:
        return _cache["index"]

    groups: list[dict] = []
    groups_loaded = True
    try:
        from groups import service as groups_service
        groups = await groups_service.list_groups()
    except Exception as exc:
        groups_loaded = False
        logger.warning(f"Ownership index: Org Roles unavailable ({exc}) — no control will be re-judged on it")

    job_titles: dict[str, list[dict]] = {}
    try:
        job_titles = await _load_job_title_people()
    except Exception as exc:
        logger.warning(f"Ownership index: job titles unavailable ({exc})")

    index = OwnershipIndex(groups, job_titles, groups_loaded=groups_loaded)
    if groups_loaded:                       # never cache an index built without Org Roles
        _cache["index"] = index
        _cache["expires_at"] = now + _TTL_SECONDS
    return index


# ── convenience one-shots (prefer get_ownership_index() for batches) ─────────

async def role_has_owner(role: str) -> bool:
    return (await get_ownership_index()).has_owner(role)


async def user_owns_role(role: str, oid: str) -> bool:
    return (await get_ownership_index()).owns(role, oid)


async def resolve_owner_role(role: str) -> dict:
    return (await get_ownership_index()).resolve(role)
