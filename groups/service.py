# =============================================================================
# groups/service.py — OrgOS-managed people groups
#
# A group is a named set of people (e.g. "Compliance Team") that can be used as
# an owner in documents/controls/evidence — the same name is written in docs, so
# any member can act on it and (later) all members can be notified.
#
# Storage: a dedicated SharePoint list "OrgOS Groups", AUTO-PROVISIONED — this
# module resolves the list by name and creates it (with columns) on first use,
# so no manual list setup or .env change is required. The list id is cached in
# process. Item CRUD reuses graph.client; only list creation is done here.
# =============================================================================

import json
import logging
from typing import Optional

import httpx

from config import settings
from graph.auth import get_graph_access_token
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    resolve_user,
    update_list_item,
)

logger = logging.getLogger(__name__)

_LIST_NAME = "OrgOS Groups"
_list_id_cache: dict = {"id": None}
# Which columns actually exist on the list. The app cannot create columns
# (SharePoint returns 403), so writes must be filtered to columns that a human
# has added. `_cols_known` = we successfully read the schema.
_available_cols: set = set()
_cols_known: bool = False


class GroupsListNotProvisioned(RuntimeError):
    """Raised when the OrgOS Groups SharePoint list doesn't exist and the app
    lacks permission to create it — an admin must create it once."""

# Columns provisioned on the OrgOS Groups list (Title = the group name).
_GROUP_COLUMNS = [
    {"name": "Description",      "text": {"allowMultipleLines": True}},
    {"name": "Members",         "text": {"allowMultipleLines": True}},  # JSON array
    {"name": "Aliases",         "text": {"allowMultipleLines": True}},  # JSON array of alt names
    {"name": "Category",        "text": {}},
    {"name": "CreatedByEntraId","text": {}},
    {"name": "CreatedByName",   "text": {}},
    {"name": "Status",          "text": {}},  # "Active" | "Withdrawn"
]

# Cap on alternative names per group (Paul: 5–6 aliases per role/group).
_MAX_ALIASES = 6


def _clean_aliases(aliases) -> list[str]:
    """Normalise a list of alias strings: trim, drop blanks/dupes, cap at 6."""
    out: list[str] = []
    seen: set = set()
    for a in (aliases or []):
        s = (a or "").strip()
        key = s.lower()
        if s and key not in seen:
            seen.add(key)
            out.append(s)
    return out[:_MAX_ALIASES]


async def _graph(method: str, url: str, **kw) -> dict:
    token = await get_graph_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    headers.update(kw.pop("headers", {}))
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(method, url, headers=headers, **kw)
        resp.raise_for_status()
        return resp.json() if resp.content else {}


async def _ensure_columns(list_id: str) -> None:
    """
    Read the list's columns and record which exist, so writes can be filtered to
    real columns. Also *attempts* to create any missing ones — but the app is
    typically not permitted to create columns (403), in which case an admin must
    add them manually; the missing column just won't be written until then.
    Runs once per process.
    """
    global _cols_known
    if _cols_known:
        return
    base = settings.graph_base_url
    site = settings.sharepoint_site_id
    try:
        existing = await _graph("GET", f"{base}/sites/{site}/lists/{list_id}/columns",
                                params={"$select": "name"})
        have = {c.get("name") for c in existing.get("value", [])}
        for col in _GROUP_COLUMNS:
            if col["name"] not in have:
                try:
                    await _graph("POST", f"{base}/sites/{site}/lists/{list_id}/columns", json=col)
                    have.add(col["name"])
                    logger.info(f"Created column '{col['name']}' on '{_LIST_NAME}'")
                except Exception as exc:
                    logger.info(
                        f"Column '{col['name']}' missing on '{_LIST_NAME}' and could not be "
                        f"auto-created (add it manually to enable): {exc}"
                    )
        _available_cols.clear()
        _available_cols.update(have)
        _cols_known = True
    except Exception as exc:
        logger.warning(f"Could not read columns on '{_LIST_NAME}': {exc}")


def _has_col(name: str) -> bool:
    """True if it's safe to write `name`. If we couldn't read the schema, fall
    back to writing (preserves behaviour on the core columns that must exist)."""
    return (not _cols_known) or (name in _available_cols)


async def get_groups_list_id() -> str:
    """
    Resolve the OrgOS Groups list id. Tries to create the list if missing; if
    the app lacks permission (common — item writes are allowed but list creation
    isn't), raises GroupsListNotProvisioned so the caller can guide an admin to
    create the list once. Columns are auto-provisioned when the list is found.
    """
    if _list_id_cache["id"]:
        return _list_id_cache["id"]

    base = settings.graph_base_url
    site = settings.sharepoint_site_id

    # Resolve by display name first.
    try:
        data = await _graph(
            "GET", f"{base}/sites/{site}/lists",
            params={"$filter": f"displayName eq '{_LIST_NAME}'", "$select": "id,displayName"},
        )
        vals = data.get("value", [])
        if vals:
            _list_id_cache["id"] = vals[0]["id"]
            await _ensure_columns(_list_id_cache["id"])
            return _list_id_cache["id"]
    except Exception as exc:
        logger.warning(f"Could not look up '{_LIST_NAME}' list: {exc}")

    # Not found — try to create it (works only if the app may create lists).
    try:
        created = await _graph(
            "POST", f"{base}/sites/{site}/lists",
            json={"displayName": _LIST_NAME, "list": {"template": "genericList"}, "columns": _GROUP_COLUMNS},
        )
        _list_id_cache["id"] = created["id"]
        logger.info(f"Auto-provisioned SharePoint list '{_LIST_NAME}' → {created['id']}")
        return _list_id_cache["id"]
    except Exception as exc:
        logger.warning(f"'{_LIST_NAME}' list missing and could not be created: {exc}")
        raise GroupsListNotProvisioned(
            "The 'OrgOS Groups' SharePoint list does not exist yet and OrgOS is "
            "not permitted to create it. An admin must create a list named "
            "'OrgOS Groups' in the OrgOS site once — the columns are then added "
            "automatically."
        )


# ── mapping ───────────────────────────────────────────────────────────────────

def _parse_json_list(raw) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _to_group(item: dict) -> dict:
    f = item.get("fields", {}) or {}
    members = _parse_json_list(f.get("Members", ""))
    aliases = [str(a) for a in _parse_json_list(f.get("Aliases", "")) if str(a).strip()]
    return {
        "id":           str(item.get("id", "")),
        "name":         f.get("Title", ""),
        "description":  f.get("Description", ""),
        "category":     f.get("Category", ""),
        "aliases":      aliases,
        "members":      members,
        "member_count": len(members),
        "created_by":   f.get("CreatedByName", ""),
        "status":       f.get("Status", "Active"),
        "created":      item.get("createdDateTime", ""),
        "modified":     item.get("lastModifiedDateTime", ""),
    }


def _norm_member(m: dict) -> dict:
    return {
        "oid":          (m.get("oid") or "").strip(),
        "display_name": (m.get("display_name") or m.get("displayName") or "").strip(),
        "email":        (m.get("email") or "").strip(),
    }


# ── reads ─────────────────────────────────────────────────────────────────────

async def list_groups(include_withdrawn: bool = False) -> list[dict]:
    lid = await get_groups_list_id()
    items = await get_list_items(lid, _LIST_NAME)
    groups = [_to_group(i) for i in items]
    if not include_withdrawn:
        groups = [g for g in groups if g["status"] != "Withdrawn"]
    groups.sort(key=lambda g: (g["name"] or "").lower())
    return groups


async def get_group(group_id: str) -> dict:
    lid = await get_groups_list_id()
    return _to_group(await get_list_item(lid, _LIST_NAME, group_id))


async def group_names() -> list[str]:
    """Active group names — the owner vocabulary contribution from groups."""
    return [g["name"] for g in await list_groups() if g["name"]]


def _all_names(group: dict) -> list[str]:
    """A group's canonical name plus its aliases, lower-cased — for resolution."""
    names = [(group.get("name") or "").strip().lower()]
    names += [(a or "").strip().lower() for a in group.get("aliases", [])]
    return [n for n in names if n]


async def find_group_by_name(name: str) -> Optional[dict]:
    """Resolve a name to a group by its canonical name OR any of its aliases,
    so different wordings in documents map to the same group."""
    target = (name or "").strip().lower()
    if not target:
        return None
    for g in await list_groups():
        if target in _all_names(g):
            return g
    return None


async def user_in_group(name: str, oid: str) -> bool:
    """True if `oid` is a member of the group named `name`."""
    g = await find_group_by_name(name)
    if not g:
        return False
    return any((m.get("oid") or "") == oid for m in g.get("members", []))


# ── writes ────────────────────────────────────────────────────────────────────

async def create_group(name: str, description: str, category: str,
                       members: list[dict], creator_oid: str, creator_name: str,
                       aliases: Optional[list[str]] = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Group name is required.")
    if await find_group_by_name(name):
        raise ValueError(f"A group named '{name}' already exists.")

    lid = await get_groups_list_id()
    fields = {
        "Title":            name,
        "Description":      description or "",
        "Category":         category or "",
        "Members":          json.dumps([_norm_member(m) for m in (members or [])]),
        "CreatedByEntraId": creator_oid,
        "CreatedByName":    creator_name or "",
        "Status":           "Active",
    }
    if _has_col("Aliases"):
        fields["Aliases"] = json.dumps(_clean_aliases(aliases))
    return _to_group(await create_list_item(lid, _LIST_NAME, fields))


async def update_group(group_id: str, description: Optional[str],
                       category: Optional[str], name: Optional[str],
                       aliases: Optional[list[str]] = None) -> dict:
    lid = await get_groups_list_id()
    fields: dict = {}
    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise ValueError("Group name cannot be empty.")
        existing = await find_group_by_name(new_name)
        if existing and existing["id"] != group_id:
            raise ValueError(f"A group named '{new_name}' already exists.")
        fields["Title"] = new_name
    if description is not None:
        fields["Description"] = description
    if category is not None:
        fields["Category"] = category
    if aliases is not None and _has_col("Aliases"):
        fields["Aliases"] = json.dumps(_clean_aliases(aliases))
    if fields:
        await update_list_item(lid, _LIST_NAME, group_id, fields)
    return await get_group(group_id)


async def _resolve_member(oid: str, display_name: str, email: str) -> dict:
    """Fill in display_name/email from Entra when only an oid is supplied."""
    m = {"oid": oid, "display_name": display_name or "", "email": email or ""}
    if oid and (not display_name or not email):
        try:
            resolved = await resolve_user(oid)
            m["display_name"] = m["display_name"] or resolved.get("display_name", "")
            m["email"] = m["email"] or resolved.get("email", "")
        except Exception as exc:
            logger.debug(f"Could not resolve member {oid}: {exc}")
    return _norm_member(m)


async def add_members(group_id: str, new_members: list[dict]) -> dict:
    lid = await get_groups_list_id()
    group = await get_group(group_id)
    members = {m["oid"]: m for m in group["members"] if m.get("oid")}
    for m in new_members:
        resolved = await _resolve_member(
            (m.get("oid") or "").strip(),
            m.get("display_name") or m.get("displayName") or "",
            m.get("email") or "",
        )
        if resolved["oid"]:
            members[resolved["oid"]] = resolved
    await update_list_item(lid, _LIST_NAME, group_id, {"Members": json.dumps(list(members.values()))})
    return await get_group(group_id)


async def remove_member(group_id: str, oid: str) -> dict:
    lid = await get_groups_list_id()
    group = await get_group(group_id)
    members = [m for m in group["members"] if (m.get("oid") or "") != oid]
    await update_list_item(lid, _LIST_NAME, group_id, {"Members": json.dumps(members)})
    return await get_group(group_id)


async def soft_delete_group(group_id: str) -> None:
    lid = await get_groups_list_id()
    await update_list_item(lid, _LIST_NAME, group_id, {"Status": "Withdrawn"})
