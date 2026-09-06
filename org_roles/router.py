# =============================================================================
# org_roles/router.py — read-only directory of users and their org_roles
# GET /api/v1/org-roles
# org_roles is read live from Entra ID (onPremisesExtensionAttributes.
# extensionAttribute1) — the same attribute the Dragnet ERP writes to on
# every role change. OrgOS never assigns org_roles; this is read-only, and
# restricted to Compliance/OrgOS Admin — it's a directory of who has elevated
# platform access, not general staff information.
# =============================================================================

from fastapi import APIRouter, Depends

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from graph.client import list_all_job_titles, list_users_with_org_roles

router = APIRouter(prefix="/api/v1/org-roles", tags=["Org Roles"])


@router.get("")
async def list_org_roles(
    user: CurrentUser = Depends(require_compliance_lead),
) -> list[dict]:
    return await list_users_with_org_roles()


@router.get("/job-titles")
async def list_job_titles(
    user: CurrentUser = Depends(get_current_user),
) -> list[str]:
    """
    The distinct real Dragnet job titles — the role vocabulary used for control
    ownership. Available to any authenticated user (reviewers assign owners).
    """
    return await list_all_job_titles()
