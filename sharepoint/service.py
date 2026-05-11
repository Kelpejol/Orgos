# =============================================================================
# sharepoint/service.py — SharePoint file browser service
# Lists folders and files from the Compliance SharePoint library.
# Supports recursive folder navigation and file content fetching for extraction.
# Depends on: config.py, graph/client.py, graph/auth.py
# =============================================================================

import logging
from typing import Optional

import httpx

from config import settings
from graph.auth import get_graph_access_token
from graph.exceptions import GraphAPIError

logger = logging.getLogger(__name__)

# Cache the compliance site ID and drive ID after first resolution
_compliance_site_id: Optional[str] = None
_compliance_drive_id: Optional[str] = None


async def _get_headers() -> dict:
    """Build auth headers for Graph API calls."""
    token = await get_graph_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _resolve_compliance_site() -> tuple[str, str]:
    """
    Resolve the Compliance SharePoint site ID and GRC MASTERY drive ID.
    Results are cached for the lifetime of the process.
    Returns (site_id, drive_id).
    """
    global _compliance_site_id, _compliance_drive_id

    if _compliance_site_id and _compliance_drive_id:
        return _compliance_site_id, _compliance_drive_id

    headers = await _get_headers()
    base = settings.graph_base_url

    # Extract hostname and path from the compliance site URL
    # e.g. https://dragnetnigeria.sharepoint.com/sites/compliance
    url = settings.compliance_site_url.rstrip("/")
    parts = url.replace("https://", "").split("/", 1)
    hostname = parts[0]
    path = parts[1] if len(parts) > 1 else ""

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get site ID
        site_resp = await client.get(
            f"{base}/sites/{hostname}:/{path}",
            headers=headers,
        )
        site_resp.raise_for_status()
        site_data = site_resp.json()
        site_id = site_data["id"]

        # Get the specific drive (document library) by name
        drives_resp = await client.get(
            f"{base}/sites/{site_id}/drives",
            headers=headers,
        )
        drives_resp.raise_for_status()
        drives = drives_resp.json().get("value", [])

        drive_id = None
        for drive in drives:
            if drive.get("name") == settings.compliance_library_name:
                drive_id = drive["id"]
                break

        if not drive_id:
            # Fall back to the default Documents drive
            logger.warning(
                f"Drive '{settings.compliance_library_name}' not found. "
                f"Available: {[d.get('name') for d in drives]}. "
                "Falling back to first available drive."
            )
            drive_id = drives[0]["id"] if drives else None

        if not drive_id:
            raise GraphAPIError(404, "No document library found in Compliance site")

    _compliance_site_id = site_id
    _compliance_drive_id = drive_id
    logger.info(f"Compliance site resolved — site_id={site_id}, drive_id={drive_id}")
    return site_id, drive_id


def _classify_item(item: dict) -> dict:
    """
    Convert a raw Graph API drive item into a clean dict for the frontend.
    Determines item type and what action should be shown.
    """
    is_folder = "folder" in item
    name = item.get("name", "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    # Determine action based on file type
    if is_folder:
        action = "browse"
    elif ext == "eml":
        action = "link_evidence"   # EML = evidence, not extraction
    elif ext in ("pdf", "docx", "txt"):
        action = "extract"
    else:
        action = "unsupported"

    return {
        "id": item.get("id"),
        "name": name,
        "type": "folder" if is_folder else "file",
        "extension": ext if not is_folder else None,
        "action": action,
        "size": item.get("size", 0),
        "modified": item.get("lastModifiedDateTime"),
        "modified_by": item.get("lastModifiedBy", {}).get("user", {}).get("displayName"),
        "download_url": item.get("@microsoft.graph.downloadUrl"),
        "web_url": item.get("webUrl"),
        "child_count": item.get("folder", {}).get("childCount", 0) if is_folder else None,
    }


async def list_folder_contents(folder_id: Optional[str] = None) -> dict:
    """
    List the contents of a folder in the Compliance SharePoint library.
    If folder_id is None, starts from the configured starting folder (GRC MASTERY).
    Supports arbitrary nesting depth via item IDs for all subfolders.
    """
    site_id, drive_id = await _resolve_compliance_site()
    headers = await _get_headers()
    base = settings.graph_base_url

    if folder_id:
        # Navigate by item ID — works at any depth
        url = f"{base}/drives/{drive_id}/items/{folder_id}/children"
    else:
        # Start from the configured starting folder by path
        starting = settings.compliance_starting_folder
        url = f"{base}/drives/{drive_id}/root:/{starting}:/children"

    params = {
        "$top": 200,
        "$orderby": "name asc",
        "$select": (
            "id,name,size,folder,file,lastModifiedDateTime,"
            "lastModifiedBy,webUrl,@microsoft.graph.downloadUrl"
        ),
    }

    all_items = []
    has_more = False
    next_link = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        current_url = url
        first_page = True

        while current_url:
            resp = await client.get(
                current_url,
                headers=headers,
                params=params if first_page else None,
            )
            resp.raise_for_status()
            data = resp.json()
            all_items.extend(data.get("value", []))

            next_link = data.get("@odata.nextLink")
            if next_link:
                has_more = True
                break

            current_url = None
            first_page = False

    classified = [_classify_item(item) for item in all_items]
    folders = sorted(
        [i for i in classified if i["type"] == "folder"],
        key=lambda x: x["name"].lower()
    )
    files = sorted(
        [i for i in classified if i["type"] == "file"],
        key=lambda x: x["name"].lower()
    )

    return {
        "items": folders + files,
        "has_more": has_more,
        "next_link": next_link,
    }

async def get_file_bytes(item_id: str) -> tuple[bytes, str]:
    """
    Download a file from SharePoint by its drive item ID.
    Uses the /content endpoint which redirects to the actual download URL.
    Returns (file_bytes, filename).
    """
    site_id, drive_id = await _resolve_compliance_site()
    headers = await _get_headers()
    base = settings.graph_base_url

    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        # Get filename from metadata
        meta_resp = await client.get(
            f"{base}/drives/{drive_id}/items/{item_id}",
            headers=headers,
            params={"$select": "id,name"},
        )
        meta_resp.raise_for_status()
        filename = meta_resp.json().get("name", "document")

        # Download content via the /content endpoint
        # Graph API returns a 302 redirect to the actual CDN URL
        # follow_redirects=True handles this automatically
        content_resp = await client.get(
            f"{base}/drives/{drive_id}/items/{item_id}/content",
            headers=headers,
        )
        content_resp.raise_for_status()

    logger.info(
        f"Downloaded {filename} "
        f"({len(content_resp.content)} bytes) from SharePoint"
    )
    return content_resp.content, filename
    """
    Download a file from SharePoint by its drive item ID.
    Returns (file_bytes, filename).
    Used by the extraction endpoint when a SharePoint file is selected.

    Args:
        item_id: Graph API drive item ID

    Returns:
        Tuple of (raw file bytes, filename)
    """
    site_id, drive_id = await _resolve_compliance_site()
    headers = await _get_headers()
    base = settings.graph_base_url

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get item metadata to confirm name and get download URL
        meta_resp = await client.get(
            f"{base}/drives/{drive_id}/items/{item_id}",
            headers=headers,
            params={"$select": "id,name,@microsoft.graph.downloadUrl"},
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        filename = meta.get("name", "document")
        download_url = meta.get("@microsoft.graph.downloadUrl")

        if not download_url:
            raise GraphAPIError(404, f"No download URL for item {item_id}")

        # Download the actual file bytes
        # download_url is pre-authenticated — no auth header needed
        file_resp = await client.get(download_url)
        file_resp.raise_for_status()

    logger.info(f"Downloaded {filename} ({len(file_resp.content)} bytes) from SharePoint")
    return file_resp.content, filename