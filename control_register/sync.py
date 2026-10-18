# =============================================================================
# control_register/sync.py — bring the Control Register in line with the library
#
# For every Control ID the library defines, compare its definition with what is
# confirmed in the Control Register:
#   unchanged → nothing for a reviewer (derived data silently refreshed)
#   changed   → one Zone 1 item showing the field-level diff
#   new       → one Zone 1 item
# A control already waiting in the queue is updated in place, never queued
# twice; a change a reviewer already rejected is not raised again until the
# document changes again. Re-syncing an unchanged library produces nothing.
#
# Nothing is withdrawn here. A confirmed control no longer defined anywhere is
# reported — superseding is the Document Lifecycle's decision, not a sync's.
#
# plan_sync is pure; apply_sync performs the writes.
# =============================================================================

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from cdi.library import LibraryIndex
from control_register.definitions import (
    candidate_from,
    completeness,
    diff,
    is_unchanged,
)

logger = logging.getLogger(__name__)

ITEM_TYPE = "Extraction"                                # Zone 1
PENDING = {"", "Pending Review", "Pending Second Review", "Blocked", "Routed to Owner"}
DECLINED = {"Rejected", "False Positive"}
RETIRED_CONTROL = {"Withdrawn", "Superseded"}


@dataclass
class SyncAction:
    kind: str                       # create_item | update_item | close_item | refresh_control
    control_id: str
    candidate: dict
    change: str = ""                # New | Changed
    diff: list = field(default_factory=list)
    queue_item_id: str = ""
    control_item_id: str = ""


@dataclass
class SyncPlan:
    actions: list[SyncAction] = field(default_factory=list)
    unchanged: int = 0
    already_queued: int = 0
    declined: int = 0
    contested: list[str] = field(default_factory=list)
    no_longer_defined: list[str] = field(default_factory=list)
    duplicate_controls: list[str] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(a.kind == kind for a in self.actions)


def _json(fields: dict, column: str) -> Optional[dict]:
    try:
        return json.loads(fields.get(column) or "null")
    except (TypeError, ValueError):
        return None


def _confirmed_by_id(register: list[dict], plan: SyncPlan) -> dict[str, tuple[str, Optional[dict]]]:
    out: dict[str, tuple[str, Optional[dict]]] = {}
    for item in register:
        f = item.get("fields") or {}
        cid = (f.get("ControlId") or "").strip()
        if not cid or f.get("Status") in RETIRED_CONTROL:
            continue
        if cid in out:
            plan.duplicate_controls.append(cid)
            continue
        out[cid] = (str(item["id"]), _json(f, "DefinitionJson"))
    return out


def _latest_queued(queue: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in sorted(queue, key=lambda i: int(str(i.get("id") or 0) or 0)):
        f = item.get("fields") or {}
        cid = (f.get("ControlId") or "").strip()
        if cid:
            out[cid] = item
    return out


def plan_sync(index: LibraryIndex, register: list[dict], queue: list[dict]) -> SyncPlan:
    plan = SyncPlan(contested=index.contested_ids)
    confirmed = _confirmed_by_id(register, plan)
    queued = _latest_queued(queue)

    for cid in index.defined_ids:
        doc, control = index.definition(cid)
        candidate = candidate_from(doc, control)
        control_item_id, current = confirmed.get(cid, ("", None))
        latest = queued.get(cid)
        latest_fields = (latest or {}).get("fields") or {}
        latest_status = (latest_fields.get("ReviewStatus") or "").strip()
        latest_pending = latest is not None and latest_status in PENDING

        if is_unchanged(current, candidate):
            plan.unchanged += 1
            if current != candidate:
                plan.actions.append(SyncAction("refresh_control", cid, candidate,
                                               control_item_id=control_item_id))
            if latest_pending:
                plan.actions.append(SyncAction("close_item", cid, candidate,
                                               queue_item_id=str(latest["id"])))
            continue

        change = "Changed" if current else "New"
        changes = diff(current, candidate)
        proposed = _json(latest_fields, "CandidateJson") if latest else None
        same_proposal = proposed is not None and not diff(proposed, candidate)

        if same_proposal and latest_status in DECLINED:
            plan.declined += 1
        elif same_proposal and latest_pending:
            plan.already_queued += 1
        elif latest_pending:
            plan.actions.append(SyncAction("update_item", cid, candidate, change, changes,
                                           queue_item_id=str(latest["id"]),
                                           control_item_id=control_item_id))
        else:
            plan.actions.append(SyncAction("create_item", cid, candidate, change, changes,
                                           control_item_id=control_item_id))

    defined = set(index.defined_ids) | set(index.contested_ids)
    plan.no_longer_defined = sorted(cid for cid in confirmed if cid not in defined)
    return plan


# ── what is written ─────────────────────────────────────────────────────────

def queue_fields(action: SyncAction) -> dict:
    c = action.candidate
    flag, reason = completeness(c)
    return {
        "Title": f"{c['control_id']} {c['title']}"[:255],
        "ItemType": ITEM_TYPE,
        "ControlId": c["control_id"],
        "ChangeKind": action.change,
        "CandidateJson": json.dumps(c, ensure_ascii=False, sort_keys=True),
        "DiffJson": json.dumps(action.diff, ensure_ascii=False),
        "SourceDocumentCode": c["defined_in_label"],
        "SourceClause": c["defined_in"]["section"][:255],
        "ControlStatement": c["requirement"],
        "RiskStatement": c["risk"],
        "ProposedOwnerRole": c["accountable"],
        "ISOClause": c["mapping_as_written"][:255],
        "CompletenessFlag": flag,
        "DeficiencyReason": reason,
        "ReviewStatus": "Pending Review",
        "Decision": "",
        "DecisionRationale": "",
        "CascadeResult": "",
    }


def control_fields(candidate: dict, status: str, blocked_reason: str) -> dict:
    """The Control Register row for a confirmed definition."""
    return {
        "Title": f"{candidate['control_id']} {candidate['title']}"[:255],
        "ControlId": candidate["control_id"],
        "DefinitionJson": json.dumps(candidate, ensure_ascii=False, sort_keys=True),
        "MappingJson": json.dumps(candidate["mapping"], ensure_ascii=False),
        "ControlStatement": candidate["requirement"],
        "OwnerRole": candidate["accountable"],
        "ISOClause": candidate["mapping_as_written"][:255],
        "SourceDocument": candidate["defined_in_label"],
        "SourceClause": candidate["defined_in"]["section"][:255],
        "RiskImplication": candidate["risk"][:500],
        "Status": status,
        "BlockedReason": blocked_reason,
    }


def refresh_fields(candidate: dict) -> dict:
    """Derived data only — status and confirmation are untouched."""
    return {
        "DefinitionJson": json.dumps(candidate, ensure_ascii=False, sort_keys=True),
        "MappingJson": json.dumps(candidate["mapping"], ensure_ascii=False),
        "SourceClause": candidate["defined_in"]["section"][:255],
    }


async def apply_sync(plan: SyncPlan) -> list[str]:
    """Perform the plan. Returns one line per write that failed (others go ahead)."""
    from config import settings
    from graph.client import create_list_item, update_list_item

    q, cr = settings.ai_review_queue_list_id, settings.control_register_list_id
    failures = []
    for a in plan.actions:
        try:
            if a.kind == "create_item":
                await create_list_item(q, "AI Review Queue", queue_fields(a))
            elif a.kind == "update_item":
                await update_list_item(q, "AI Review Queue", a.queue_item_id, queue_fields(a))
            elif a.kind == "close_item":
                await update_list_item(q, "AI Review Queue", a.queue_item_id, {
                    "ReviewStatus": "Superseded",
                    "CascadeResult": "Closed by library sync: the defining document now "
                                     "matches the confirmed definition.",
                })
            elif a.kind == "refresh_control":
                await update_list_item(cr, "Control Register", a.control_item_id,
                                       refresh_fields(a.candidate))
        except Exception as exc:
            logger.error("Library sync %s %s failed: %s", a.kind, a.control_id, exc)
            failures.append(f"{a.kind} {a.control_id}: {exc}")
    return failures
