# =============================================================================
# agents/gap_analyzer/router.py
# POST /api/v1/agents/gap-analysis/run  — trigger gap analysis
# GET  /api/v1/agents/gap-analysis/status — last run summary
# =============================================================================

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth.validator import CurrentUser, get_current_user
from agents.gap_analyzer.service import run_gap_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Gap Analyzer"])

_last_run: dict = {}


@router.post("/gap-analysis/run")
async def trigger_gap_analysis(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Trigger the Gap Analyzer agent.
    Reads confirmed Control Register, Evidence Tracker, and Role Register.
    Compares against ISO 27001, ISO 9001, and NDPA clause requirements.
    Writes gap findings with proposed remediation packages to the Gap Analysis list.
    Per Bobby's amendment: findings include complete remediation packages.
    """
    global _last_run

    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Compliance Lead or OrgOS Admin required to run Gap Analysis.",
        )

    try:
        logger.info(f"Gap Analyzer triggered by {user.name}")
        summary = await run_gap_analysis()
        _last_run = {
            **summary,
            "triggered_by": user.name,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        return _last_run
    except Exception as exc:
        logger.exception("Gap Analyzer failed")
        raise HTTPException(status_code=500, detail=f"Gap Analyzer failed: {exc}")


@router.get("/gap-analysis/status")
async def gap_analysis_status(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not _last_run:
        return {"status": "never_run", "message": "Gap Analyzer has not been run yet."}
    return _last_run