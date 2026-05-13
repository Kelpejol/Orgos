# # =============================================================================
# # graph/client.py — Microsoft Graph API async client
# # All SharePoint List CRUD operations go through this module.
# # No other module calls Graph API directly — they all call these functions.
# # Depends on: config.py, graph/auth.py, graph/exceptions.py, httpx
# # =============================================================================

# import logging
# from typing import Any, Optional

# import httpx

# from config import settings
# from graph.auth import get_graph_access_token, invalidate_token_cache
# from graph.exceptions import (
#     SharePointListNotConfiguredError,
#     raise_for_graph_status,
# )

# logger = logging.getLogger(__name__)

# # Shared async client — created at app startup, closed at shutdown
# # Use get_client() to access it — do not instantiate httpx.AsyncClient directly
# _client: Optional[httpx.AsyncClient] = None


# async def startup() -> None:
#     """Initialize the shared httpx.AsyncClient. Called from main.py lifespan."""
#     global _client
#     _client = httpx.AsyncClient(
#         timeout=httpx.Timeout(30.0, connect=10.0),
#         limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
#     )
#     logger.info("Graph API HTTP client initialized")


# async def shutdown() -> None:
#     """Close the shared httpx.AsyncClient. Called from main.py lifespan."""
#     global _client
#     if _client is not None:
#         await _client.aclose()
#         _client = None
#         logger.info("Graph API HTTP client closed")


# def get_client() -> httpx.AsyncClient:
#     """Return the shared httpx.AsyncClient. Raises if not initialized."""
#     if _client is None:
#         raise RuntimeError(
#             "Graph API client not initialized. "
#             "Ensure startup() is called in the FastAPI lifespan."
#         )
#     return _client


# async def _get_headers() -> dict:
#     """Build authorization headers for a Graph API request."""
#     token = await get_graph_access_token()
#     return {
#         "Authorization": f"Bearer {token}",
#         "Content-Type": "application/json",
#     }


# async def _request(
#     method: str,
#     url: str,
#     json: Optional[dict] = None,
#     params: Optional[dict] = None,
#     context: str = "",
#     retry_on_401: bool = True,
# ) -> Any:
#     """
#     Internal request handler with automatic 401 retry.
#     On a 401, invalidates the token cache and retries once with a fresh token.
#     """
#     headers = await _get_headers()
#     client = get_client()

#     response = await client.request(
#         method=method,
#         url=url,
#         headers=headers,
#         json=json,
#         params=params,
#     )

#     # On 401 — token may have expired between cache check and use
#     if response.status_code == 401 and retry_on_401:
#         logger.warning("Graph API returned 401 — refreshing token and retrying")
#         invalidate_token_cache()
#         headers = await _get_headers()
#         response = await client.request(
#             method=method,
#             url=url,
#             headers=headers,
#             json=json,
#             params=params,
#         )

#     if response.status_code not in (200, 201, 204):
#         body = {}
#         try:
#             body = response.json()
#         except Exception:
#             pass
#         logger.error(
#             f"Graph API error | {method} {url} | status={response.status_code} | {body}"
#         )
#         raise_for_graph_status(response.status_code, body, context)

#     if response.status_code == 204 or not response.content:
#         return None

#     return response.json()


# def _guard_list_configured(list_id: str, list_name: str) -> None:
#     """
#     Raise SharePointListNotConfiguredError if the list ID is still 'placeholder'.
#     Call this at the start of every function that uses a list ID.
#     """
#     if not settings.is_list_configured(list_id):
#         raise SharePointListNotConfiguredError(list_name)


# # =============================================================================
# #  SharePoint List operations
# # =============================================================================


# async def get_list_items(
#     list_id: str,
#     list_name: str,
#     odata_filter: Optional[str] = None,
#     select_fields: Optional[str] = None,
#     top: int = 500,
# ) -> list[dict]:
#     """
#     Retrieve all items from a SharePoint List.

#     Args:
#         list_id: SharePoint List GUID from .env
#         list_name: Human-readable name for error messages
#         odata_filter: OData $filter expression e.g. "fields/Status eq 'Active'"
#         select_fields: Comma-separated field names to return
#         top: Max items per page (SharePoint max is 5000, default 500 for safety)

#     Returns:
#         List of SharePoint item dicts. Each dict has 'id' and 'fields' keys.

#     Example fields response:
#         {"id": "1", "fields": {"Title": "...", "Status": "Active", ...}}
#     """
#     _guard_list_configured(list_id, list_name)

#     url = f"{settings.sharepoint_lists_base}/{list_id}/items"
#     params: dict = {"$expand": "fields", "$top": top}

#     if odata_filter:
#         params["$filter"] = odata_filter
#     if select_fields:
#         params["$select"] = f"id,{select_fields}"

#     all_items: list[dict] = []
#     next_link: Optional[str] = url

#     # Follow @odata.nextLink for pagination
#     while next_link:
#         if next_link == url:
#             data = await _request("GET", url, params=params, context=f"Get items from {list_name}")
#         else:
#             data = await _request("GET", next_link, context=f"Get items from {list_name} (page)")

#         all_items.extend(data.get("value", []))
#         next_link = data.get("@odata.nextLink")

#     logger.debug(f"Retrieved {len(all_items)} items from {list_name}")
#     return all_items


# async def get_list_item(list_id: str, list_name: str, item_id: str) -> dict:
#     """
#     Retrieve a single SharePoint List item by its ID.

#     Args:
#         list_id: SharePoint List GUID
#         list_name: Human-readable name for error messages
#         item_id: SharePoint item ID (integer as string)

#     Returns:
#         SharePoint item dict with 'id' and 'fields' keys.
#     """
#     _guard_list_configured(list_id, list_name)

#     url = f"{settings.sharepoint_lists_base}/{list_id}/items/{item_id}"
#     return await _request(
#         "GET",
#         url,
#         params={"$expand": "fields"},
#         context=f"Get item {item_id} from {list_name}",
#     )


# async def create_list_item(
#     list_id: str, list_name: str, fields: dict
# ) -> dict:
#     """
#     Create a new item in a SharePoint List.

#     Args:
#         list_id: SharePoint List GUID
#         list_name: Human-readable name for error messages
#         fields: Dict of field names to values. Must NOT include 'id'.

#     Person field format:
#         {"Owner@odata.type": "#Microsoft.Azure.Connectors.SharePoint.SPListExpandedUser",
#          "OwnerId": "entra-user-id"}

#     Returns:
#         The created SharePoint item dict with the new 'id' and 'fields'.
#     """
#     _guard_list_configured(list_id, list_name)

#     url = f"{settings.sharepoint_lists_base}/{list_id}/items"
#     body = {"fields": fields}

#     result = await _request("POST", url, json=body, context=f"Create item in {list_name}")
#     logger.info(f"Created item {result.get('id')} in {list_name}")
#     return result


# async def update_list_item(
#     list_id: str, list_name: str, item_id: str, fields: dict
# ) -> dict:
#     """
#     Update fields on an existing SharePoint List item.
#     Uses PATCH — only the provided fields are updated.

#     Args:
#         list_id: SharePoint List GUID
#         list_name: Human-readable name for error messages
#         item_id: SharePoint item ID
#         fields: Dict of field names to new values (partial update)

#     Returns:
#         The updated field values as returned by Graph API.
#     """
#     _guard_list_configured(list_id, list_name)

#     url = (
#         f"{settings.sharepoint_lists_base}/{list_id}/items/{item_id}/fields"
#     )
#     result = await _request(
#         "PATCH", url, json=fields, context=f"Update item {item_id} in {list_name}"
#     )
#     logger.info(f"Updated item {item_id} in {list_name}")
#     return result or {}


# async def soft_delete_list_item(
#     list_id: str, list_name: str, item_id: str
# ) -> None:
#     """
#     Soft-delete a SharePoint List item by setting Status = 'Withdrawn'.
#     OrgOS never hard-deletes register entries — audit trail must be preserved.

#     Args:
#         list_id: SharePoint List GUID
#         list_name: Human-readable name for error messages
#         item_id: SharePoint item ID to soft-delete
#     """
#     await update_list_item(
#         list_id,
#         list_name,
#         item_id,
#         {"Status": "Withdrawn"},
#     )
#     logger.info(f"Soft-deleted (Withdrawn) item {item_id} in {list_name}")


# async def check_graph_connectivity() -> dict:
#     """
#     Verify that the backend can reach the Microsoft Graph API.
#     Used by the /api/v1/health/graph endpoint.

#     Returns:
#         Dict with 'status' ('ok' or 'error') and 'detail' message.
#     """
#     try:
#         token = await get_graph_access_token()
#         # Lightweight call — just get the site metadata
#         url = f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
#         data = await _request("GET", url, context="Graph health check")
#         site_name = data.get("displayName", "unknown")
#         return {"status": "ok", "site": site_name, "token_acquired": True}
#     except Exception as exc:
#         return {"status": "error", "detail": str(exc)}
# # Simple in-memory cache — avoids repeated Graph API calls for the same person
# _user_cache: dict = {}


# async def resolve_user(entra_oid: str) -> dict:
#     """
#     Resolve an Entra ID OID to display name and email.
#     Calls GET /users/{oid} via Graph API.
#     Results are cached in memory for the lifetime of the process.

#     Args:
#         entra_oid: The Entra ID object ID of the user

#     Returns:
#         Dict with 'display_name' and 'email' keys.
#         Returns empty strings if resolution fails — never crashes.
#     """
#     if not entra_oid or entra_oid == "dev-bypass-oid":
#         return {"display_name": "Dev User", "email": "dev@dragnet.com.ng"}

#     if entra_oid in _user_cache:
#         return _user_cache[entra_oid]

#     try:
#         url = f"{settings.graph_base_url}/users/{entra_oid}"
#         data = await _request(
#             "GET",
#             url,
#             context=f"Resolve user {entra_oid}",
#         )
#         result = {
#             "display_name": data.get("displayName", ""),
#             "email": data.get("mail") or data.get("userPrincipalName", ""),
#         }
#         _user_cache[entra_oid] = result
#         return result
#     except Exception as exc:
#         logger.warning(f"Could not resolve user {entra_oid}: {exc}")
#         return {"display_name": "", "email": ""}
    
#     # Simple in-memory cache — avoids repeated Graph API calls for the same person
# _user_cache: dict = {}








# =============================================================================
# graph/client.py — Microsoft Graph API async client
# All SharePoint List CRUD operations go through this module.
# No other module calls Graph API directly — they all call these functions.
# Depends on: config.py, graph/auth.py, graph/exceptions.py, httpx
# =============================================================================

import logging
from typing import Any, Optional

import httpx

from config import settings
from graph.auth import get_graph_access_token, invalidate_token_cache
from graph.exceptions import (
    SharePointListNotConfiguredError,
    raise_for_graph_status,
)

logger = logging.getLogger(__name__)

# Shared async client — created at app startup, closed at shutdown
# Use get_client() to access it — do not instantiate httpx.AsyncClient directly
_client: Optional[httpx.AsyncClient] = None


async def startup() -> None:
    """Initialize the shared httpx.AsyncClient. Called from main.py lifespan."""
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    logger.info("Graph API HTTP client initialized")


async def shutdown() -> None:
    """Close the shared httpx.AsyncClient. Called from main.py lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Graph API HTTP client closed")


def get_client() -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient. Raises if not initialized."""
    if _client is None:
        raise RuntimeError(
            "Graph API client not initialized. "
            "Ensure startup() is called in the FastAPI lifespan."
        )
    return _client


async def _get_headers() -> dict:
    """Build authorization headers for a Graph API request."""
    token = await get_graph_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _request(
    method: str,
    url: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    context: str = "",
    retry_on_401: bool = True,
) -> Any:
    """
    Internal request handler with automatic 401 retry.
    On a 401, invalidates the token cache and retries once with a fresh token.
    """
    headers = await _get_headers()
    client = get_client()

    response = await client.request(
        method=method,
        url=url,
        headers=headers,
        json=json,
        params=params,
    )

    # On 401 — token may have expired between cache check and use
    if response.status_code == 401 and retry_on_401:
        logger.warning("Graph API returned 401 — refreshing token and retrying")
        invalidate_token_cache()
        headers = await _get_headers()
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=json,
            params=params,
        )

    if response.status_code not in (200, 201, 204):
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        logger.error(
            f"Graph API error | {method} {url} | status={response.status_code} | {body}"
        )
        raise_for_graph_status(response.status_code, body, context)

    if response.status_code == 204 or not response.content:
        return None

    return response.json()


def _guard_list_configured(list_id: str, list_name: str) -> None:
    """
    Raise SharePointListNotConfiguredError if the list ID is still 'placeholder'.
    Call this at the start of every function that uses a list ID.
    """
    if not settings.is_list_configured(list_id):
        raise SharePointListNotConfiguredError(list_name)


# =============================================================================
#  SharePoint List operations
# =============================================================================


async def get_list_items(
    list_id: str,
    list_name: str,
    odata_filter: Optional[str] = None,
    select_fields: Optional[str] = None,
    top: int = 500,
) -> list[dict]:
    """
    Retrieve all items from a SharePoint List.

    Args:
        list_id: SharePoint List GUID from .env
        list_name: Human-readable name for error messages
        odata_filter: OData $filter expression e.g. "fields/Status eq 'Active'"
        select_fields: Comma-separated field names to return
        top: Max items per page (SharePoint max is 5000, default 500 for safety)

    Returns:
        List of SharePoint item dicts. Each dict has 'id' and 'fields' keys.

    Example fields response:
        {"id": "1", "fields": {"Title": "...", "Status": "Active", ...}}
    """
    _guard_list_configured(list_id, list_name)

    url = f"{settings.sharepoint_lists_base}/{list_id}/items"
    params: dict = {"$expand": "fields", "$top": top}

    if odata_filter:
        params["$filter"] = odata_filter
    if select_fields:
        params["$select"] = f"id,{select_fields}"

    all_items: list[dict] = []
    next_link: Optional[str] = url

    # Follow @odata.nextLink for pagination
    while next_link:
        if next_link == url:
            data = await _request("GET", url, params=params, context=f"Get items from {list_name}")
        else:
            data = await _request("GET", next_link, context=f"Get items from {list_name} (page)")

        all_items.extend(data.get("value", []))
        next_link = data.get("@odata.nextLink")

    logger.debug(f"Retrieved {len(all_items)} items from {list_name}")
    return all_items


async def get_list_item(list_id: str, list_name: str, item_id: str) -> dict:
    """
    Retrieve a single SharePoint List item by its ID.

    Args:
        list_id: SharePoint List GUID
        list_name: Human-readable name for error messages
        item_id: SharePoint item ID (integer as string)

    Returns:
        SharePoint item dict with 'id' and 'fields' keys.
    """
    _guard_list_configured(list_id, list_name)

    url = f"{settings.sharepoint_lists_base}/{list_id}/items/{item_id}"
    return await _request(
        "GET",
        url,
        params={"$expand": "fields"},
        context=f"Get item {item_id} from {list_name}",
    )


async def create_list_item(
    list_id: str, list_name: str, fields: dict
) -> dict:
    """
    Create a new item in a SharePoint List.

    Args:
        list_id: SharePoint List GUID
        list_name: Human-readable name for error messages
        fields: Dict of field names to values. Must NOT include 'id'.

    Person field format:
        {"Owner@odata.type": "#Microsoft.Azure.Connectors.SharePoint.SPListExpandedUser",
         "OwnerId": "entra-user-id"}

    Returns:
        The created SharePoint item dict with the new 'id' and 'fields'.
    """
    _guard_list_configured(list_id, list_name)

    url = f"{settings.sharepoint_lists_base}/{list_id}/items"
    body = {"fields": fields}

    result = await _request("POST", url, json=body, context=f"Create item in {list_name}")
    logger.info(f"Created item {result.get('id')} in {list_name}")
    return result


async def update_list_item(
    list_id: str, list_name: str, item_id: str, fields: dict
) -> dict:
    """
    Update fields on an existing SharePoint List item.
    Uses PATCH — only the provided fields are updated.

    Args:
        list_id: SharePoint List GUID
        list_name: Human-readable name for error messages
        item_id: SharePoint item ID
        fields: Dict of field names to new values (partial update)

    Returns:
        The updated field values as returned by Graph API.
    """
    _guard_list_configured(list_id, list_name)

    url = (
        f"{settings.sharepoint_lists_base}/{list_id}/items/{item_id}/fields"
    )
    result = await _request(
        "PATCH", url, json=fields, context=f"Update item {item_id} in {list_name}"
    )
    logger.info(f"Updated item {item_id} in {list_name}")
    return result or {}


async def soft_delete_list_item(
    list_id: str, list_name: str, item_id: str
) -> None:
    """
    Soft-delete a SharePoint List item by setting Status = 'Withdrawn'.
    OrgOS never hard-deletes register entries — audit trail must be preserved.

    Args:
        list_id: SharePoint List GUID
        list_name: Human-readable name for error messages
        item_id: SharePoint item ID to soft-delete
    """
    await update_list_item(
        list_id,
        list_name,
        item_id,
        {"Status": "Withdrawn"},
    )
    logger.info(f"Soft-deleted (Withdrawn) item {item_id} in {list_name}")


async def check_graph_connectivity() -> dict:
    """
    Verify that the backend can reach the Microsoft Graph API.
    Used by the /api/v1/health/graph endpoint.

    Returns:
        Dict with 'status' ('ok' or 'error') and 'detail' message.
    """
    try:
        token = await get_graph_access_token()
        # Lightweight call — just get the site metadata
        url = f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        data = await _request("GET", url, context="Graph health check")
        site_name = data.get("displayName", "unknown")
        return {"status": "ok", "site": site_name, "token_acquired": True}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


# Simple in-memory cache — avoids repeated Graph API calls for the same person
_user_cache: dict = {}


async def resolve_user(entra_oid: str) -> dict:
    """
    Resolve an Entra ID OID to display name and email.
    Calls GET /users/{oid} via Graph API.
    Results are cached in memory for the lifetime of the process.

    Args:
        entra_oid: The Entra ID object ID of the user

    Returns:
        Dict with 'display_name' and 'email' keys.
        Returns empty strings if resolution fails — never crashes.
    """
    if not entra_oid or entra_oid == "dev-bypass-oid":
        return {"display_name": "Dev User", "email": "dev@dragnet.com.ng"}

    if entra_oid in _user_cache:
        return _user_cache[entra_oid]

    try:
        url = f"{settings.graph_base_url}/users/{entra_oid}"
        data = await _request(
            "GET",
            url,
            context=f"Resolve user {entra_oid}",
        )
        result = {
            "display_name": data.get("displayName", ""),
            "email": data.get("mail") or data.get("userPrincipalName", ""),
        }
        _user_cache[entra_oid] = result
        return result
    except Exception as exc:
        logger.warning(f"Could not resolve user {entra_oid}: {exc}")
        return {"display_name": "", "email": ""}


# =============================================================================
#  SharePoint Document Library — file upload / download
# =============================================================================

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


async def upload_file_to_sharepoint(
    file_bytes: bytes,
    filename: str,
    folder: str = "Document Lifecycle Drafts",
) -> str:
    """
    Upload a file to a SharePoint document library via the Graph API.

    Uses a simple PUT upload — suitable for files up to ~4 MB (covers all
    AI-generated .docx drafts). For larger files use the resumable upload
    session endpoint instead.

    Args:
        file_bytes: Raw file content as bytes.
        filename:   Target filename in SharePoint (e.g. "DRG-SD-POL-01-26.docx").
        folder:     Library-relative folder path. Defaults to
                    "Document Lifecycle Drafts". Must already exist in the
                    document library — Graph will return 404 if it doesn't.

    Returns:
        The SharePoint webUrl of the uploaded file (use as SharePointFileUrl
        in the lifecycle list entry so the frontend can open it directly).

    Raises:
        httpx.HTTPStatusError / graph exceptions on failure.

    Required config.py settings:
        sharepoint_site_id  — SharePoint site GUID or "hostname,siteId,webId"
        sharepoint_drive_id — Document library drive GUID
                              (find via GET /sites/{site}/drives)

    Example .env entries:
        SHAREPOINT_SITE_ID=your-site-id
        SHAREPOINT_DRIVE_ID=your-drive-id
    """
    token = await get_graph_access_token()
    client = get_client()

    # Graph PUT endpoint for small file upload:
    # PUT /sites/{site}/drives/{drive}/root:/{folder}/{filename}:/content
    url = (
        f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        f"/drives/{settings.sharepoint_drive_id}"
        f"/root:/{folder}/{filename}:/content"
    )

    response = await client.put(
        url,
        content=file_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": _DOCX_CONTENT_TYPE,
        },
    )

    # 201 Created (new file) or 200 OK (overwrite) are both success
    if response.status_code not in (200, 201):
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        logger.error(
            f"SharePoint upload failed | PUT {url} "
            f"| status={response.status_code} | {body}"
        )
        raise_for_graph_status(response.status_code, body, f"Upload {filename} to SharePoint")

    data = response.json()
    web_url = data.get("webUrl", "")
    logger.info(f"Uploaded '{filename}' to SharePoint folder '{folder}': {web_url}")
    return web_url


async def download_file_from_sharepoint(web_url: str) -> tuple[bytes, str]:
    """
    Download a file from SharePoint by its webUrl.

    This resolves the webUrl to a direct download stream via Graph API
    using the /shares/u! encoding trick — avoids needing to store the
    drive item ID separately.

    Args:
        web_url: The SharePoint webUrl returned by upload_file_to_sharepoint
                 or stored in the lifecycle list's SharePointFileUrl field.

    Returns:
        Tuple of (file_bytes, content_type). content_type is the MIME type
        reported by SharePoint (e.g. the .docx MIME type above).

    Raises:
        httpx.HTTPStatusError / graph exceptions on failure.
    """
    import base64

    token = await get_graph_access_token()
    client = get_client()

    # Encode the webUrl using the Graph /shares/u! trick:
    # base64url-encode the URL, strip padding, prefix with "u!"
    encoded = base64.urlsafe_b64encode(web_url.encode()).rstrip(b"=").decode()
    share_id = f"u!{encoded}"

    # Fetch the drive item metadata to get the @microsoft.graph.downloadUrl
    metadata_url = f"{settings.graph_base_url}/shares/{share_id}/driveItem"
    meta_resp = await client.get(
        metadata_url,
        headers={"Authorization": f"Bearer {token}"},
    )

    if meta_resp.status_code not in (200, 201):
        body = {}
        try:
            body = meta_resp.json()
        except Exception:
            pass
        raise_for_graph_status(
            meta_resp.status_code, body,
            f"Resolve SharePoint item for download: {web_url}",
        )

    meta = meta_resp.json()

    # @microsoft.graph.downloadUrl is a pre-authenticated URL — no token needed
    download_url = meta.get("@microsoft.graph.downloadUrl")
    if not download_url:
        raise ValueError(
            f"SharePoint item has no downloadUrl. "
            f"Check that the file exists and the app has Files.Read permission. "
            f"webUrl={web_url}"
        )

    file_resp = await client.get(download_url)
    file_resp.raise_for_status()

    content_type = file_resp.headers.get("Content-Type", _DOCX_CONTENT_TYPE)
    logger.info(
        f"Downloaded {len(file_resp.content):,} bytes from SharePoint: {web_url}"
    )
    return file_resp.content, content_type