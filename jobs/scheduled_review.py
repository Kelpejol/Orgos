# =============================================================================
# jobs/scheduled_review.py — Scheduled Document Review Check
# Runs daily at 08:00 WAT via APScheduler.
# Scans the Document Register for documents whose NextReviewDate is within
# 30 days, and creates a Document Lifecycle entry (trigger="Scheduled Review")
# if one does not already exist for that document code.
# =============================================================================

import logging
from datetime import date, timedelta

from config import settings
from graph.client import get_list_items, create_list_item

logger = logging.getLogger(__name__)

REVIEW_LEAD_DAYS = 30   # Create lifecycle entry this many days before NextReviewDate


async def check_document_review_dates() -> None:
    """
    Scheduled job: create lifecycle entries for documents approaching their review date.

    Skips documents that:
    - Already have a lifecycle entry with trigger="Scheduled Review" AND stage != "Approved"
    - Have Status = "Withdrawn" or "Superseded"
    - Have no NextReviewDate set
    """
    if not settings.is_list_configured(settings.document_register_list_id):
        logger.debug("Scheduled review: Document Register list not configured — skipping")
        return

    logger.info("Scheduled review: scanning Document Register for upcoming review dates…")

    threshold = date.today() + timedelta(days=REVIEW_LEAD_DAYS)
    today     = date.today()

    try:
        doc_items = await get_list_items(
            settings.document_register_list_id,
            "Document Register",
        )
    except Exception as exc:
        logger.error(f"Scheduled review: failed to read Document Register: {exc}")
        return

    # Build set of document codes already in lifecycle with Scheduled Review trigger
    existing_lifecycle_codes: set[str] = set()
    if settings.is_list_configured(settings.document_lifecycle_list_id):
        try:
            lifecycle_items = await get_list_items(
                settings.document_lifecycle_list_id,
                "Document Lifecycle",
            )
            for li in lifecycle_items:
                lf = li.get("fields", {})
                if (
                    lf.get("Trigger") == "Scheduled Review"
                    and lf.get("Stage") not in ("Approved", None)
                    and lf.get("ApprovalStatus") != "Approved"
                ):
                    code = lf.get("DocumentCode", "").strip()
                    if code:
                        existing_lifecycle_codes.add(code)
        except Exception as exc:
            logger.warning(f"Scheduled review: failed to read lifecycle list: {exc}")

    triggered = 0
    skipped   = 0

    for item in doc_items:
        f = item.get("fields", {})

        # Skip inactive documents
        status = f.get("DocumentStatus", f.get("Status", "")).strip()
        if status in ("Withdrawn", "Superseded"):
            skipped += 1
            continue

        doc_code = f.get("DocumentCode", "").strip()
        if not doc_code:
            skipped += 1
            continue

        review_date_str = f.get("NextReviewDate", "").strip()
        if not review_date_str:
            skipped += 1
            continue

        try:
            review_date = date.fromisoformat(review_date_str[:10])
        except ValueError:
            logger.debug(f"Scheduled review: invalid NextReviewDate '{review_date_str}' for {doc_code}")
            skipped += 1
            continue

        # Only trigger for documents due within the window (not already overdue for more than 30 days)
        if review_date < today - timedelta(days=REVIEW_LEAD_DAYS) or review_date > threshold:
            skipped += 1
            continue

        # Skip if there's already an in-progress lifecycle entry for this document code
        if doc_code in existing_lifecycle_codes:
            logger.debug(f"Scheduled review: {doc_code} already has active lifecycle entry — skipping")
            skipped += 1
            continue

        # Create lifecycle entry
        owner_oid  = f.get("OwnerId", "") or f.get("OwnerEntraId", "")
        owner_name = f.get("Owner", f.get("OwnerDisplayName", ""))

        lc_fields: dict = {
            "Title":        f"Scheduled review — {f.get('Title', doc_code)}",
            "DocumentCode": doc_code,
            "DocumentType": f.get("DocumentType", "Policy"),
            "Department":   f.get("Department", ""),
            "Stage":        "Review",
            "Trigger":      "Scheduled Review",
            "AIGenerated":  False,
            "Revised":      False,
            "Notes":        (
                f"Auto-created by scheduled review job.\n"
                f"Document: {f.get('Title', doc_code)}\n"
                f"Next review date: {review_date_str}\n"
                f"Current version: {f.get('CurrentVersion', f.get('Version', ''))}"
            ),
            "RejectionCount":           0,
            "StakeholderResponseCount": 0,
        }
        if owner_oid:
            lc_fields["OwnerEntraId"] = owner_oid
        if owner_name:
            lc_fields["Owner"] = owner_name
        if f.get("SharePointUrl"):
            lc_fields["SharePointFileUrl"] = f.get("SharePointUrl")
        if settings.is_list_configured(settings.document_lifecycle_list_id):
            linked = f.get("LinkedDocumentRegisterItem", f.get("id", item.get("id", "")))
            if linked:
                lc_fields["LinkedDocumentRegisterItem"] = str(linked)

        try:
            if settings.is_list_configured(settings.document_lifecycle_list_id):
                await create_list_item(
                    settings.document_lifecycle_list_id,
                    "Document Lifecycle",
                    lc_fields,
                )
                triggered += 1
                logger.info(
                    f"Scheduled review: created lifecycle entry for {doc_code} "
                    f"(review due {review_date_str})"
                )
        except Exception as exc:
            logger.error(f"Scheduled review: failed to create lifecycle entry for {doc_code}: {exc}")

    logger.info(
        f"Scheduled review complete — triggered: {triggered}, skipped: {skipped}"
    )
