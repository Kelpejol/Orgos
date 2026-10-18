# =============================================================================
# lifecycle/preview.py — render a SharePoint document as a PDF for reading
#
# A document should be READ as a PDF, never opened as the editable Word file.
# Most people here have edit rights on the library, so handing a reviewer the
# source means they can change it by typing in it — and that change would never
# meet the CDI check that an upload runs.
#
# Microsoft Graph does the conversion (it needs a real driveItem, not raw
# bytes), so the copy is written to a scratch folder purely to be converted.
# The source is never touched.
# =============================================================================

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import HTTPException

from config import settings
from graph.client import (
    convert_drive_item_to_pdf,
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
    converted by Graph. `scratch_name` names the disposable copy, so repeated
    renders of the same document overwrite one another instead of piling up.
    """
    if filename.lower().endswith(".pdf"):
        return content
    try:
        _, drive_id = await resolve_compliance_drive()
        await ensure_drive_folder(drive_id, PREVIEW_FOLDER)
        await upload_bytes_to_drive(drive_id, PREVIEW_FOLDER, scratch_name, content)
        return await convert_drive_item_to_pdf(drive_id, f"{PREVIEW_FOLDER}/{scratch_name}")
    except Exception as exc:
        logger.warning(f"PDF conversion failed for {filename}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Could not render this document for reading. Download it instead.",
        )
