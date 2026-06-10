# # =============================================================================
# # agents/policy_drafter/router.py
# # POST /api/v1/agents/draft-document
# #   Takes a document brief, generates a CDI-compliant draft using Ollama,
# #   creates a Document Lifecycle entry with the draft uploaded to SharePoint.
# # =============================================================================

# import logging

# from fastapi import APIRouter, Depends, HTTPException
# from pydantic import BaseModel
# from typing import Optional

# from auth.validator import CurrentUser, get_current_user
# from agents.policy_drafter.service import draft_document
# from config import settings
# from graph.client import (
#     create_list_item,
#     get_list_items,
# )

# logger = logging.getLogger(__name__)

# router = APIRouter(prefix="/api/v1/agents", tags=["Document Drafter"])


# async def _fetch_role_titles() -> list[str]:
#     try:
#         items = await get_list_items(settings.role_register_list_id, "Role Register")
#         return [
#             i.get("fields", {}).get("Title", "")
#             for i in items
#             if i.get("fields", {}).get("Title")
#         ]
#     except Exception:
#         return []


# class DraftRequest(BaseModel):
#     title:             str
#     doc_type:          str = "Policy"
#     department:        str
#     notes:             str = ""
#     standards_mapping: str = ""
#     trigger:           str = "Manual"
#     linked_gap_id:     Optional[str] = None


# @router.post("/draft-document")
# async def draft_document_endpoint(
#     body: DraftRequest,
#     user: CurrentUser = Depends(get_current_user),
# ) -> dict:
#     """
#     Generate a CDI-compliant document draft and create a Document Lifecycle entry.
#     The draft is stored as plain text in the lifecycle entry's Notes field.
#     The document owner then copies it into a properly formatted Word document,
#     uploads it via the lifecycle Upload action, and proceeds through the pipeline.
#     Returns the lifecycle entry ID and the generated draft.
#     """
#     logger.info(f"Document Drafter requested: '{body.title}' by {user.name}")

#     role_titles = await _fetch_role_titles()

#     # Generate draft
#     try:
#         draft = await draft_document(
#             title=             body.title,
#             doc_type=          body.doc_type,
#             department=        body.department,
#             notes=             body.notes,
#             standards_mapping= body.standards_mapping,
#             role_titles=       role_titles,
#         )
#         print(f"Draft generated with code, {draft}")
#     except Exception as exc:
#         logger.exception("Document Drafter generation failed")
#         raise HTTPException(
#             status_code=503,
#             detail=f"Document generation failed: {exc}. Check that Ollama is running.",
#         )

#     # Create Document Lifecycle entry
#     lifecycle_fields = {
#         "Title":           body.title,
#         "DocumentCode":    draft["doc_code"],
#         "DocumentType":    body.doc_type,
#         "Department":      body.department,
#         "Stage":           "Review",
#         "Trigger":         body.trigger,
#         "AIGenerated":     True,
#         "Revised":         False,
#         "OwnerEntraId":    user.oid,
#         "StandardsMapping": body.standards_mapping,
#         "Notes":           (
#             f"AI-generated draft — {draft['doc_code']}\n\n"
#             f"Review the draft in the DraftContent field. "
#             f"Copy into a Word document, format per CDI standards, "
#             f"and upload via the Upload button to progress."
#         ),
#     }
#     if body.linked_gap_id:
#         lifecycle_fields["LinkedGapId"] = body.linked_gap_id

#     try:
#         lifecycle_item = await create_list_item(
#             settings.document_lifecycle_list_id,
#             "Document Lifecycle",
#             lifecycle_fields,
#         )
#         lifecycle_id = str(lifecycle_item["id"])
#         logger.info(f"Document Lifecycle entry created: {lifecycle_id} for {draft['doc_code']}")
#     except Exception as exc:
#         logger.exception("Failed to create lifecycle entry")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Draft generated but lifecycle entry creation failed: {exc}",
#         )

#     return {
#         "lifecycle_id": lifecycle_id,
#         "doc_code":     draft["doc_code"],
#         "title":        draft["title"],
#         "sections":     draft["sections"],
#         "full_text":    draft["full_text"],
#         "message":      (
#             f"Draft generated and lifecycle entry created. "
#             f"Document code: {draft['doc_code']}. "
#             f"Copy the full_text into a Word document, format per CDI standards, "
#             f"and upload via the Document Lifecycle Upload button."
#         ),
#     }













# =============================================================================
# agents/policy_drafter/router.py
# POST /api/v1/agents/draft-document
#   1. Generate all sections via Ollama.
#   2. Build a formatted .docx with docx_builder (python-docx, no new library needed).
#   3. Run CDI check against the generated .docx immediately.
#   4. Upload to SharePoint via /drive/root:/ path (no drive_id config needed).
#   5. Create a Document Lifecycle entry with CDI results and SP file URL.
#   6. Return lifecycle_id, doc_code, CDI report, AND docx_base64 so the
#      frontend can trigger a direct browser download even if SP upload failed.
# =============================================================================

import base64
import io
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from agents.policy_drafter.service import draft_document, generate_doc_code_base
from agents.cdi_checker.service import run_cdi_check
from config import settings
from graph.client import (
    create_list_item,
    get_list_items,
    resolve_user,
    update_list_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Document Drafter"])


# =============================================================================
#  Helpers
# =============================================================================

async def _fetch_role_titles() -> list[str]:
    try:
        items = await get_list_items(settings.role_register_list_id, "Role Register")
        return [
            i.get("fields", {}).get("Title", "")
            for i in items
            if i.get("fields", {}).get("Title")
        ]
    except Exception:
        return []


async def _resolve_display_name(entra_oid: str, fallback: str = "") -> str:
    fallback = (fallback or "").strip()
    if not entra_oid:
        return fallback
    try:
        resolved = await resolve_user(entra_oid)
        return (resolved.get("display_name") or "").strip() or fallback
    except Exception:
        return fallback


async def _write_lifecycle_owner_name(item_id: str, owner_oid: str, fallback: str = "") -> str:
    owner_name = await _resolve_display_name(owner_oid, fallback)
    if owner_name and item_id and settings.is_list_configured(settings.document_lifecycle_list_id):
        await update_list_item(
            settings.document_lifecycle_list_id,
            "Document Lifecycle",
            item_id,
            {"Owner": owner_name},
        )
    return owner_name


async def _next_serial(base_prefix: str) -> str:
    """
    Query the Document Lifecycle list for existing items whose DocumentCode
    starts with base_prefix and return the next sequential serial number.
    Example: base_prefix="DRG-SD-POL-ACCCON" → finds "DRG-SD-POL-ACCCON-01-26"
    → returns "02".
    Falls back to "01" if the list is unconfigured or the query fails.
    """
    try:
        items = await get_list_items(
            settings.document_lifecycle_list_id, "Document Lifecycle"
        )
        max_serial = 0
        for item in items:
            code = item.get("fields", {}).get("DocumentCode", "")
            if code.startswith(base_prefix + "-"):
                parts = code.split("-")
                # Format: DRG-DEPT-TYPE-SHORT-SERIAL-YEAR  (6 parts)
                if len(parts) >= 6:
                    try:
                        max_serial = max(max_serial, int(parts[-2]))
                    except ValueError:
                        pass
        return f"{(max_serial + 1):02d}"
    except Exception:
        return "01"


# =============================================================================
#  Request schema
# =============================================================================

class DraftRequest(BaseModel):
    title:             str
    doc_type:          str = "Policy"
    department:        str
    notes:             str = ""
    standards_mapping: str = ""
    trigger:           str = "Manual"
    linked_gap_id:     Optional[str] = None


# =============================================================================
#  POST /api/v1/agents/draft-document
# =============================================================================

@router.post("/draft-document")
async def draft_document_endpoint(
    body: DraftRequest,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    1. Compute the next serial for this doc code base (auto-increment).
    2. Generate all sections via Ollama.
    3. Build a formatted .docx (server-side, python-docx — no new technology needed).
    4. Run CDI check against the generated .docx.
    5. Create a Document Lifecycle entry (no SharePoint upload — user downloads
       the .docx from the response, edits locally, then uploads via the lifecycle
       Upload button when ready).
    6. Return docx_base64 so the frontend can trigger an immediate browser download.
    """
    logger.info(f"Document Drafter requested: '{body.title}' by {user.name}")

    role_titles = await _fetch_role_titles()

    # ── 1: Auto-increment serial ──────────────────────────────────────────────
    base_prefix = generate_doc_code_base(body.department, body.doc_type, body.title)
    serial      = await _next_serial(base_prefix)
    logger.info(f"Doc code base: {base_prefix}, next serial: {serial}")

    # ── 2 + 3: Generate sections via Ollama + build .docx ────────────────────
    try:
        draft = await draft_document(
            title=             body.title,
            doc_type=          body.doc_type,
            department=        body.department,
            notes=             body.notes,
            standards_mapping= body.standards_mapping,
            role_titles=       role_titles,
            serial=            serial,
        )
        logger.info(f"Draft + docx built: {draft['doc_code']}")
    except Exception as exc:
        logger.exception("Document Drafter generation failed")
        raise HTTPException(
            status_code=503,
            detail=f"Document generation failed: {exc}. Check that Ollama is running.",
        )

    docx_buffer: Optional[io.BytesIO] = draft.pop("docx_buffer", None)
    docx_bytes = docx_buffer.read() if docx_buffer else b""
    filename   = f"{draft['doc_code']}_v1.0_DRAFT.docx"

    # ── 4: Run CDI check against the generated .docx ─────────────────────────
    cdi_result: dict = {}
    cdi_status        = "Pending"
    cdi_failures_json = ""
    if docx_bytes:
        try:
            cdi_result = await run_cdi_check(
                file_bytes=docx_bytes,
                filename=filename,
                doc_code=draft["doc_code"],
                role_register_titles=role_titles,
            )
            if cdi_result.get("error"):
                cdi_status = "Error"
            elif cdi_result.get("passed"):
                cdi_status = "Passed"
            else:
                cdi_status = "Failed"
                cdi_failures_json = json.dumps([
                    {"check": c["check_id"], "detail": c["finding"], "fix": c.get("proposed_fix", "")}
                    for c in cdi_result.get("checks", []) if c["result"] == "FAIL"
                ])
            logger.info(
                f"CDI check on AI draft {draft['doc_code']}: "
                f"{cdi_status} — {cdi_result.get('fail_count', 0)} failures"
            )
        except Exception as exc:
            logger.warning(f"CDI check on AI draft failed: {exc}")
            cdi_status = "Error"

    # ── 5: Create Document Lifecycle entry (no SharePoint upload yet) ─────────
    # The user downloads the draft from docx_base64, edits it locally, and
    # uploads the revised version via PATCH /lifecycle/documents/{id}/upload
    # which handles the SharePoint upload and CDI re-check at that point.
    owner_name = await _resolve_display_name(user.oid, user.name)

    lifecycle_fields: dict = {
        "Title":            body.title,
        "DocumentCode":     draft["doc_code"],
        "DocumentType":     body.doc_type,
        "Department":       body.department,
        "Stage":            "Review",
        "Trigger":          body.trigger,
        "AIGenerated":      True,
        "Revised":          False,
        "OwnerEntraId":     user.oid,
        "Owner":            owner_name,
        "CDIStatus":        cdi_status,
        "StandardsMapping": draft["standards_mapping"],  # always non-empty
        "Notes": (
            f"AI-generated draft — {draft['doc_code']}. "
            f"CDI check on draft: {cdi_status} "
            f"({cdi_result.get('pass_count', 0)} passed, {cdi_result.get('fail_count', 0)} failed). "
            f"Download the .docx, revise, then upload via the Upload button."
        ),
    }
    if cdi_failures_json:
        lifecycle_fields["CDIFailures"] = cdi_failures_json
    if body.linked_gap_id:
        lifecycle_fields["LinkedGapId"] = body.linked_gap_id

    try:
        lifecycle_item = await create_list_item(
            settings.document_lifecycle_list_id,
            "Document Lifecycle",
            lifecycle_fields,
        )
        lifecycle_id = str(lifecycle_item["id"])
        try:
            await _write_lifecycle_owner_name(lifecycle_id, user.oid, owner_name)
        except Exception as exc:
            logger.warning(
                f"Lifecycle entry {lifecycle_id} created, but Owner text field "
                f"could not be populated: {exc}"
            )
        logger.info(f"Lifecycle entry created: {lifecycle_id} for {draft['doc_code']}")
    except Exception as exc:
        logger.exception("Failed to create lifecycle entry")
        raise HTTPException(
            status_code=500,
            detail=f"Draft generated but lifecycle entry creation failed: {exc}",
        )

    # ── 6: Return lifecycle metadata + base64 docx ───────────────────────────
    docx_b64 = base64.b64encode(docx_bytes).decode("ascii") if docx_bytes else None

    cdi_summary = {
        "status":     cdi_status,
        "pass_count": cdi_result.get("pass_count", 0),
        "fail_count": cdi_result.get("fail_count", 0),
        "failures": [
            {"check": c["check_id"], "detail": c["finding"], "fix": c.get("proposed_fix", "")}
            for c in cdi_result.get("checks", []) if c.get("result") == "FAIL"
        ] if cdi_result else [],
    }

    return {
        "lifecycle_id": lifecycle_id,
        "doc_code":     draft["doc_code"],
        "title":        draft["title"],
        "sections":     draft["sections"],
        "full_text":    draft["full_text"],
        "docx_base64":  docx_b64,
        "filename":     filename,
        "cdi_check":    cdi_summary,
    }
