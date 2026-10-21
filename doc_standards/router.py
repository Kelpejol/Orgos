# =============================================================================
# doc_standards/router.py — the Document Standards page
#
#   GET  /api/v1/doc-standards/standard          the standard (everyone)
#   POST /api/v1/doc-standards/check             upload a file, see how it fares (everyone)
#   POST /api/v1/doc-standards/convert/preview   read a file or Lifecycle item, show the proofs (Compliance)
#   POST /api/v1/doc-standards/convert/download  the converted file (Compliance)
#   POST /api/v1/doc-standards/convert/apply     convert a Lifecycle item in place (Compliance)
#
# Checking writes nothing anywhere. Previewing writes nothing. Only /apply
# changes anything, and only a Lifecycle item still in Review: the original
# file is never overwritten — the item is pointed at a new working copy.
# =============================================================================

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from cdi.parser import parse_document
from cdi.reader import UnsupportedDocument
from doc_standards import service
from doc_standards.checks import run_checks
from lifecycle.schemas import CdtCoverFacts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/doc-standards", tags=["Document Standards"])

MAX_BYTES = 15 * 1024 * 1024
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _read_upload(file: UploadFile, allowed: tuple[str, ...]) -> tuple[bytes, str]:
    name = os.path.basename(file.filename or "document")
    if not name.lower().endswith(allowed):
        raise HTTPException(status_code=422, detail=f"Upload a {' or '.join(allowed)} file.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 15 MB.")
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")
    return data, name


@router.get("/standard")
async def get_standard(user: CurrentUser = Depends(get_current_user)) -> dict:
    return service.standard_view()


@router.post("/check")
async def check_document(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)) -> dict:
    data, name = await _read_upload(file, (".docx", ".pdf"))
    try:
        parsed = await asyncio.to_thread(parse_document, data, name)
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Could not read %s", name)
        raise HTTPException(status_code=422, detail=f"The document could not be read ({type(exc).__name__}).")
    ctx, notes = await service.build_context(parsed)
    report = await asyncio.to_thread(run_checks, parsed, name, data, ctx)
    report["context_notes"] = notes
    return report


# ── conversion ──────────────────────────────────────────────────────────────

def _code_conflict(fields: dict, plan) -> str:
    """The Lifecycle item and the document must agree on the document's code. If they
    do not, that disagreement is the very drift conversion exists to end — it is shown
    and resolved by a person, not papered over by whichever happens to win."""
    from cdi.library import _base_code
    stored = (fields.get("DocumentCode") or "").strip()
    if stored and plan.code and _base_code(stored) != _base_code(plan.code):
        return (f"The Lifecycle item's document code is {stored}, but the document states {plan.code}. "
                "Correct whichever is wrong first.")
    return ""


async def _lifecycle_source(item_id: str) -> tuple[bytes, str, CdtCoverFacts, dict]:
    """The file, name and cover facts of a Lifecycle item that can still be converted."""
    from graph.client import download_file_from_sharepoint, get_list_item
    from lifecycle.router import _LIST_NAME, _filename_from_sharepoint_url, _get_list_id
    try:
        fields = (await get_list_item(_get_list_id(), _LIST_NAME, item_id)).get("fields", {}) or {}
    except Exception:
        raise HTTPException(status_code=404, detail="That Lifecycle item was not found.")
    if fields.get("Stage") != "Review" or fields.get("ApprovalStatus") == "Approved":
        raise HTTPException(status_code=409, detail="Only a document still in Review can be converted.")
    url = fields.get("SharePointFileUrl")
    if not url:
        raise HTTPException(status_code=422, detail="That item has no file yet.")
    data, content_type = await download_file_from_sharepoint(url)
    name = _filename_from_sharepoint_url(url, content_type)
    try:
        cover = CdtCoverFacts.from_json(fields.get("CDTCoverFacts", ""))
    except ValueError:
        cover = CdtCoverFacts()
    return data, name, cover, fields


@router.post("/convert/preview")
async def convert_preview(file: Optional[UploadFile] = File(None), item_id: Optional[str] = Form(None),
                          user: CurrentUser = Depends(require_compliance_lead)) -> dict:
    """Read, build and PROVE the conversion; return what would happen. Writes nothing."""
    fields: dict = {}
    if bool(file) == bool(item_id):
        raise HTTPException(status_code=422, detail="Give either a file or a Lifecycle item, not both.")
    if file:
        data, name = await _read_upload(file, (".docx", ".pdf", ".doc"))
        cover, source = None, {"kind": "upload"}
    else:
        data, name, cover, fields = await _lifecycle_source(item_id)
        source = {"kind": "lifecycle", "item_id": item_id}
    plan = await service.plan_conversion(data, name, cover)
    if item_id and plan.ok and (conflict := _code_conflict(fields, plan)):
        plan.ok, plan.reason = False, conflict
        plan.source_bytes = plan.preview_bytes = b""
    return {**plan.as_dict(), "source": source}


@router.post("/convert/download")
async def convert_download(file: UploadFile = File(...), kind: str = Form("reading"),
                           user: CurrentUser = Depends(require_compliance_lead)) -> Response:
    """The converted file of an upload. `reading` is filled in, to read and check;
    `source` still has its cover placeholders, which is the form the system keeps."""
    if kind not in ("reading", "source"):
        raise HTTPException(status_code=422, detail="kind must be 'reading' or 'source'.")
    data, name = await _read_upload(file, (".docx",))
    plan = await service.plan_conversion(data, name)
    if not plan.ok:
        raise HTTPException(status_code=422, detail=plan.reason)
    payload = plan.preview_bytes if kind == "reading" else plan.source_bytes
    out = re.sub(r'[\\/:*?"<>|]+', "", plan.title).strip() or "document"
    suffix = "" if kind == "source" else " (reading copy)"
    return Response(content=payload, media_type=DOCX,
                    headers={"Content-Disposition": f'attachment; filename="{out}{suffix}.docx"'})


class ApplyConversion(BaseModel):
    item_id: str


@router.post("/convert/apply")
async def convert_apply(body: ApplyConversion, user: CurrentUser = Depends(require_compliance_lead)) -> dict:
    """
    Convert a Lifecycle item in Review. The original file is not touched: the
    converted file becomes the item's own working copy, named as its title, and
    the cover facts are saved on the item so the Register is the master from
    here on. Refused unless every proof holds.
    """
    from graph.client import update_list_item
    from lifecycle.router import (_LIST_NAME, _audit_lifecycle_action, _cdi_check_file, _get_list_id,
                                  _sp_to_doc, _upload_to_sharepoint)
    from graph.client import get_list_item
    data, name, cover, fields = await _lifecycle_source(body.item_id)
    plan = await service.plan_conversion(data, name, cover)
    if plan.ok and (conflict := _code_conflict(fields, plan)):
        plan.ok, plan.reason = False, conflict
    if not plan.ok:
        raise HTTPException(status_code=422, detail={"message": plan.reason, "plan": plan.as_dict()})

    filename = re.sub(r'[\\/:*?"<>|]+', "", plan.title).strip() + ".docx"      # V23: the file is named as its title
    try:
        url = await _upload_to_sharepoint(body.item_id, filename, plan.source_bytes)
        update = {"SharePointFileUrl": url, "CDTCoverFacts": plan.facts.to_json(), "Title": plan.title,
                  "Revised": True, "CDIStatus": "Pending", "CDIFailures": ""}
        if not fields.get("DocumentCode"):
            update["DocumentCode"] = plan.code
        await update_list_item(_get_list_id(), _LIST_NAME, body.item_id, update)
        status_, failures = await _cdi_check_file(body.item_id, plan.source_bytes, filename)
        await update_list_item(_get_list_id(), _LIST_NAME, body.item_id,
                               {"CDIStatus": status_, "CDIFailures": failures})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Converting lifecycle item %s failed", body.item_id)
        raise HTTPException(status_code=503, detail=f"The conversion was built and proved but could not be saved: {exc}")
    await _audit_lifecycle_action(
        {**fields, "id": body.item_id}, user, "Converted to CDT",
        f"{len(plan.taken_out)} header row(s) replaced by the cover; {len(plan.stays)} kept; "
        f"proofs: {', '.join(p.name for p in plan.proofs)}. The original file is unchanged.")
    updated = await _sp_to_doc(await get_list_item(_get_list_id(), _LIST_NAME, body.item_id))
    return {"ok": True, "item": updated, "plan": plan.as_dict()}
