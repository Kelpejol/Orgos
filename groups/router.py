# =============================================================================
# groups/router.py — OrgOS people groups API
# GET    /api/v1/groups                       list groups (any authenticated user)
# GET    /api/v1/groups/names                 active group names (owner vocabulary)
# POST   /api/v1/groups                       create (Compliance/Admin)
# PATCH  /api/v1/groups/{id}                  rename/edit (Compliance/Admin)
# POST   /api/v1/groups/{id}/members          add members (Compliance/Admin)
# DELETE /api/v1/groups/{id}/members/{oid}    remove a member (Compliance/Admin)
# DELETE /api/v1/groups/{id}                  soft-delete (Compliance/Admin)
#
# Reads are open to any authenticated user (owner pickers need the names/members);
# writes require Compliance or Admin.
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from graph.exceptions import GraphAPIError, GraphNotFoundError
from groups import service
from groups.service import GroupsListNotProvisioned

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/groups", tags=["Groups"])


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GroupsListNotProvisioned):
        raise HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=getattr(exc, "status_code", 502), detail=str(exc))
    logger.exception(f"Groups error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


class Member(BaseModel):
    oid: str
    display_name: Optional[str] = ""
    email: Optional[str] = ""


class CreateGroup(BaseModel):
    name: str
    description: Optional[str] = ""
    category: Optional[str] = ""
    aliases: Optional[list[str]] = None
    members: Optional[list[Member]] = None


class UpdateGroup(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    aliases: Optional[list[str]] = None


class AddMembers(BaseModel):
    members: list[Member]


@router.get("")
async def list_groups(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    try:
        return await service.list_groups()
    except Exception as exc:
        _handle(exc, "list groups")


@router.get("/names")
async def list_group_names(user: CurrentUser = Depends(get_current_user)) -> list[str]:
    try:
        return await service.group_names()
    except Exception as exc:
        _handle(exc, "list group names")


@router.get("/{group_id}")
async def get_group(group_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        return await service.get_group(group_id)
    except Exception as exc:
        _handle(exc, f"get group {group_id}")


@router.post("", status_code=201)
async def create_group(
    body: CreateGroup,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    try:
        return await service.create_group(
            name=body.name,
            description=body.description or "",
            category=body.category or "",
            members=[m.model_dump() for m in (body.members or [])],
            creator_oid=user.oid,
            creator_name=user.name or "",
            aliases=body.aliases,
        )
    except Exception as exc:
        _handle(exc, "create group")


@router.patch("/{group_id}")
async def update_group(
    group_id: str,
    body: UpdateGroup,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    try:
        return await service.update_group(group_id, body.description, body.category, body.name, body.aliases)
    except Exception as exc:
        _handle(exc, f"update group {group_id}")


@router.post("/{group_id}/members")
async def add_members(
    group_id: str,
    body: AddMembers,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    try:
        return await service.add_members(group_id, [m.model_dump() for m in body.members])
    except Exception as exc:
        _handle(exc, f"add members to {group_id}")


@router.delete("/{group_id}/members/{oid}")
async def remove_member(
    group_id: str,
    oid: str,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    try:
        return await service.remove_member(group_id, oid)
    except Exception as exc:
        _handle(exc, f"remove member {oid} from {group_id}")


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    user: CurrentUser = Depends(require_compliance_lead),
) -> None:
    try:
        await service.soft_delete_group(group_id)
    except Exception as exc:
        _handle(exc, f"delete group {group_id}")
