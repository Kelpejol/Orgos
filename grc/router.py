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

from auth.validator import CurrentUser, get_current_user
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
    """
    Convert Graph API exceptions to appropriate FastAPI HTTP responses.
    Called in every endpoint's except block.
    """
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
    """
    Returns all documents from the Document Register.
    Only approved, controlled documents are in this register.
    Filter by status (Active / Under Review / Superseded / Withdrawn)
    or department.
    """
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
    doc: schemas.DocumentCreate
) -> schemas.DocumentRead:
    """
    Add a new approved document to the Document Register.
    This endpoint is called by the Document Lifecycle Approval cascade (Tier 2).
    Documents must not be added here directly unless they have been approved.
    """
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
        # Try exact UPN first
        try:
            url  = f"{settings.graph_base_url}/users/{email}"
            data = await _request("GET", url, context=f"Resolve user {email}")
        except Exception:
            # Fall back to $filter search by mail or UPN
            url    = f"{settings.graph_base_url}/users"
            params = {"$filter": f"mail eq '{email}' or userPrincipalName eq '{email}'",
                      "$select": "id,displayName,mail,userPrincipalName,jobTitle"}
            resp   = await _request("GET", url, params=params, context=f"Search user {email}")
            results = resp.get("value", [])
            if not results:
                raise HTTPException(status_code=404,
                    detail=f"No Microsoft 365 account found for '{email}'.")
            data = results[0]

        return {
            "oid":          data.get("id", ""),
            "display_name": data.get("displayName", ""),
            "email":        data.get("mail") or data.get("userPrincipalName", ""),
            "job_title":    data.get("jobTitle", ""),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404,
            detail=f"No Microsoft 365 account found for '{email}'.")

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


@router.delete(
    "/documents/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a document (sets status to Withdrawn)",
)
async def delete_document(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """
    Soft-delete only — sets Status = 'Withdrawn'.
    OrgOS never hard-deletes register entries. Audit trail is preserved.
    """
    try:
        await service.soft_delete_document(item_id)
    except Exception as exc:
        _handle_graph_error(exc, f"soft-delete document {item_id}")


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
    summary="Update a role (e.g. reassign current holder)",
)
async def update_role(
    item_id: str,
    role: schemas.RoleUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> schemas.RoleRead:
    """
    Key use case: when a person changes role, update current_holder_id here.
    All ownership across all registers updates automatically via Entra ID resolution.
    """
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
    user: CurrentUser = Depends(get_current_user),
) -> schemas.RoleRead:
    """
    The primary action on the Role Register.
    Assigns a person to a confirmed but unassigned role.
    Only Compliance Lead or OrgOS Admin can perform this action.
    """
    if "Compliance.Lead" not in user.roles and "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance Lead or Admin role required to assign roles",
        )
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
    """Used by the Work Hub to surface unassigned roles as urgent items."""
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
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ObligationRead]:
    """Status (Overdue / Due Soon / Upcoming) is calculated on every read."""
    try:
        return await service.get_obligations(obligation_type=obligation_type)
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


# =============================================================================
#  Contract Register
# =============================================================================

@router.get(
    "/contracts",
    response_model=list[schemas.ContractRead],
    summary="List all contracts",
)
async def list_contracts(
    contract_type: Optional[str] = Query(None, alias="type"),
    user: CurrentUser = Depends(get_current_user),
) -> list[schemas.ContractRead]:
    try:
        return await service.get_contracts(contract_type=contract_type)
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
