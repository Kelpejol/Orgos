# =============================================================================
# evidence/service.py — keep evidence obligations in step with the controls
#
# sync_obligations()  reconcile the Evidence Tracker with every confirmed
#                     control's stated records (after an accept, and daily)
# start_clocks()      start each scheduled obligation's clock once someone
#                     holds its Control owner role (the first record is due
#                     one period later)
# refresh_states()    write each obligation's current state (Due soon, Late,
#                     Missing, Stale, …) to its row when it changes, so Power
#                     Automate flows watching the list notify the owner
#
# The Evidence Tracker list holds one row per obligation (ObligationKey =
# "CONTROL|REC-nnnn"). Rows without a key are the older one-per-control rows;
# they are left as they are.
# =============================================================================

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from config import settings
from evidence.obligations import assess, plan_obligations
from graph.client import create_list_item, get_list_items, update_list_item

logger = logging.getLogger(__name__)

LIST_NAME = "Evidence Tracker"


def _list_id() -> str:
    return settings.evidence_tracker_list_id


async def _confirmed_controls() -> list[dict]:
    items = await get_list_items(settings.control_register_list_id, "Control Register")
    out = []
    for i in items:
        f = i.get("fields") or {}
        try:
            definition = json.loads(f.get("DefinitionJson") or "null")
        except (TypeError, ValueError):
            definition = None
        if f.get("ControlId") and definition:
            out.append({"control_id": f["ControlId"], "status": f.get("Status", ""),
                        "definition": definition,
                        # set by Compliance in Extraction Review when the document states no schedule
                        "schedule_days": int(float(f.get("RecordScheduleDays") or 0)),
                        "schedule_set_by": f.get("RecordScheduleSetBy") or ""})
    return out


async def _catalogue() -> Optional[dict]:
    from graph.exceptions import SharePointListNotConfiguredError
    from records_catalogue import service as catalogue

    try:
        return (await catalogue.load()) or None      # empty = not imported yet
    except SharePointListNotConfiguredError:
        return None


async def sync_obligations() -> dict:
    """Create, refresh and retire obligations. Returns counts and failures."""
    controls = await _confirmed_controls()
    existing = await get_list_items(_list_id(), LIST_NAME)
    actions = plan_obligations(controls, existing, await _catalogue())

    from graph.bulk import run_writes

    def write(a):
        if a.kind == "create":
            return create_list_item(_list_id(), LIST_NAME, a.fields)
        return update_list_item(_list_id(), LIST_NAME, a.item_id, a.fields)

    failures = await run_writes([(f"{a.kind} {a.key}", lambda a=a: write(a)) for a in actions])
    failed = {f.split(":", 1)[0] for f in failures}
    counts = {k: sum(a.kind == k and f"{a.kind} {a.key}" not in failed for a in actions)
              for k in ("create", "update", "retire")}
    logger.info("Evidence obligations synced: %s, %d failure(s)", counts, len(failures))
    return {**counts, "failures": failures}


def clocks_to_start(items: list[dict], holders, today: Optional[date] = None) -> list[tuple[str, dict]]:
    """
    (item id, fields) for each scheduled obligation whose clock has not started and whose
    Control owner role now has someone in it: it starts today. `holders(role)` → people. Pure.
    """
    today = today or date.today()
    out = []
    for item in items:
        f = item.get("fields") or {}
        if (f.get("ObligationKey") and f.get("Status") != "Withdrawn"
                and int(float(f.get("CheckFrequencyDays") or 0)) > 0
                and not f.get("ScheduledFrom") and not f.get("LastRecordDate")
                and holders(f.get("OwnerRole") or "")):
            out.append((str(item["id"]), {"ScheduledFrom": today.isoformat()}))
    return out


async def start_clocks(items: Optional[list[dict]] = None) -> dict:
    """Start the clocks that can start: scheduled, and someone holds the Control owner role."""
    from ownership.resolver import get_ownership_index

    owners = await get_ownership_index()
    if not getattr(owners, "groups_loaded", True):
        return {"started": 0, "failed": 0}            # without Org Roles nobody holds anything: wait
    items = items if items is not None else await get_list_items(_list_id(), LIST_NAME)
    starts = clocks_to_start(items, lambda role: owners.resolve(role).get("people") if role else [])
    failed = 0
    for item_id, fields in starts:
        try:
            await update_list_item(_list_id(), LIST_NAME, item_id, fields)
        except Exception as exc:
            failed += 1
            logger.error("Could not start the schedule of obligation %s: %s", item_id, exc)
    return {"started": len(starts) - failed, "failed": failed}


def state_changes(items: list[dict], today: Optional[date] = None) -> list[tuple[str, dict]]:
    """(item id, fields) for each obligation whose stored state is out of date. Pure."""
    out = []
    for item in items:
        f = item.get("fields") or {}
        if not f.get("ObligationKey"):
            continue
        a = assess(f, today)
        due = a.next_due.isoformat() if a.next_due else ""
        stored = (f.get("State") or "", f.get("StateDetail") or "", str(f.get("NextDue") or "")[:10])
        if stored != (a.state, a.detail[:255], due):
            out.append((str(item["id"]), {"State": a.state, "StateDetail": a.detail[:255],
                                          "NextDue": due or None}))
    return out


async def refresh_states() -> dict:
    """Daily: bring the stored State of every obligation up to today."""
    items = await get_list_items(_list_id(), LIST_NAME)
    changes = state_changes(items)
    failed = 0
    for item_id, fields in changes:
        try:
            await update_list_item(_list_id(), LIST_NAME, item_id, fields)
        except Exception as exc:
            failed += 1
            logger.error("Could not update state of obligation %s: %s", item_id, exc)
    return {"changed": len(changes) - failed, "failed": failed}


async def run_daily() -> None:
    """Scheduled job: reconcile obligations, then refresh their states."""
    for name in ("evidence_tracker_list_id", "control_register_list_id"):
        if not settings.is_list_configured(getattr(settings, name)):
            logger.debug("Evidence obligations: %s not configured — skipping", name)
            return
    try:
        # Roles may have changed since yesterday (Org Roles re-checks at once;
        # this is the safety net).
        from control_register.status import recheck_control_statuses
        await recheck_control_statuses()
    except Exception:
        logger.exception("Evidence daily run: re-checking control statuses failed")
    try:
        synced = await sync_obligations()
        clocks = await start_clocks()
        states = await refresh_states()
        logger.info("Evidence daily run: obligations %s; clocks %s; states %s", synced, clocks, states)
    except Exception as exc:
        logger.error("Evidence daily run failed: %s", exc)
