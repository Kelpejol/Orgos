# =============================================================================
# agents/gap_analyzer/router.py
# POST /api/v1/agents/gap-analysis/run  — trigger gap analysis
# GET  /api/v1/agents/gap-analysis/status — last run summary
# =============================================================================

import logging
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth.validator import CurrentUser, require_compliance_lead
from agents.gap_analyzer.service import run_gap_analysis
from config import settings
from graph.client import get_list_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Gap Analyzer"])

_last_run: dict = {}


@router.post("/gap-analysis/run")
async def trigger_gap_analysis(
    user: CurrentUser = Depends(require_compliance_lead),
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
        summary = await run_gap_analysis(triggered_by=user.name)
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
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    if not _last_run:
        if settings.is_list_configured(settings.audit_log_list_id):
            try:
                items = await get_list_items(settings.audit_log_list_id, "Audit Log")
                runs = [
                    i for i in items
                    if i.get("fields", {}).get("Action") == "Gap Analyzer run"
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
                logger.warning(f"Could not read Gap Analyzer status from Audit Log: {exc}")
        return {"status": "never_run", "message": "Gap Analyzer has not been run yet."}
    return _last_run
