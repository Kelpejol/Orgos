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

# router = APIRouter(prefix="/api/v1/agents", tags=["Policy Drafter"])


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
#     logger.info(f"Policy Drafter requested: '{body.title}' by {user.name}")

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
#         logger.exception("Policy Drafter generation failed")
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
#   Takes a document brief, generates a CDI-compliant draft using Ollama,
#   creates a Document Lifecycle entry, and stores the .docx in SharePoint.
#
# The .docx is built server-side by docx_builder.py so the frontend just
# needs an authenticated GET to /api/v1/lifecycle/documents/{id}/download
# — no copy-paste, no manual formatting step.
# =============================================================================

import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from auth.validator import CurrentUser, get_current_user
from agents.policy_drafter.service import draft_document
from config import settings
from graph.client import (
    create_list_item,
    get_list_items,
    upload_file_to_sharepoint,   # you must have / add this helper — see note below
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Policy Drafter"])


# =============================================================================
#  Helper: fetch role titles from the Role Register list
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
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    1. Generate all sections via Ollama.
    2. Build a formatted .docx with docx_builder.
    3. Upload the .docx to SharePoint (document library).
    4. Create a Document Lifecycle list entry pointing at the SharePoint file.
    5. Return the lifecycle_id and doc_code so the frontend can surface them.

    The frontend should then call GET /api/v1/lifecycle/documents/{id}/download
    (authenticated) to stream the file to the user — no copy-paste required.
    """
    logger.info(f"Policy Drafter requested: '{body.title}' by {user.name}")

    role_titles = await _fetch_role_titles()

    # ── 1 + 2: Generate draft text AND build .docx ────────────────────────────
    try:
        draft = await draft_document(
            title=             body.title,
            doc_type=          body.doc_type,
            department=        body.department,
            notes=             body.notes,
            standards_mapping= body.standards_mapping,
            role_titles=       role_titles,
        )
        logger.info(f"Draft + docx built: {draft['doc_code']}")
    except Exception as exc:
        logger.exception("Policy Drafter generation failed")
        raise HTTPException(
            status_code=503,
            detail=f"Document generation failed: {exc}. Check that Ollama is running.",
        )

    # ── 3: Upload .docx to SharePoint ─────────────────────────────────────────
    # docx_buffer is a BytesIO returned by build_docx() in docx_builder.py
    sharepoint_url: Optional[str] = None
    docx_buffer = draft.get("docx_buffer")
    filename = f"{draft['doc_code']}_v1.0_DRAFT.docx"

    if docx_buffer:
        try:
            sharepoint_url = await upload_file_to_sharepoint(
                file_bytes=docx_buffer.read(),
                filename=filename,
                folder="Document Lifecycle Drafts",   # adjust to your library/folder
            )
            logger.info(f"Uploaded to SharePoint: {sharepoint_url}")
        except Exception as exc:
            # Non-fatal — lifecycle entry still created, download falls back to DB
            logger.warning(f"SharePoint upload failed (non-fatal): {exc}")

    # ── 4: Create Document Lifecycle entry ────────────────────────────────────
    lifecycle_fields = {
        "Title":            body.title,
        "DocumentCode":     draft["doc_code"],
        "DocumentType":     body.doc_type,
        "Department":       body.department,
        "Stage":            "Review",
        "Trigger":          body.trigger,
        "AIGenerated":      True,
        "Revised":          False,
        "OwnerEntraId":     user.oid,
        "StandardsMapping": body.standards_mapping,
        "Notes": (
            f"AI-generated draft — {draft['doc_code']}\n\n"
            f"Download the .docx, review and revise per CDI standards, "
            f"then upload the revised version to progress through the lifecycle."
        ),
    }
    if sharepoint_url:
        lifecycle_fields["SharePointFileUrl"] = sharepoint_url
    if body.linked_gap_id:
        lifecycle_fields["LinkedGapId"] = body.linked_gap_id

    try:
        lifecycle_item = await create_list_item(
            settings.document_lifecycle_list_id,
            "Document Lifecycle",
            lifecycle_fields,
        )
        lifecycle_id = str(lifecycle_item["id"])
        logger.info(f"Lifecycle entry created: {lifecycle_id} for {draft['doc_code']}")
    except Exception as exc:
        logger.exception("Failed to create lifecycle entry")
        raise HTTPException(
            status_code=500,
            detail=f"Draft generated but lifecycle entry creation failed: {exc}",
        )

    # Strip BytesIO from the response (not JSON-serialisable)
    draft.pop("docx_buffer", None)

    return {
        "lifecycle_id":  lifecycle_id,
        "doc_code":      draft["doc_code"],
        "title":         draft["title"],
        "sections":      draft["sections"],
        "full_text":     draft["full_text"],
        "sharepoint_url": sharepoint_url,
        "message": (
            f"Draft generated and lifecycle entry created. "
            f"Document code: {draft['doc_code']}. "
            f"Download the formatted .docx from the lifecycle card, revise, and upload."
        ),
    }


# =============================================================================
#  NOTE — upload_file_to_sharepoint helper
#
#  If graph/client.py doesn't yet have this function, add it:
#
#  async def upload_file_to_sharepoint(
#      file_bytes: bytes,
#      filename: str,
#      folder: str = "Document Lifecycle Drafts",
#  ) -> str:
#      """Upload bytes to a SharePoint document library. Returns the item web URL."""
#      site_id  = settings.sharepoint_site_id    # add to config if missing
#      drive_id = settings.sharepoint_drive_id   # add to config if missing
#      token    = await get_graph_token()
#      url = (
#          f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}"
#          f"/root:/{folder}/{filename}:/content"
#      )
#      async with httpx.AsyncClient() as client:
#          resp = await client.put(
#              url,
#              content=file_bytes,
#              headers={
#                  "Authorization": f"Bearer {token}",
#                  "Content-Type": (
#                      "application/vnd.openxmlformats-officedocument"
#                      ".wordprocessingml.document"
#                  ),
#              },
#          )
#          resp.raise_for_status()
#          return resp.json().get("webUrl", "")
# =============================================================================