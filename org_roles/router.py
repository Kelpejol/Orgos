# =============================================================================
# org_roles/router.py — read-only directory of users and their org_roles
# GET /api/v1/org-roles
# org_roles is read live from Entra ID (onPremisesExtensionAttributes.
# extensionAttribute1) — the same attribute the Dragnet ERP writes to on
# every role change. OrgOS never assigns org_roles; this is read-only, and
# restricted to Compliance/OrgOS Admin — it's a directory of who has elevated
# platform access, not general staff information.
# =============================================================================

import logging

from fastapi import APIRouter, Depends

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from graph.client import list_all_job_titles, list_users_with_org_roles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/org-roles", tags=["Org Roles"])


@router.get("")
async def list_org_roles(
    all_staff: bool = False,
    user: CurrentUser = Depends(require_compliance_lead),
) -> list[dict]:
    """
    By default: everyone the ERP has granted an org_role.
    With ?all_staff=true: every enabled internal member (a full staff
    directory), org_roles simply empty for most of them.
    """
    return await list_users_with_org_roles(include_all_staff=all_staff)


@router.get("/ownership-summary")
async def ownership_summary(
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    How many controls and evidence items each role owns, keyed by the
    lower-cased role name. Lets the UI show ownership load per job title /
    group — and surface roles that own nothing before the Gap Analyzer does.
    """
    from config import settings
    from graph.client import get_list_items

    def _key(v: str) -> str:
        return " ".join((v or "").split()).strip().lower()

    counts: dict[str, dict] = {}

    async def _tally(list_id: str, list_name: str, bucket: str) -> None:
        if not settings.is_list_configured(list_id):
            return
        try:
            for i in await get_list_items(list_id, list_name):
                role = (i.get("fields", {}) or {}).get("OwnerRole", "")
                k = _key(role)
                if not k:
                    continue
                entry = counts.setdefault(k, {"label": role, "controls": 0, "evidence": 0})
                entry[bucket] += 1
        except Exception as exc:
            logger.warning(f"Ownership summary: could not read {list_name}: {exc}")

    await _tally(settings.control_register_list_id, "Control Register", "controls")
    await _tally(settings.evidence_tracker_list_id, "Evidence Tracker", "evidence")
    return counts


@router.get("/job-titles")
async def list_job_titles(
    user: CurrentUser = Depends(get_current_user),
) -> list[str]:
    """
    The distinct real Dragnet job titles — the role vocabulary used for control
    ownership. Available to any authenticated user (reviewers assign owners).
    """
    return await list_all_job_titles()
