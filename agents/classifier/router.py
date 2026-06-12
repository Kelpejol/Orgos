# =============================================================================
# agents/classifier/router.py
# POST /api/v1/agents/classify  — trigger the Classifier manually
# GET  /api/v1/agents/classify/status — last run summary
# =============================================================================

import logging
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth.validator import CurrentUser, require_compliance_lead
from agents.classifier.service import run_classifier
from config import settings
from graph.client import get_list_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Classifier Agent"])

# In-memory last run record — replaced with SharePoint log in production
_last_run: dict = {}


@router.post("/classify")
async def trigger_classifier(
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Trigger the Classifier agent manually.
    Reads all Zone 1 queue items, compares role terms against the Role Register,
    detects near-duplicate controls, and writes Zone 2/3 items to the queue.
    In ongoing operations this fires automatically after each Extractor batch.
    """
    global _last_run

    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin required to run the Classifier.",
        )

    try:
        logger.info(f"Classifier triggered by {user.name} ({user.oid})")
        summary = await run_classifier(triggered_by=user.name)
        _last_run = {
            **summary,
            "triggered_by": user.name,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        return _last_run
    except Exception as exc:
        logger.exception("Classifier failed")
        raise HTTPException(status_code=500, detail=f"Classifier failed: {exc}")


@router.get("/classify/status")
async def classifier_status(
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """Returns the result of the last Classifier run."""
    if not _last_run:
        if settings.is_list_configured(settings.audit_log_list_id):
            try:
                items = await get_list_items(settings.audit_log_list_id, "Audit Log")
                runs = [
                    i for i in items
                    if i.get("fields", {}).get("Action") == "Classifier run"
                ]
                runs.sort(key=lambda i: i.get("createdDateTime", ""), reverse=True)
                if runs:
                    fields = runs[0].get("fields", {})
                    try:
                        summary = json.loads(fields.get("Rationale", "{}"))
                    except Exception:
                        summary = {}
                    return {
                        **summary,
                        "triggered_by": fields.get("ReviewerName", ""),
                        "triggered_at": runs[0].get("createdDateTime", ""),
                    }
            except Exception as exc:
                logger.warning(f"Could not read classifier status from Audit Log: {exc}")
        return {"status": "never_run", "message": "Classifier has not been run yet."}
    return _last_run
