# =============================================================================
# records_catalogue/router.py — Records Catalogue API (read-only)
# GET /api/v1/records-catalogue               — records, filterable
# GET /api/v1/records-catalogue/{record_id}   — one record with its disposition gate
#
# The Catalogue is issued by Records Governance and loaded with
# scripts/import_records_catalogue.py; OrgOS does not edit it.
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.validator import CurrentUser, get_current_user
from graph.exceptions import GraphAPIError
from records_catalogue import service
from records_catalogue.model import RecordEntry, normalise_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/records-catalogue", tags=["Records Catalogue"])


def _summary(e: RecordEntry) -> dict:
    allowed, _ = e.disposition_gate()
    return {
        "record_id": e.record_id,
        "name": e.name,
        "record_type": e.record_type,
        "admission_status": e.admission_status,
        "custodian": e.custodian,
        "system_id": e.system_id,
        "location": e.location,
        "retention_rule": e.retention_rule,
        "retention_validation": e.retention_validation,
        "record_validation_status": e.record_validation_status,
        "automated_disposition_allowed": allowed,
    }


def _detail(e: RecordEntry) -> dict:
    allowed, reason = e.disposition_gate()
    return {**e.to_dict(), "system_id": e.system_id, "withdrawn": e.withdrawn,
            "automated_disposition_allowed": allowed, "disposition_gate_reason": reason}


async def _load():
    try:
        return await service.load()
    except GraphAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("")
async def list_records(
    q: Optional[str] = Query(None, description="Record ID, name or alias contains"),
    record_type: Optional[str] = None,
    system_id: Optional[str] = Query(None, description="e.g. S01"),
    include_withdrawn: bool = False,
    user: CurrentUser = Depends(get_current_user),
):
    entries = list((await _load()).values())
    if not include_withdrawn:
        entries = [e for e in entries if not e.withdrawn]
    if record_type:
        entries = [e for e in entries if e.record_type.lower() == record_type.lower()]
    if system_id:
        entries = [e for e in entries if e.system_id == system_id.upper()]
    if q:
        needle = normalise_name(q)
        entries = [e for e in entries
                   if q.strip().upper() in e.record_id
                   or needle in normalise_name(" ".join([e.name, *e.aliases]))]
    return [_summary(e) for e in sorted(entries, key=lambda e: e.record_id)]


@router.get("/{record_id}")
async def get_record(record_id: str, user: CurrentUser = Depends(get_current_user)):
    entry = (await _load()).get(record_id.strip().upper())
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{record_id} is not in the Records Catalogue.")
    return _detail(entry)
