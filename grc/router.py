# =============================================================================
# grc/router.py — GRC module FastAPI router
# All Tier 1 endpoints: Document Register, Role Register,
# Compliance Calendar, Contract Register.
# All routes require a valid Entra ID bearer token.
# Depends on: grc/service.py, grc/schemas.py, auth/validator.py
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.validator import CurrentUser, get_current_user, require_admin
from graph.exceptions import (
    GraphAPIError,
    GraphNotFoundError,
    SharePointListNotConfiguredError,
)
from grc import schemas
from grc import service
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/grc", tags=["GRC — Tier 1"])


def _handle_graph_error(exc: Exception, operation: str) -> None:
    """Convert Graph API exceptions to appropriate FastAPI HTTP responses."""
    if isinstance(exc, SharePointListNotConfiguredError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    elif isinstance(exc, GraphNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    elif isinstance(exc, GraphAPIError):
        logger.error(f"Graph API error during {operation}: {exc}")
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        )
    else:
        logger.exception(f"Unexpected error during {operation}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {operation}",
        )


# =============================================================================
#  Document Register
# =============================================================================

@router.get(
    "/documents",
    response_model=list[schemas.DocumentRead],
    summary="List all approved controlled documents",
)
async def list_documents(
    status_filter: Optional[str] = Query(None, alias="status"),
    department: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.DocumentRead]:
    try:
        return await service.get_documents(status=status_filter, department=department)
    except Exception as exc:
        _handle_graph_error(exc, "list documents")


@router.post(
    "/documents",
    response_model=schemas.DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register an approved document",
)
async def create_document(
    doc: schemas.DocumentCreate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.DocumentRead:
    try:
        return await service.create_document(doc)
    except Exception as exc:
        _handle_graph_error(exc, "create document")


@router.get("/users/resolve")
async def resolve_user_by_email(
    email: str = Query(...),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        from graph.client import _request
        try:
            url  = f"{settings.graph_base_url}/users/{email}"
            data = await _request("GET", url, context=f"Resolve user {email}")
        except Exception:
            url    = f"{settings.graph_base_url}/users"
            params = {
                "$filter": f"mail eq '{email}' or userPrincipalName eq '{email}'",
                "$select": "id,displayName,mail,userPrincipalName,jobTitle",
            }
            resp    = await _request("GET", url, params=params, context=f"Search user {email}")
            results = resp.get("value", [])
            if not results:
                raise HTTPException(
                    status_code=404,
                    detail=f"No Microsoft 365 account found for '{email}'.",
                )
            data = results[0]

        return {
            "oid":          data.get("id", ""),
            "display_name": data.get("displayName", ""),
            "email":        data.get("mail") or data.get("userPrincipalName", ""),
            "job_title":    data.get("jobTitle", ""),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"No Microsoft 365 account found for '{email}'.",
        )


@router.get("/users/search")
async def search_users_endpoint(
    q: str = Query(..., min_length=2),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """Prefix search across displayName and mail. Returns up to 8 matches."""
    safe_q = q.replace("'", "").strip()
    if not safe_q:
        return []
    try:
        from graph.client import _request
        params = {
            "$filter": f"startswith(displayName,'{safe_q}') or startswith(mail,'{safe_q}')",
            "$select": "id,displayName,mail,userPrincipalName,jobTitle",
            "$top": "8",
        }
        resp = await _request(
            "GET",
            f"{settings.graph_base_url}/users",
            params=params,
            context="search users",
        )
        return [
            {
                "oid":          r.get("id", ""),
                "display_name": r.get("displayName", ""),
                "email":        r.get("mail") or r.get("userPrincipalName", ""),
                "job_title":    r.get("jobTitle", ""),
            }
            for r in resp.get("value", [])
        ]
    except Exception:
        return []


@router.get(
    "/documents/{item_id}",
    response_model=schemas.DocumentRead,
    summary="Get a single document",
)
async def get_document(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.DocumentRead:
    try:
        return await service.get_document(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"get document {item_id}")


@router.patch(
    "/documents/{item_id}",
    response_model=schemas.DocumentRead,
    summary="Update a document entry",
)
async def update_document(
    item_id: str,
    doc: schemas.DocumentUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.DocumentRead:
    try:
        return await service.update_document(item_id, doc)
    except Exception as exc:
        _handle_graph_error(exc, f"update document {item_id}")


@router.get(
    "/documents/{item_id}/withdrawal-impact",
    summary="Preview full dependency chain before withdrawing a document",
)
async def get_withdrawal_impact(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Returns every item that will be affected by withdrawing this document:
    open queue items, active controls, evidence items, lifecycle entries,
    compliance obligations, and which Standards Map clauses will lose coverage.
    Call this before POST /withdraw to show the reviewer the full impact.
    """
    try:
        return await service.get_withdrawal_impact(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"withdrawal impact {item_id}")


@router.post(
    "/documents/{item_id}/withdraw",
    summary="Withdraw a document with full dependency cascade",
)
async def withdraw_document(
    item_id: str,
    body: schemas.DocumentWithdraw,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Withdraws the document and cascades to all dependent records:
    - Cancels open AI Review Queue items from this document (with provenance)
    - Flags sourced controls to Under Review (with provenance)
    - Flags linked pending/submitted evidence items
    - Cancels in-progress Document Lifecycle entries
    - Re-opens Gap Analysis items whose lifecycle was cancelled
    - Notes Compliance Calendar obligations referencing this document
    - Auto-creates Critical gap findings for Standards Map clauses that lose all coverage

    Requires Compliance Lead or OrgOS Admin role.
    Rationale must be at least 10 characters.
    If withdrawal_reason is Superseded, replaced_by_code must reference an existing document.
    """
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance Lead or OrgOS Admin role required to withdraw documents.",
        )
    try:
        return await service.withdraw_document(
            item_id=item_id,
            withdrawal_reason=body.withdrawal_reason.value,
            rationale=body.rationale,
            replaced_by_code=body.replaced_by_code,
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        _handle_graph_error(exc, f"withdraw document {item_id}")


@router.delete(
    "/documents/{item_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    summary="Deprecated — use POST /documents/{id}/withdraw",
    include_in_schema=False,
)
async def delete_document_deprecated(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=(
            "Direct deletion is not permitted. "
            "Use POST /api/v1/grc/documents/{id}/withdraw with a withdrawal reason and rationale."
        ),
    )


# =============================================================================
#  Role Register
# =============================================================================

@router.get(
    "/roles",
    response_model=list[schemas.RoleRead],
    summary="List all organisational roles",
)
async def list_roles(
    department: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.RoleRead]:
    try:
        return await service.get_roles(department=department)
    except Exception as exc:
        _handle_graph_error(exc, "list roles")


@router.post(
    "/roles",
    response_model=schemas.RoleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new role mapping",
)
async def create_role(
    role: schemas.RoleCreate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.RoleRead:
    try:
        return await service.create_role(role)
    except Exception as exc:
        _handle_graph_error(exc, "create role")


@router.patch(
    "/roles/{item_id}",
    response_model=schemas.RoleRead,
    summary="Update a role",
)
async def update_role(
    item_id: str,
    role: schemas.RoleUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.RoleRead:
    try:
        return await service.update_role(item_id, role)
    except Exception as exc:
        _handle_graph_error(exc, f"update role {item_id}")


@router.patch(
    "/roles/{item_id}/assign",
    response_model=schemas.RoleRead,
    summary="Assign a person to an unassigned role",
)
async def assign_role(
    item_id: str,
    assignment: schemas.RoleAssign,
    user: CurrentUser = Depends(require_admin),
) -> schemas.RoleRead:
    try:
        return await service.assign_role_holder(item_id, assignment.current_holder_id)
    except Exception as exc:
        _handle_graph_error(exc, f"assign role {item_id}")


@router.get(
    "/roles/unassigned",
    response_model=list[schemas.RoleRead],
    summary="Get all roles with no current holder",
)
async def list_unassigned_roles(
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.RoleRead]:
    try:
        return await service.get_unassigned_roles()
    except Exception as exc:
        _handle_graph_error(exc, "list unassigned roles")


@router.get(
    "/roles/{item_id}",
    response_model=schemas.RoleRead,
    summary="Get a single role",
)
async def get_role(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.RoleRead:
    try:
        return await service.get_role(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"get role {item_id}")


# =============================================================================
#  Compliance Calendar
# =============================================================================

@router.get(
    "/compliance",
    response_model=list[schemas.ObligationRead],
    summary="List all compliance obligations",
)
async def list_obligations(
    obligation_type: Optional[str] = Query(None, alias="type"),
    authority:       Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ObligationRead]:
    """Status (Overdue / Due Soon / Upcoming / Completed) is calculated on every read."""
    try:
        return await service.get_obligations(
            obligation_type=obligation_type,
            authority=authority,
        )
    except Exception as exc:
        _handle_graph_error(exc, "list obligations")


@router.get(
    "/compliance/overdue",
    response_model=list[schemas.ObligationRead],
    summary="Get overdue obligations",
)
async def list_overdue_obligations(
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ObligationRead]:
    try:
        return await service.get_overdue_obligations()
    except Exception as exc:
        _handle_graph_error(exc, "list overdue obligations")


@router.get(
    "/compliance/due-soon",
    response_model=list[schemas.ObligationRead],
    summary="Get obligations due within 30 days",
)
async def list_due_soon_obligations(
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ObligationRead]:
    try:
        return await service.get_due_soon_obligations()
    except Exception as exc:
        _handle_graph_error(exc, "list due-soon obligations")


@router.get(
    "/compliance/{item_id}",
    response_model=schemas.ObligationRead,
    summary="Get a single obligation",
)
async def get_obligation(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ObligationRead:
    try:
        return await service.get_obligation(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"get obligation {item_id}")


@router.post(
    "/compliance",
    response_model=schemas.ObligationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a compliance obligation",
)
async def create_obligation(
    obligation: schemas.ObligationCreate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ObligationRead:
    try:
        return await service.create_obligation(obligation)
    except Exception as exc:
        _handle_graph_error(exc, "create obligation")


@router.patch(
    "/compliance/{item_id}",
    response_model=schemas.ObligationRead,
    summary="Update a compliance obligation",
)
async def update_obligation(
    item_id: str,
    obligation: schemas.ObligationUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ObligationRead:
    try:
        return await service.update_obligation(item_id, obligation)
    except Exception as exc:
        _handle_graph_error(exc, f"update obligation {item_id}")


@router.patch(
    "/compliance/{item_id}/complete",
    response_model=schemas.ObligationRead,
    summary="Mark an obligation as completed; rolls recurrence forward",
)
async def complete_obligation(
    item_id: str,
    body: schemas.CompleteObligation,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ObligationRead:
    """
    For Once obligations: stamps CompletedDate — status becomes Completed.
    For recurring obligations: rolls the DueDate forward one period and
    records the completion for audit history. The obligation re-enters
    the active calendar cycle with the new due date.
    """
    try:
        return await service.complete_obligation(
            item_id,
            user_oid=user.oid,
            user_name=user.name,
            body=body,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _handle_graph_error(exc, f"complete obligation {item_id}")


@router.post(
    "/compliance/{item_id}/escalate",
    summary="Escalate an overdue obligation to Gap Analysis",
)
async def escalate_obligation(
    item_id: str,
    body: schemas.EscalateObligation,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Creates a Gap Analysis item (category = Obligation gap) and links the
    obligation to it. Idempotent — repeated calls return the existing gap ID.
    Requires Compliance Lead or OrgOS Admin.
    """
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance Lead or Admin role required to escalate obligations",
        )
    try:
        return await service.escalate_obligation(
            item_id,
            user_oid=user.oid,
            user_name=user.name,
            escalation_notes=body.escalation_notes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _handle_graph_error(exc, f"escalate obligation {item_id}")


@router.delete(
    "/compliance/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a compliance obligation (sets status to Withdrawn)",
)
async def delete_obligation(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    try:
        await service.soft_delete_obligation(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"soft-delete obligation {item_id}")


# =============================================================================
#  Contract Register
# =============================================================================

@router.get(
    "/contracts",
    response_model=list[schemas.ContractRead],
    summary="List all contracts",
)
async def list_contracts(
    contract_type:    Optional[str] = Query(None, alias="type"),
    lifecycle_status: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ContractRead]:
    try:
        return await service.get_contracts(
            contract_type=contract_type,
            lifecycle_status=lifecycle_status,
        )
    except Exception as exc:
        _handle_graph_error(exc, "list contracts")


@router.get(
    "/contracts/expiring",
    response_model=list[schemas.ContractRead],
    summary="Get contracts expiring within 60 days",
)
async def list_expiring_contracts(
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ContractRead]:
    try:
        return await service.get_expiring_contracts()
    except Exception as exc:
        _handle_graph_error(exc, "list expiring contracts")


@router.get(
    "/contracts/{item_id}",
    response_model=schemas.ContractRead,
    summary="Get a single contract",
)
async def get_contract(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ContractRead:
    try:
        return await service.get_contract(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"get contract {item_id}")


@router.post(
    "/contracts",
    response_model=schemas.ContractRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a contract record",
)
async def create_contract(
    contract: schemas.ContractCreate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ContractRead:
    try:
        return await service.create_contract(contract)
    except Exception as exc:
        _handle_graph_error(exc, "create contract")


@router.patch(
    "/contracts/{item_id}",
    response_model=schemas.ContractRead,
    summary="Update a contract record",
)
async def update_contract(
    item_id: str,
    contract: schemas.ContractUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ContractRead:
    try:
        return await service.update_contract(item_id, contract)
    except Exception as exc:
        _handle_graph_error(exc, f"update contract {item_id}")


@router.patch(
    "/contracts/{item_id}/lifecycle",
    response_model=schemas.ContractRead,
    summary="Update contract lifecycle status (Terminate, Under Review, Supersede)",
)
async def update_contract_lifecycle(
    item_id: str,
    lifecycle_status: schemas.ContractLifecycleStatus,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ContractRead:
    """
    Dedicated endpoint for lifecycle transitions. Requires Compliance Lead.
    lifecycle_status body is passed as a JSON string: "Terminated"
    """
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance Lead or Admin role required to change contract lifecycle status",
        )
    try:
        update = schemas.ContractUpdate(lifecycle_status=lifecycle_status)
        return await service.update_contract(item_id, update)
    except HTTPException:
        raise
    except Exception as exc:
        _handle_graph_error(exc, f"update lifecycle {item_id}")


@router.post(
    "/contracts/{item_id}/add-obligation",
    response_model=schemas.ObligationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Compliance Calendar obligation from this contract",
)
async def add_contract_obligation(
    item_id: str,
    body: schemas.ContractAddObligation,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.ObligationRead:
    """
    Creates a Compliance Calendar entry linked to this contract.
    The LinkedContractId field on the obligation traces back to this contract.
    """
    try:
        return await service.add_contract_obligation(item_id, body)
    except Exception as exc:
        _handle_graph_error(exc, f"add contract obligation {item_id}")


@router.delete(
    "/contracts/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a contract (sets status to Withdrawn)",
)
async def delete_contract(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    try:
        await service.soft_delete_contract(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"soft-delete contract {item_id}")
