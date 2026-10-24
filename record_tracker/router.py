# =============================================================================
# record_tracker/router.py
# GET  /api/v1/records              — list all record items
# GET  /api/v1/records/{id}         — get single item
# PATCH /api/v1/records/{id}/submit — owner submits a record with link
# PATCH /api/v1/records/{id}/verify — compliance verifies submission
#
# NOTE — naming: this module was renamed from "Evidence Tracker" to "Record
# Tracker" (OrgOS's own feature/API naming only). The underlying SharePoint
# list is still literally named "Evidence Tracker" with columns like
# EvidenceDescription/EvidenceType/EvidenceLink — those are NOT renamed here
# (OrgOS cannot rename SharePoint columns). The 16-code "Evidence Type"
# taxonomy (DRG-QI-REF-EVTX-01-26) also keeps its name throughout — it is a
# separate, formally documented standard, distinct from this tracker feature.
# =============================================================================

import logging
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from config import settings
from graph.auth import get_graph_access_token
from graph.client import (
    create_list_item,
    get_list_item,
    get_list_items,
    update_list_item,
)
from graph.exceptions import GraphAPIError, GraphNotFoundError
from graph.client import resolve_user
from evidence.obligations import ATTENTION, assess, may_upload, system_id_of

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Record Tracker"])

# The real SharePoint list name — unchanged (see module note above).
_LIST_NAME = "Evidence Tracker"


def _list_id() -> str:
    # Unchanged config attribute — renaming it would require a matching
    # production .env update; not worth the deploy-coordination risk for an
    # internal-only name. See module note above.
    return settings.evidence_tracker_list_id


def _handle(exc: Exception, ctx: str):
    if isinstance(exc, GraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    elif isinstance(exc, GraphAPIError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    logger.exception(f"Error: {ctx}")
    raise HTTPException(status_code=500, detail=f"Error: {ctx}")


def _sp_to_record(item: dict) -> dict:
    f = item.get("fields", {})
    return {
        "id":                  str(item["id"]),
        "Title":               f.get("Title", ""),
        "RecordDescription":   f.get("EvidenceDescription", ""),
        "EvidenceType":        f.get("EvidenceType", ""),
        "SourceSystem":        f.get("SourceSystem", ""),
        "RecordFormat":        f.get("EvidenceFormat", ""),
        "Frequency":           f.get("Frequency", ""),
        "CollectionMethod":    f.get("CollectionMethod", ""),
        "OwnerRole":           f.get("OwnerRole", ""),
        "OwnerEntraId":        f.get("OwnerEntraId", ""),
        "ValidationCriteria":  f.get("ValidationCriteria", ""),
        "RecordLink":          f.get("EvidenceLink", ""),
        "RecordUrl":           f.get("EvidenceLink", ""),
        "recordUrl":           f.get("EvidenceLink", ""),
        "Status":              f.get("Status", "Pending"),
        "LinkedControlId":     f.get("LinkedControlId", ""),
        "NextDue":             f.get("NextDue", ""),
        "LastCollected":       f.get("LastCollected", ""),
        "SubmissionNotes":     f.get("SubmissionNotes", ""),
        "RejectionNote":       f.get("RejectionNote", ""),
        "VerifiedBy":          f.get("VerifiedBy", ""),
        "created":             item.get("createdDateTime", ""),
        "modified":            item.get("lastModifiedDateTime", ""),
        **_obligation_view(f),
    }


def _obligation_view(f: dict) -> dict:
    """
    An evidence obligation (one control × one record). Its state is assessed
    live from the schedule and the last accepted record, never read stale.
    Older one-per-control rows have no ObligationKey and no assessment.
    """
    if not f.get("ObligationKey"):
        return {"IsObligation": False}
    a = assess(f)
    location = f.get("SourceSystem", "")
    return {
        "IsObligation":            True,
        "ObligationKey":           f["ObligationKey"],
        "RecordId":                f.get("RecordId", ""),
        "OperatingTrigger":        f.get("OperatingTrigger", ""),
        "Custodian":               f.get("Custodian", ""),
        "Location":                location,
        "MayUpload":               may_upload(system_id_of(location)),
        "CheckFrequencyDays":      int(float(f.get("CheckFrequencyDays") or 0)),
        "FreshnessDays":           int(float(f.get("FreshnessDays") or 0)),
        "SuggestedFrequencyDays":  int(float(f.get("SuggestedFrequencyDays") or 0)),
        "SuggestedFrequencyBasis": f.get("SuggestedFrequencyBasis", ""),
        "ScheduledFrom":           str(f.get("ScheduledFrom") or "")[:10],
        "LastRecordDate":          str(f.get("LastRecordDate") or "")[:10],
        "PendingRecordDate":       str(f.get("PendingRecordDate") or "")[:10],
        "State":                   a.state,
        "StateDetail":             a.detail,
        "NextDue":                 a.next_due.isoformat() if a.next_due else "",
    }


# =============================================================================
#  Endpoints
# =============================================================================

@router.get("/api/v1/records")
async def list_records(
    owner_oid:  Optional[str] = None,
    status:     Optional[str] = None,
    control_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """
    List record items. Filterable by owner OID, status, or linked control.
    """
    try:
        items = await get_list_items(_list_id(), _LIST_NAME)
        records = [_sp_to_record(i) for i in items]

        # Ownership is the Control owner's role for obligations; the shared
        # resolver still supports legacy job-title rows. OwnerEntraId is
        # never populated. Resolve once and stamp each item so the UI can gate
        # actions without re-deriving membership client-side.
        try:
            from ownership.resolver import get_ownership_index
            ownership = await get_ownership_index()
            for r in records:
                res = ownership.resolve(r["OwnerRole"])
                r["OwnedByMe"]    = ownership.owns(r["OwnerRole"], user.oid)
                r["OwnerKind"]    = res["kind"]           # group | job_title | unresolved
                r["OwnerPeople"]  = res["people"]
                r["OwnerResolved"] = res["resolved"]
                r["OwnerCanonical"] = res["canonical"]
                r["OwnerViaAlias"]  = res["via_alias"]
        except Exception as exc:
            logger.warning(f"Could not resolve record ownership: {exc}")
            for r in records:
                r.setdefault("OwnedByMe", False)
                r.setdefault("OwnerKind", "unresolved")
                r.setdefault("OwnerPeople", [])
                r.setdefault("OwnerResolved", False)

        if owner_oid:
            # Filter by who actually holds the owning role.
            records = [r for r in records
                       if any((p.get("oid") or "") == owner_oid for p in r.get("OwnerPeople", []))]
        if status:
            records = [r for r in records if r["Status"] == status]
        if control_id:
            records = [r for r in records if r["LinkedControlId"] == control_id]

        # Sort: overdue and due soon first
        status_order = {
            "Overdue": 0, "Due Soon": 1, "Submitted": 2,
            "Pending": 3, "Rejected": 4, "Accepted": 5,
        }
        state_order = {"Missing": 0, "Late": 1, "Rejected": 2, "Stale": 3, "Due soon": 4,
                       "Submitted": 5, "Awaiting first record": 6, "Unscheduled": 7, "Current": 8}
        records.sort(key=lambda r: (state_order.get(r.get("State"), 9) if r.get("IsObligation")
                                    else status_order.get(r["Status"], 9)))
        return records
    except Exception as exc:
        _handle(exc, "list records")


@router.get("/api/v1/records/{item_id}")
async def get_record(
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        item = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(item)
    except Exception as exc:
        _handle(exc, f"get record {item_id}")


class SubmitRecord(BaseModel):
    record_link:      str   # Mandatory — link to the record where it lives
    submission_notes: Optional[str] = None
    record_date:      Optional[str] = None   # when the record was produced; required for obligations


class ScheduleObligation(BaseModel):
    check_frequency_days: int                # how often the record must be confirmed
    freshness_days:       Optional[int] = None


def _record_date(value: Optional[str]) -> str:
    """The date the submitted record was produced — required, not in the future."""
    try:
        d = date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail=(
            "record_date is required: the date the record itself was produced "
            "(e.g. the review meeting's date), not today's date by default."))
    if d > date.today():
        raise HTTPException(status_code=422, detail="record_date cannot be in the future.")
    return d.isoformat()


def _may_submit(fields: dict) -> None:
    """
    An obligation recurs: an Accepted record is this period's proof, and the
    next period's record is submitted over it. Older one-off rows must be
    reopened by Compliance first.
    """
    status = fields.get("Status") or ""
    if status == "Withdrawn":
        raise HTTPException(status_code=409, detail="This obligation is withdrawn: the control no longer names this record.")
    if status == "Accepted" and not fields.get("ObligationKey"):
        raise HTTPException(
            status_code=409,
            detail="This record is already Accepted. Someone with the Compliance role "
                   "must reopen it (reject) before a new record can be submitted.",
        )


class VerifyRecord(BaseModel):
    accepted:      bool
    rejection_note: Optional[str] = None  # Required if accepted=False


def _safe_filename(filename: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in (" ", ".", "-", "_") else "_" for c in filename)
    return cleaned.strip(" .") or "record-file"


async def _upload_record_to_sharepoint(
    item_id: str,
    filename: str,
    file_bytes: bytes,
) -> str:
    """
    Upload a record file to SharePoint and return the source webUrl.
    Path: /EVID-{item_id}-{filename} — kept as-is, matches the already-
    uploaded files' naming convention on the live drive.
    """
    token = await get_graph_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    upload_path = f"Evidence/EVID-{item_id}-{_safe_filename(filename)}"
    upload_url = (
        f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        f"/drive/root:/{upload_path}:/content"
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.put(upload_url, headers=headers, content=file_bytes)
        resp.raise_for_status()

    web_url = resp.json().get("webUrl", "")
    logger.info(f"Uploaded record '{filename}' for item {item_id}: {web_url}")
    return web_url


@router.patch("/api/v1/records/{item_id}/submit")
async def submit_record(
    item_id: str,
    body: SubmitRecord,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner submits a collected record with a mandatory link to the artefact.
    Sets status to Submitted for Compliance team verification.
    """
    if not body.record_link.strip():
        raise HTTPException(
            status_code=422,
            detail="record_link is mandatory. Paste the URL to the artefact in SharePoint, Intune, GitHub, or the relevant source system.",
        )

    try:
        current_fields = (await get_list_item(_list_id(), _LIST_NAME, item_id)).get("fields", {}) or {}
        _may_submit(current_fields)

        fields: dict = {
            "EvidenceLink":   body.record_link.strip(),
            "Status":         "Submitted",
            "LastCollected":  date.today().isoformat(),
            "RejectionNote":  "",  # Clear any previous rejection
        }
        if current_fields.get("ObligationKey"):
            fields["PendingRecordDate"] = _record_date(body.record_date)
        if body.submission_notes:
            fields["SubmissionNotes"] = body.submission_notes

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"submit record {item_id}")


@router.post("/api/v1/records/{item_id}/upload")
async def upload_record(
    item_id: str,
    file: UploadFile = File(...),
    submission_notes: Optional[str] = Form(None),
    record_date: Optional[str] = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Owner uploads a collected record to SharePoint.
    The returned SharePoint webUrl is stored as the record's source URL.
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Record file is required.")

    filename = file.filename or f"record_{item_id}"

    try:
        current_fields = (await get_list_item(_list_id(), _LIST_NAME, item_id)).get("fields", {}) or {}
    except Exception as exc:
        _handle(exc, f"get record {item_id}")
    pending_date = None
    if current_fields.get("ObligationKey"):
        location = current_fields.get("SourceSystem", "")
        if not may_upload(system_id_of(location)):
            raise HTTPException(status_code=409, detail=(
                f"This record's authoritative home is {location or 'outside OrgOS'}. Link to it "
                "there instead of uploading a copy — OrgOS references records at source."))
        pending_date = _record_date(record_date)
    _may_submit(current_fields)

    try:
        record_url = await _upload_record_to_sharepoint(item_id, filename, file_bytes)
    except Exception as exc:
        logger.exception(f"SharePoint record upload failed for {item_id}")
        raise HTTPException(status_code=503, detail=f"SharePoint upload failed: {exc}")

    try:
        fields: dict = {
            "EvidenceLink":   record_url,
            "Status":         "Submitted",
            "LastCollected":  date.today().isoformat(),
            "RejectionNote":  "",
        }
        if pending_date:
            fields["PendingRecordDate"] = pending_date
        if submission_notes:
            fields["SubmissionNotes"] = submission_notes

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"save uploaded record {item_id}")


@router.patch("/api/v1/records/{item_id}/verify")
async def verify_record(
    item_id: str,
    body: VerifyRecord,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Compliance team verifies a submitted record item.
    Accept → status becomes Accepted.
    Reject → status returns to Pending with rejection note visible to owner.
    """
    if not body.accepted and not body.rejection_note:
        raise HTTPException(
            status_code=422,
            detail="rejection_note is required when rejecting a record.",
        )

    try:
        current = await get_list_item(_list_id(), _LIST_NAME, item_id)
        cur_status = (current.get("fields", {}) or {}).get("Status", "") or ""
        if cur_status != "Submitted":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Only submitted records can be verified (current status: "
                    f"'{cur_status or 'Pending'}'). The owner must submit the record first."
                ),
            )

        cur = current.get("fields", {}) or {}
        is_obligation = bool(cur.get("ObligationKey"))
        fields: dict = {
            "Status":     "Accepted" if body.accepted else ("Rejected" if is_obligation else "Pending"),
            "VerifiedBy": user.name or user.oid,
        }
        if is_obligation and body.accepted:
            # The schedule runs from the record's own date, not the day it was checked.
            fields["LastRecordDate"] = str(cur.get("PendingRecordDate") or "")[:10] or date.today().isoformat()
        if not body.accepted and body.rejection_note:
            fields["RejectionNote"] = body.rejection_note

        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"verify record {item_id}")


class ReassignRecordOwner(BaseModel):
    owner_role: str


@router.patch("/api/v1/records/{item_id}/reassign-owner")
async def reassign_record_owner(
    item_id: str,
    body: ReassignRecordOwner,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Reassign a legacy record's owner role. Compliance only. Defined obligations
    keep the Control owner stated in their defining document; role holders are
    managed in Org Roles. This endpoint does not validate legacy role names.
    """
    owner = (body.owner_role or "").strip()
    if not owner:
        raise HTTPException(status_code=422, detail="owner_role is required.")
    try:
        cur = (await get_list_item(_list_id(), _LIST_NAME, item_id)).get("fields", {}) or {}
        if cur.get("ObligationKey"):
            raise HTTPException(status_code=422, detail=(
                "This obligation's owner is the Control owner of control "
                f"{cur.get('LinkedControlId')}, stated in its defining document. Change it there; "
                "who holds the role is set in Org Roles."))
        await update_list_item(_list_id(), _LIST_NAME, item_id, {"OwnerRole": owner})
        updated = await get_list_item(_list_id(), _LIST_NAME, item_id)
        return _sp_to_record(updated)
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"reassign record owner {item_id}")


@router.patch("/api/v1/records/{item_id}/schedule")
async def schedule_obligation(
    item_id: str,
    body: ScheduleObligation,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    Set how often an obligation's record must be confirmed (and, optionally,
    how old an accepted record may be). Documents rarely state this, so a
    person decides it; until then the obligation is Unscheduled. The first
    record falls due one period after the schedule is set.
    """
    if not 1 <= body.check_frequency_days <= 3650:
        raise HTTPException(status_code=422, detail="check_frequency_days must be 1–3650.")
    if body.freshness_days is not None and not 0 <= body.freshness_days <= 3650:
        raise HTTPException(status_code=422, detail="freshness_days must be 0–3650 (0 = same as the frequency).")
    try:
        cur = (await get_list_item(_list_id(), _LIST_NAME, item_id)).get("fields", {}) or {}
        if not cur.get("ObligationKey"):
            raise HTTPException(status_code=422, detail="Only evidence obligations have a schedule.")
        fields: dict = {
            "CheckFrequencyDays": body.check_frequency_days,
            "FreshnessDays":      body.freshness_days or 0,
            "ScheduleSetBy":      user.name or user.oid,
        }
        if not cur.get("ScheduledFrom"):
            fields["ScheduledFrom"] = date.today().isoformat()
        await update_list_item(_list_id(), _LIST_NAME, item_id, fields)
        return _sp_to_record(await get_list_item(_list_id(), _LIST_NAME, item_id))
    except HTTPException:
        raise
    except Exception as exc:
        _handle(exc, f"schedule obligation {item_id}")
