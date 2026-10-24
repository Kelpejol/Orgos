# =============================================================================
# control_register/status.py — re-check Active / Blocked when roles change
#
# A control is Active only when its Control owner is recognised in Org Roles,
# by its name or an agreed alias. When someone creates, renames or changes
# a role in Org Roles, every confirmed control
# is re-checked straight away — nobody has to run a script. The daily
# evidence run re-checks too, as a safety net.
#
# Only Active and Blocked are touched: a status a person set (Under Review, …)
# stands. Nothing else on the row changes.
# =============================================================================

from __future__ import annotations

import asyncio
import logging

from config import settings

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_tasks: set[asyncio.Task] = set()


async def recheck_control_statuses() -> dict:
    from cdi.library import LibraryIndex
    from control_register.sync import apply_sync, plan_sync
    from graph.client import get_list_items
    from ownership.resolver import get_ownership_index

    if not settings.is_list_configured(settings.control_register_list_id):
        return {"changed": 0, "failures": []}
    async with _lock:
        owners = await get_ownership_index(force=True)      # the change just made
        register = await get_list_items(settings.control_register_list_id, "Control Register")
        plan = plan_sync(LibraryIndex([]), register, [], owners.resolve)
        plan.actions = [a for a in plan.actions if a.kind == "refresh_status"]
        failures = await apply_sync(plan) if plan.actions else []
    changed = [f"{a.control_id} → {a.fields['Status']}" for a in plan.actions]
    if changed:
        logger.info("Control statuses re-checked against roles: %s", ", ".join(changed))
    return {"changed": len(plan.actions) - len(failures), "detail": changed, "failures": failures}


def recheck_soon() -> None:
    """Fire-and-forget after a role change; the request doesn't wait for it."""
    async def run():
        try:
            from doc_standards import gate
            gate.invalidate()                  # a role changed: results that depend on Org Roles are out of date
            await recheck_control_statuses()
        except Exception:
            logger.exception("Re-checking control statuses after a role change failed")

    task = asyncio.create_task(run())
    _tasks.add(task)                       # asyncio holds tasks weakly
    task.add_done_callback(_tasks.discard)
