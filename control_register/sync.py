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
    decide_status,
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
    kind: str                       # create_item | update_item | close_item | refresh_control | refresh_status
    control_id: str
    candidate: dict
    change: str = ""                # New | Changed
    diff: list = field(default_factory=list)
    queue_item_id: str = ""
    control_item_id: str = ""
    fields: dict = field(default_factory=dict)      # a resolution item's own fields


@dataclass
class SyncPlan:
    actions: list[SyncAction] = field(default_factory=list)
    unchanged: int = 0
    already_queued: int = 0
    declined: int = 0
    contested: list[str] = field(default_factory=list)
    no_longer_defined: list[str] = field(default_factory=list)
    duplicate_controls: list[str] = field(default_factory=list)
    _status: dict = field(default_factory=dict, repr=False)   # cid → (Status, BlockedReason)

    def count(self, kind: str) -> int:
        return sum(a.kind == kind for a in self.actions)


def _json(fields: dict, column: str) -> Optional[dict]:
    try:
        return json.loads(fields.get(column) or "null")
    except (TypeError, ValueError):
        return None


def _confirmed_by_id(register: list[dict], plan: SyncPlan) -> dict[str, tuple[str, Optional[dict]]]:
    out: dict[str, tuple[str, Optional[dict]]] = {}
    plan._status = {}
    for item in register:
        f = item.get("fields") or {}
        cid = (f.get("ControlId") or "").strip()
        if not cid or f.get("Status") in RETIRED_CONTROL:
            continue
        if cid in out:
            plan.duplicate_controls.append(cid)
            continue
        out[cid] = (str(item["id"]), _json(f, "DefinitionJson"))
        plan._status[cid] = (f.get("Status") or "", f.get("BlockedReason") or "")
    return out


def _latest_queued(queue: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in sorted(queue, key=lambda i: int(str(i.get("id") or 0) or 0)):
        f = item.get("fields") or {}
        cid = (f.get("ControlId") or "").strip()
        if cid and not f.get("ResolutionKey"):        # definitions only, never Zone 2 items
            out[cid] = item
    return out


def plan_sync(index: LibraryIndex, register: list[dict], queue: list[dict],
              resolve=None) -> SyncPlan:
    """
    `resolve` (OwnershipIndex.resolve), when given, also re-checks the status
    of every confirmed control: one Blocked for an unrecognised role becomes
    Active once the role is recognised, and the reverse.
    """
    plan = SyncPlan(contested=index.contested_ids)
    confirmed = _confirmed_by_id(register, plan)
    queued = _latest_queued(queue)

    for cid in index.defined_ids:
        doc, control = index.definition(cid)
        candidate = candidate_from(doc, control, index)
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

    if resolve is not None:
        for cid, (control_item_id, definition) in confirmed.items():
            if not definition:
                continue
            if plan._status.get(cid, ("",))[0] not in ("Active", "Blocked"):
                continue                     # a status a person set (Under Review, …) stands
            status, reason = decide_status(definition, resolve)
            if (status, reason) != plan._status.get(cid):
                plan.actions.append(SyncAction("refresh_status", cid, definition,
                                               control_item_id=control_item_id,
                                               fields={"Status": status, "BlockedReason": reason}))

    defined = set(index.defined_ids) | set(index.contested_ids)
    plan.no_longer_defined = sorted(cid for cid in confirmed if cid not in defined)
    return plan


# ── what is written ─────────────────────────────────────────────────────────

def queue_fields(action: SyncAction) -> dict:
    if action.fields:
        return action.fields
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
                    "CascadeResult": a.fields.get("CascadeResult") or (
                        "Closed by library sync: the defining document now "
                        "matches the confirmed definition."),
                })
            elif a.kind == "refresh_status":
                await update_list_item(cr, "Control Register", a.control_item_id, a.fields)
            elif a.kind == "refresh_control":
                await update_list_item(cr, "Control Register", a.control_item_id,
                                       refresh_fields(a.candidate))
        except Exception as exc:
            logger.error("Library sync %s %s failed: %s", a.kind, a.control_id, exc)
            failures.append(f"{a.kind} {a.control_id}: {exc}")
    return failures


# =============================================================================
#  Zone 2 — references that do not resolve
#
# One item per problem, not per citation: a REC ID cited by five documents is
# one admission request listing all five. Each item carries a ResolutionKey;
# a sync closes it once the problem is gone (the record admitted to the
# Catalogue, the second definition removed), and a declined item is not
# raised again.
# =============================================================================

ZONE2_ITEM_TYPE = "Orphan"


def _latest_by_key(queue: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in sorted(queue, key=lambda i: int(str(i.get("id") or 0) or 0)):
        key = ((item.get("fields") or {}).get("ResolutionKey") or "").strip()
        if key:
            out[key] = item
    return out


def _record_problems(index: LibraryIndex, catalogue: dict) -> dict[str, dict]:
    out = {}
    for rid, cited_in in sorted(index.record_citations().items()):
        entry = catalogue.get(rid)
        if entry is None:
            reason = (f"{rid} is cited but is not in the Enterprise Records Catalogue. "
                      "Records Governance assigns Record IDs: either admit the record "
                      "or correct the citation.")
            kind = "RECORD_NOT_IN_CATALOGUE"
        elif entry.withdrawn:
            reason = (f"{rid} ({entry.name}) is a withdrawn duplicate proposal in the "
                      "Catalogue. Cite the governed record instead.")
            kind = "WITHDRAWN_RECORD_CITED"
        else:
            continue
        out[f"RECORD:{rid}"] = {
            "Title": f"{rid}: record cited but not governed"[:255],
            "OrphanClassification": kind,
            "ResponsibilityStatement": reason,
            "OrphanReason": "Cited in: " + "; ".join(cited_in),
            "SourceDocumentCode": cited_in[0],
            "SourceDocumentCode2": "; ".join(cited_in[1:])[:255],
        }
    return out


def _definition_conflicts(index: LibraryIndex) -> dict[str, dict]:
    out = {}
    for cid in index.contested_ids:
        docs = list(dict.fromkeys(
            s.document.header.code or s.document.filename for s in index.stated_by[cid]))
        out[f"DEFINED-TWICE:{cid}"] = {
            "Title": f"{cid}: defined by more than one document"[:255],
            "OrphanClassification": "CONTROL_DEFINED_TWICE",
            "ResponsibilityStatement": (
                f"{cid} is defined by {' and '.join(docs)} with equal authority, so OrgOS "
                "cannot tell which governs. Select the governing document; the other is "
                "revised through Document Lifecycle. Until then the control is not synced."),
            "OrphanReason": "Defined in: " + "; ".join(docs),
            "SourceDocumentCode": docs[0],
            "SourceDocumentCode2": "; ".join(docs[1:])[:255],
        }
    return out


def plan_resolutions(index: LibraryIndex, queue: list[dict],
                     catalogue: Optional[dict] = None) -> list[SyncAction]:
    """
    Zone 2 items for references that do not resolve. `catalogue` maps Record ID
    → RecordEntry; None skips record checks (the Catalogue is not loaded).
    """
    problems = _definition_conflicts(index)
    if catalogue is not None:
        problems.update(_record_problems(index, catalogue))

    latest = _latest_by_key(queue)
    actions = []
    for key, fields in problems.items():
        item = latest.get(key)
        if item is not None and ((item.get("fields") or {}).get("ReviewStatus") or "") != "Superseded":
            # Waiting, or a person has decided it (a fix may be under way in
            # Document Lifecycle). Raised again only if it was resolved and recurred.
            continue
        actions.append(SyncAction("create_item", key, {}, fields={
            **fields,
            "ItemType": ZONE2_ITEM_TYPE,
            "ResolutionKey": key,
            "ReviewStatus": "Pending Review",
        }))

    checked = {"DEFINED-TWICE"} | ({"RECORD"} if catalogue is not None else set())
    for key, item in latest.items():
        status = ((item.get("fields") or {}).get("ReviewStatus") or "").strip()
        if key.split(":", 1)[0] in checked and key not in problems and status in PENDING:
            actions.append(SyncAction("close_item", key, {}, queue_item_id=str(item["id"]),
                                      fields={"CascadeResult": "Closed by library sync: "
                                                               "the reference now resolves."}))
    return actions
