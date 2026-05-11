# =============================================================================
# agents/classifier/router.py
# POST /api/v1/agents/classify  — trigger the Classifier manually
# GET  /api/v1/agents/classify/status — last run summary
# =============================================================================

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth.validator import CurrentUser, get_current_user
from agents.classifier.service import run_classifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Classifier Agent"])

# In-memory last run record — replaced with SharePoint log in production
_last_run: dict = {}


@router.post("/classify")
async def trigger_classifier(
    user: CurrentUser = Depends(get_current_user),
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
        summary = await run_classifier()
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
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Returns the result of the last Classifier run."""
    if not _last_run:
        return {"status": "never_run", "message": "Classifier has not been run yet."}
    return _last_run