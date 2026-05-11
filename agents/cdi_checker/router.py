# =============================================================================
# agents/cdi_checker/router.py
# POST /api/v1/agents/cdi-check   — check a document file upload
# POST /api/v1/agents/cdi-check-url — check a document by SharePoint URL
# Used by:
#   - Document Lifecycle upload action (runs automatically on upload)
#   - Phase 0 CDI triage script
# =============================================================================

import logging

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from auth.validator import CurrentUser, get_current_user
from agents.cdi_checker.service import run_cdi_check
from config import settings
from graph.auth import get_graph_access_token
from graph.client import get_list_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["CDI Checker"])


async def _fetch_role_titles() -> list[str]:
    """Fetch all role titles from the Role Register for CDI-07 check."""
    try:
        items = await get_list_items(settings.role_register_list_id, "Role Register")
        return [
            i.get("fields", {}).get("Title", "")
            for i in items
            if i.get("fields", {}).get("Title")
        ]
    except Exception:
        return []


@router.post("/cdi-check")
async def check_document_upload(
    doc_code: str = "",
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Run CDI checks against an uploaded document file.
    Returns PASS/FAIL per check with proposed fix for each failure.
    Used by the Document Lifecycle upload action.
    """
    file_bytes = await file.read()
    filename   = file.filename or "document.docx"

    role_titles = await _fetch_role_titles()
    result      = await run_cdi_check(file_bytes, filename, doc_code, role_titles)

    logger.info(
        f"CDI check: {filename} | code={doc_code} | "
        f"passed={result['passed']} | fails={result['fail_count']}"
    )
    return result


class CDICheckUrlRequest(BaseModel):
    file_url:  str
    doc_code:  str = ""
    filename:  str = "document.docx"


@router.post("/cdi-check-url")
async def check_document_by_url(
    body: CDICheckUrlRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Run CDI checks against a document at a SharePoint URL.
    Used by the Phase 0 CDI triage script.
    Downloads the file via Graph API then runs all 15 checks.
    """
    try:
        token = await get_graph_access_token()
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(
                body.file_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            file_bytes = resp.content
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not download document from SharePoint: {exc}",
        )

    role_titles = await _fetch_role_titles()
    result      = await run_cdi_check(file_bytes, body.filename, body.doc_code, role_titles)

    logger.info(
        f"CDI check (URL): {body.filename} | code={body.doc_code} | "
        f"passed={result['passed']} | fails={result['fail_count']}"
    )
    return result