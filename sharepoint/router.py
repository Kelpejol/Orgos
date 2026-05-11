# =============================================================================
# sharepoint/router.py — SharePoint file browser + extraction endpoints
# GET  /api/v1/sharepoint/browse              — root folder contents
# GET  /api/v1/sharepoint/browse/{folder_id}  — subfolder contents
# POST /api/v1/sharepoint/extract/{item_id}   — extract from SharePoint file
# Depends on: sharepoint/service.py, agents/extractor/service.py, auth/validator.py
# =============================================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from agents.extractor import service as extractor_service
from agents.extractor.schemas import ExtractionResponse
from auth.validator import CurrentUser, get_current_user
from graph.exceptions import GraphAPIError
from sharepoint import service as sp_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sharepoint", tags=["SharePoint — File Browser"])


class BrowseResponse(BaseModel):
    """Response shape for folder browse requests."""
    items: list[dict]
    has_more: bool
    next_link: Optional[str] = None


class SharePointExtractionRequest(BaseModel):
    """Request body for extracting from a SharePoint file."""
    source_document_code: str
    write_to_sharepoint: bool = False


@router.get(
    "/browse",
    response_model=BrowseResponse,
    summary="List root contents of the Compliance GRC MASTERY library",
)
async def browse_root(
    user: CurrentUser = Depends(get_current_user),
) -> BrowseResponse:
    """
    Returns the top-level folders and files in the GRC MASTERY document library.
    Folders always appear before files, both sorted alphabetically.
    """
    try:
        result = await sp_service.list_folder_contents(folder_id=None)
        return BrowseResponse(**result)
    except GraphAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        logger.exception("Failed to browse root SharePoint folder")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not access Compliance SharePoint library: {exc}",
        )


@router.get(
    "/browse/{folder_id}",
    response_model=BrowseResponse,
    summary="List contents of a specific folder",
)
async def browse_folder(
    folder_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> BrowseResponse:
    """
    Returns the contents of a specific folder by its Graph API drive item ID.
    Works for any depth of nesting — folders inside folders inside folders.
    """
    try:
        result = await sp_service.list_folder_contents(folder_id=folder_id)
        return BrowseResponse(**result)
    except GraphAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        logger.exception(f"Failed to browse SharePoint folder {folder_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not access folder: {exc}",
        )


@router.post(
    "/extract/{item_id}",
    response_model=ExtractionResponse,
    summary="Extract GRC controls from a SharePoint file",
)
async def extract_from_sharepoint(
    item_id: str,
    request: SharePointExtractionRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ExtractionResponse:
    """
    Downloads a file from SharePoint by its drive item ID and runs
    the full extraction pipeline through the local Ollama LLM.
    The file never needs to leave SharePoint — the backend fetches it
    directly and processes it locally.
    """
    try:
        file_bytes, filename = await sp_service.get_file_bytes(item_id)
    except GraphAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        logger.exception(f"Failed to fetch SharePoint file {item_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not download file from SharePoint: {exc}",
        )

    try:
        return await extractor_service.run_extraction_from_file(
            file_bytes=file_bytes,
            filename=filename,
            doc_code=request.source_document_code,
            write_to_sharepoint=request.write_to_sharepoint,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception(f"Extraction failed for SharePoint file {item_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Extraction failed: {exc}. Check that Ollama is running.",
        )