# =============================================================================
# lifecycle/preview.py — render a SharePoint document as a PDF for reading
#
# A document should be READ as a PDF, never opened as the editable Word file.
# Most people here have edit rights on the library, so handing a reviewer the
# source means they can change it by typing in it — and that change would never
# meet the CDI check that an upload runs.
#
# Microsoft Graph does the conversion, and it needs a real driveItem, not raw
# bytes. A file read as it is is converted where it is (render_file_pdf): no
# copy. Only a document whose cover is filled in for reading has no file of
# its own; it is written to a scratch folder, converted, and deleted at once,
# so no second copy of a document is ever left in SharePoint.
# =============================================================================

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import HTTPException

from config import settings
from graph.client import (
    convert_drive_item_to_pdf,
    delete_drive_item,
    drive_item_pdf,
    ensure_drive_folder,
    resolve_compliance_drive,
    upload_bytes_to_drive,
)

logger = logging.getLogger(__name__)

PDF_MEDIA = "application/pdf"
PREVIEW_FOLDER = "_CDT_Previews"


def allowed_sharepoint_url(url: str) -> bool:
    """
    True if `url` points at one of Dragnet's own SharePoint hosts.

    Rendering takes a URL, so without this check OrgOS would fetch and return
    whatever a caller named. Graph's /shares only reaches tenant content, but
    the host is checked here too rather than relying on that.
    """
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return False
    allowed = {
        (urlparse(settings.sharepoint_site_url).hostname or "").lower(),
        (urlparse(settings.compliance_site_url).hostname or "").lower(),
    }
    return host in {h for h in allowed if h}


async def render_pdf(content: bytes, filename: str, scratch_name: str) -> bytes:
    """
    `content` as PDF bytes. A PDF is returned unchanged; anything else is
    converted by Graph from a scratch file named `scratch_name`, which is
    deleted as soon as it has been converted.
    """
    if filename.lower().endswith(".pdf"):
        return content
    try:
        _, drive_id = await resolve_compliance_drive()
        await ensure_drive_folder(drive_id, PREVIEW_FOLDER)
        scratch = await upload_bytes_to_drive(drive_id, PREVIEW_FOLDER, scratch_name, content)
        try:
            return await convert_drive_item_to_pdf(drive_id, f"{PREVIEW_FOLDER}/{scratch_name}")
        finally:
            try:
                await delete_drive_item(drive_id, scratch.get("id", ""))
            except Exception as exc:
                logger.info(f"The scratch file {scratch_name} was not deleted: {exc}")
    except Exception as exc:
        logger.warning(f"PDF conversion failed for {filename}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Could not render this document for reading. Open it in SharePoint instead.",
        )


async def render_file_pdf(drive_id: str, item_id: str, filename: str) -> bytes:
    """A document's own file as PDF, converted where it is: nothing is copied."""
    try:
        return await drive_item_pdf(drive_id, item_id)
    except Exception as exc:
        logger.warning(f"PDF conversion failed for {filename}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Could not render this document for reading. Open it in SharePoint instead.",
        )
