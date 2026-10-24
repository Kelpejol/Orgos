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
    from agents.extractor.ollama_client import require_legacy_extraction

    try:
        require_legacy_extraction(doc_code=request.source_document_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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

# =============================================================================
#  Read a SharePoint document as a PDF
#
#  The registers hold a document's SharePoint webUrl rather than a lifecycle
#  item id, so they cannot use the lifecycle view endpoint. This renders any
#  document in Dragnet's own SharePoint, by URL, so "View" means the same
#  thing everywhere: read it, do not open the editable source.
# =============================================================================

@router.get("/view.pdf")
async def view_sharepoint_document(
    url: str = Query(..., description="The document's SharePoint webUrl"),
    user: CurrentUser = Depends(get_current_user),
):
    from fastapi import Response

    from graph.client import download_file_from_sharepoint
    from lifecycle.preview import PDF_MEDIA, allowed_sharepoint_url, render_pdf
    from lifecycle.router import _filename_from_sharepoint_url

    if not allowed_sharepoint_url(url):
        raise HTTPException(
            status_code=400,
            detail="That URL is not a Dragnet SharePoint document.",
        )

    try:
        content, content_type = await download_file_from_sharepoint(url)
    except Exception as exc:
        logger.warning(f"Could not fetch {url} for viewing: {exc}")
        raise HTTPException(status_code=404, detail="That document could not be fetched.")

    # The stored URL is usually a Word viewer link (".../Doc.aspx?file=X.docx"),
    # whose last path segment is the viewer page, not the file.
    filename = _filename_from_sharepoint_url(url, content_type)
    # One scratch copy per document, so repeated reads overwrite rather than pile up.
    scratch = f"view_{abs(hash(url))}.docx"
    content = await render_pdf(content, filename, scratch)

    return Response(
        content=content,
        media_type=PDF_MEDIA,
        headers={
            "Content-Disposition":
                f'inline; filename="{filename.rsplit(".", 1)[0]}.pdf"',
            "Cache-Control": "no-store",
        },
    )
