# =============================================================================
# jobs/sensitisation_deadline.py — Sensitisation deadline reminders
# Runs daily at 09:00 WAT via APScheduler.
# Checks lifecycle documents in Sensitisation stage and logs warnings for
# those whose deadline is expired or expiring within 2 days.
# (Teams notifications would be wired here via Power Automate — see POWER_AUTOMATE_GUIDE.md)
# =============================================================================

import logging
from datetime import date, timedelta

from config import settings
from graph.client import get_list_items, update_list_item

logger = logging.getLogger(__name__)


async def check_sensitisation_deadlines() -> None:
    """
    Scheduled job: identify lifecycle documents in Sensitisation with imminent/expired deadlines.
    Logs warnings for operator awareness.
    In a full deployment, this is the hook point for sending deadline reminder notifications.
    """
    if not settings.is_list_configured(settings.document_lifecycle_list_id):
        logger.debug("Sensitisation deadline check: lifecycle list not configured — skipping")
        return

    logger.info("Sensitisation deadline check: scanning lifecycle documents…")

    today    = date.today()
    warning_threshold = today + timedelta(days=2)

    try:
        items = await get_list_items(
            settings.document_lifecycle_list_id,
            "Document Lifecycle",
        )
    except Exception as exc:
        logger.error(f"Sensitisation deadline check: failed to read lifecycle list: {exc}")
        return

    expired_count   = 0
    expiring_count  = 0

    for item in items:
        f = item.get("fields", {})

        if f.get("Stage") != "Sensitisation":
            continue

        deadline_str = f.get("SensitisationDeadline", "").strip()
        if not deadline_str:
            continue

        try:
            deadline = date.fromisoformat(deadline_str[:10])
        except ValueError:
            continue

        doc_code = f.get("DocumentCode", item.get("id", ""))
        title    = f.get("Title", "")

        if deadline < today:
            expired_count += 1
            logger.warning(
                f"Sensitisation deadline EXPIRED: '{title}' ({doc_code}) — "
                f"deadline was {deadline_str}. Owner: {f.get('OwnerEntraId', 'unknown')}."
            )
        elif deadline <= warning_threshold:
            expiring_count += 1
            days_left = (deadline - today).days
            logger.info(
                f"Sensitisation deadline imminent: '{title}' ({doc_code}) — "
                f"{days_left} day(s) left (deadline: {deadline_str}). "
                f"Owner: {f.get('OwnerEntraId', 'unknown')}."
            )

    logger.info(
        f"Sensitisation deadline check complete — "
        f"expired: {expired_count}, expiring within 2 days: {expiring_count}"
    )
