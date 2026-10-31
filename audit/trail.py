# =============================================================================
# audit/trail.py — one way to write a decision to the Audit Log
#
# Every decision a person makes in OrgOS is recorded: who, what, on which item,
# why, and the state before and after (DINT §8). The review queue, Lifecycle and
# the classifier write their own richer entries; everything else — record
# verification and scheduling, gap decisions, strategic risks, role changes,
# owner reassignment — writes through here, in the Audit Log's own columns.
#
# Best-effort by design: a decision that has been applied is never rolled back
# because its audit entry failed, but the failure is logged loudly as an
# AUDIT GAP so it can be found.
# =============================================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger(__name__)


async def record(user, action: str, detail: str = "", *, item_id: str = "", item_type: str = "",
                 document_code: str = "", state_from: str = "", state_to: str = "") -> bool:
    """Write one Audit Log entry. Returns True if it was written."""
    if not settings.is_list_configured(settings.audit_log_list_id):
        return False
    from graph.client import create_list_item
    oid, name = getattr(user, "oid", "") or "", getattr(user, "name", "") or ""
    try:
        await create_list_item(settings.audit_log_list_id, "Audit Log", {
            "Title":              f"{action} — {document_code or item_id}"[:255],
            "Action":             action,
            "Decision":           action,
            "Rationale":          (detail or "")[:4000],
            "ReviewerOID":        oid,
            "ReviewerEntraId":    oid,
            "ReviewerName":       name,
            "ItemId":             str(item_id or ""),
            "ItemType":           item_type,
            "SourceDocumentCode": document_code,
            "StateFrom":          state_from,
            "StateTo":            state_to,
            "Timestamp":          datetime.now(timezone.utc).isoformat(),
        })
        return True
    except Exception as exc:
        logger.error(f"AUDIT GAP — '{action}' on {item_type} {item_id} not logged: {exc}")
        return False
