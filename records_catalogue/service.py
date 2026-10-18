# =============================================================================
# records_catalogue/service.py — the Records Catalogue as held in OrgOS
#
# Stored in the "Records Catalogue" SharePoint list, one item per record:
#   Title       the Record ID (REC-0676) — the key, never reused
#   RecordName  the canonical name, so the list is readable in SharePoint
#   Payload     the whole record as JSON (multi-line text)
# The app cannot create SharePoint columns, so the 29 Catalogue fields travel
# in one column rather than 29 an administrator would have to provision.
#
# The Catalogue changes only when Records Governance re-issues it, so reads are
# cached for ten minutes. Imports are idempotent upserts by Record ID and never
# delete: a record that disappears from a new workbook is reported, not removed.
# =============================================================================

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from config import settings
from graph.client import create_list_item, get_list_items, update_list_item
from records_catalogue.model import RecordEntry, normalise_name

logger = logging.getLogger(__name__)

LIST_NAME = "Records Catalogue"
_TTL_SECONDS = 600

_cache: dict = {}          # {"entries": {record_id: RecordEntry}, "at": float}


def _list_id() -> str:
    return settings.records_catalogue_list_id


def invalidate() -> None:
    _cache.clear()


# ── SharePoint item ↔ RecordEntry ───────────────────────────────────────────

def to_fields(entry: RecordEntry) -> dict:
    return {
        "Title": entry.record_id,
        "RecordName": entry.name,
        "Payload": json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True),
    }


def from_item(item: dict) -> Optional[RecordEntry]:
    f = item.get("fields") or {}
    try:
        data = json.loads(f.get("Payload") or "{}")
    except (TypeError, ValueError):
        logger.warning("Records Catalogue item %s has an unreadable Payload", item.get("id"))
        return None
    record_id = (f.get("Title") or data.get("record_id") or "").strip()
    if not record_id:
        return None
    data["record_id"] = record_id                      # the Title is the key
    data.setdefault("name", f.get("RecordName") or "")
    return RecordEntry.from_dict(data)


# ── reads ───────────────────────────────────────────────────────────────────

async def load(force: bool = False) -> dict[str, RecordEntry]:
    """Every record keyed by Record ID (cached)."""
    if not force and _cache and time.monotonic() - _cache["at"] < _TTL_SECONDS:
        return _cache["entries"]
    items = await get_list_items(_list_id(), LIST_NAME, top=999)
    entries = {e.record_id: e for e in filter(None, map(from_item, items))}
    _cache.update(entries=entries, at=time.monotonic())
    return entries


async def get(record_id: str) -> Optional[RecordEntry]:
    return (await load()).get(record_id.strip().upper())


def match_name(entries, name: str) -> list[RecordEntry]:
    """
    Governed records whose canonical name or an alias is exactly this name
    (case and punctuation ignored). More than one match is returned as-is: a
    person chooses, the system does not guess.
    """
    key = normalise_name(name)
    if not key:
        return []
    return [e for e in entries
            if not e.withdrawn
            and (normalise_name(e.name) == key or any(normalise_name(a) == key for a in e.aliases))]


async def find_by_name(name: str) -> list[RecordEntry]:
    return match_name((await load()).values(), name)


# ── import ──────────────────────────────────────────────────────────────────

@dataclass
class ImportPlan:
    create: list[RecordEntry] = field(default_factory=list)
    update: list[tuple[str, RecordEntry]] = field(default_factory=list)   # (item id, entry)
    unchanged: int = 0
    not_in_workbook: list[str] = field(default_factory=list)              # kept, reported
    duplicates_in_list: list[str] = field(default_factory=list)


def plan_import(existing_items: list[dict], workbook: list[RecordEntry]) -> ImportPlan:
    """What an import would change. Pure."""
    plan = ImportPlan()
    by_id: dict[str, dict] = {}
    for item in existing_items:
        rid = ((item.get("fields") or {}).get("Title") or "").strip()
        if rid in by_id:
            plan.duplicates_in_list.append(rid)
            continue
        if rid:
            by_id[rid] = item

    seen = set()
    for entry in workbook:
        seen.add(entry.record_id)
        item = by_id.get(entry.record_id)
        if item is None:
            plan.create.append(entry)
            continue
        current = item.get("fields") or {}
        wanted = to_fields(entry)
        if all(current.get(k) == v for k, v in wanted.items()):
            plan.unchanged += 1
        else:
            plan.update.append((str(item["id"]), entry))
    plan.not_in_workbook = sorted(rid for rid in by_id if rid not in seen)
    return plan


async def apply_import(plan: ImportPlan) -> None:
    for entry in plan.create:
        await create_list_item(_list_id(), LIST_NAME, to_fields(entry))
    for item_id, entry in plan.update:
        await update_list_item(_list_id(), LIST_NAME, item_id, to_fields(entry))
    invalidate()
