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

import asyncio
import logging
import random
import time
from typing import Any, Optional

import httpx

from config import settings
from graph.auth import get_graph_access_token, invalidate_token_cache
from graph.exceptions import (
    GraphServiceUnavailableError,
    SharePointListNotConfiguredError,
    raise_for_graph_status,
)

logger = logging.getLogger(__name__)

# ── Transient-failure retry policy ───────────────────────────────────────────
# 429/503 mean Graph REJECTED the request (it was not processed), so they are
# safe to retry for ANY method. 502/504 and network/timeout errors are
# AMBIGUOUS for writes (the write may have reached SharePoint), so we retry them
# only for idempotent reads — never for POST/PATCH/PUT/DELETE — to avoid
# duplicate writes.
_RETRY_ANY_METHOD_STATUSES = frozenset({429, 503})
_RETRY_IDEMPOTENT_STATUSES = frozenset({502, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_MAX_ATTEMPTS = 4          # 1 initial + 3 retries
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 20.0


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter for retry `attempt` (1-based)."""
    base = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    return base + random.uniform(0, base * 0.25)


def _parse_retry_after(headers) -> Optional[float]:
    """Read the Retry-After HEADER (integer seconds) if present and numeric."""
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None  # HTTP-date form is not used by Graph; ignore

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
    extra_headers: Optional[dict] = None,
) -> Any:
    """
    Internal request handler with:
      • one 401 refresh-and-retry (inline, does not consume a transient attempt);
      • bounded exponential-backoff retry on transient failures —
        429/503 for any method, and 502/504/network/timeout for reads only
        (writes are never retried on ambiguous errors, to avoid double-writes);
      • Retry-After header honoured for the wait between attempts.
    """
    client = get_client()
    method_up = method.upper()
    idempotent = method_up in _IDEMPOTENT_METHODS
    last_transport_exc: Optional[Exception] = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        headers = await _get_headers()
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = await client.request(
                method=method, url=url, headers=headers, json=json, params=params
            )
            # 401 — token may have expired mid-flight. Refresh once, re-issue
            # immediately in this same attempt (not counted as a transient retry).
            if response.status_code == 401 and retry_on_401:
                logger.warning("Graph API returned 401 — refreshing token and retrying once")
                invalidate_token_cache()
                headers = await _get_headers()
                if extra_headers:
                    headers.update(extra_headers)
                response = await client.request(
                    method=method, url=url, headers=headers, json=json, params=params
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Network-level failure — outcome unknown. Retry reads only.
            last_transport_exc = exc
            if idempotent and attempt < _MAX_ATTEMPTS:
                delay = _backoff_seconds(attempt)
                logger.warning(
                    f"Graph transport error | {method} {url} | "
                    f"retry {attempt}/{_MAX_ATTEMPTS - 1} in {delay:.1f}s | {exc}"
                )
                await asyncio.sleep(delay)
                continue
            logger.error(f"Graph transport error (no retry) | {method} {url} | {exc}")
            raise GraphServiceUnavailableError(f"{context}: {exc}") from exc

        status = response.status_code

        # Success
        if status in (200, 201, 204):
            if status == 204 or not response.content:
                return None
            return response.json()

        # Transient? 429/503 any method; 502/504 reads only.
        retryable = status in _RETRY_ANY_METHOD_STATUSES or (
            idempotent and status in _RETRY_IDEMPOTENT_STATUSES
        )
        if retryable and attempt < _MAX_ATTEMPTS:
            retry_after = _parse_retry_after(response.headers)
            delay = min(
                retry_after if retry_after is not None else _backoff_seconds(attempt),
                _BACKOFF_MAX_SECONDS,
            )
            logger.warning(
                f"Graph API {status} | {method} {url} | "
                f"retry {attempt}/{_MAX_ATTEMPTS - 1} in {delay:.1f}s"
            )
            await asyncio.sleep(delay)
            continue

        # Non-retryable, or retries exhausted → raise the mapped error.
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        logger.error(f"Graph API error | {method} {url} | status={status} | {body}")
        raise_for_graph_status(
            status, body, context, retry_after=_parse_retry_after(response.headers)
        )

    # Loop exhausted (only reachable if every attempt was a retried transport error).
    if last_transport_exc is not None:
        raise GraphServiceUnavailableError(f"{context}: {last_transport_exc}") from last_transport_exc
    raise GraphServiceUnavailableError(
        f"{context}: exhausted {_MAX_ATTEMPTS} attempts"
    )


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


# org_roles changes more often than name/email (a role change should show up
# without a process restart), so the cache here uses a short TTL rather than
# being indefinite.
_USER_CACHE_TTL = 300.0  # 5 minutes


async def resolve_user(entra_oid: str) -> dict:
    """
    Resolve an Entra ID OID to display name, email, and org_roles in a single
    Graph call. org_roles is read from onPremisesExtensionAttributes.
    extensionAttribute1 — the same attribute the Dragnet ERP writes to on
    every role change (see ERP_Backend_Architecture.md's graphRoles.service.ts,
    which calls this "quick lookup"). Comma-separated, lowercase-normalised.
    OrgOS never assigns org_roles itself — this is read-only, for display.
    Results are cached in memory for a few minutes per process.

    Args:
        entra_oid: The Entra ID object ID of the user

    Returns:
        Dict with 'display_name', 'email', and 'org_roles' keys.
        Returns empty values if resolution fails — never crashes.
    """
    if not entra_oid or entra_oid == "dev-bypass-oid":
        return {"display_name": "Dev User", "email": "dev@dragnet.com.ng", "org_roles": []}

    now = time.time()
    cached = _user_cache.get(entra_oid)
    if cached and now - cached["fetched_at"] < _USER_CACHE_TTL:
        return cached

    try:
        url = f"{settings.graph_base_url}/users/{entra_oid}"
        data = await _request(
            "GET",
            url,
            params={"$select": "displayName,mail,userPrincipalName,onPremisesExtensionAttributes"},
            context=f"Resolve user {entra_oid}",
        )
        raw_roles = (data.get("onPremisesExtensionAttributes") or {}).get("extensionAttribute1") or ""
        result = {
            "display_name": data.get("displayName", ""),
            "email": data.get("mail") or data.get("userPrincipalName", ""),
            "org_roles": [r.strip().lower() for r in raw_roles.split(",") if r.strip()],
            "fetched_at": now,
        }
        _user_cache[entra_oid] = result
        return result
    except Exception as exc:
        logger.warning(f"Could not resolve user {entra_oid}: {exc}")
        return {"display_name": "", "email": "", "org_roles": []}


async def list_users_with_org_roles() -> list[dict]:
    """
    Lists every Entra ID user who has at least one org_role assigned, read
    live from onPremisesExtensionAttributes.extensionAttribute1 — the same
    attribute the Dragnet ERP writes to on every role change (see
    ERP_Backend_Architecture.md's graphRoles.service.ts). OrgOS never
    assigns org_roles itself — this is read-only, for display.

    Filtering on a directory extension attribute is an "advanced query" in
    Graph and requires ConsistencyLevel: eventual plus $count=true.
    """
    results: list[dict] = []
    url = f"{settings.graph_base_url}/users"
    params: Optional[dict] = {
        "$select": "id,displayName,mail,userPrincipalName,jobTitle,department,onPremisesExtensionAttributes",
        "$filter": "onPremisesExtensionAttributes/extensionAttribute1 ne null",
        "$count": "true",
        "$top": "999",
    }
    try:
        while url:
            data = await _request(
                "GET", url, params=params,
                extra_headers={"ConsistencyLevel": "eventual"},
                context="List users with org_roles",
            )
            if not data:
                break
            for u in data.get("value", []):
                raw = (u.get("onPremisesExtensionAttributes") or {}).get("extensionAttribute1") or ""
                roles = [r.strip().lower() for r in raw.split(",") if r.strip()]
                if not roles:
                    continue
                results.append({
                    "oid": u.get("id", ""),
                    "display_name": u.get("displayName", ""),
                    "email": u.get("mail") or u.get("userPrincipalName", ""),
                    "job_title": u.get("jobTitle") or "",
                    "department": u.get("department") or "",
                    "org_roles": roles,
                })
            url = data.get("@odata.nextLink")
            params = None  # nextLink already carries the query string
    except Exception as exc:
        logger.warning(f"Could not list users with org_roles: {exc}")
    return results


# Distinct job titles across the tenant — the canonical role vocabulary used for
# control ownership (extraction) and CDI role checks. Cached in-process (job
# titles change rarely); refreshed hourly.
_job_titles_cache: dict = {"titles": None, "expires_at": 0.0}


async def list_all_job_titles(force: bool = False) -> list[str]:
    """
    Every distinct, non-empty job title held by an enabled Entra user, sorted.
    This is the single source of truth for the role a control can be owned by.
    Cached for one hour; on a Graph failure the last good list is reused.
    """
    import time
    now = time.time()
    cached = _job_titles_cache.get("titles")
    if not force and cached is not None and now < _job_titles_cache.get("expires_at", 0):
        return cached

    titles: set[str] = set()
    url = f"{settings.graph_base_url}/users"
    params: Optional[dict] = {
        "$select": "jobTitle",
        "$filter": "accountEnabled eq true and jobTitle ne null",
        "$count": "true",
        "$top": "999",
    }
    try:
        while url:
            data = await _request(
                "GET", url, params=params,
                extra_headers={"ConsistencyLevel": "eventual"},
                context="List all job titles",
            )
            if not data:
                break
            for u in data.get("value", []):
                t = (u.get("jobTitle") or "").strip()
                if t:
                    titles.add(t)
            url = data.get("@odata.nextLink")
            params = None
    except Exception as exc:
        logger.warning(f"Could not list job titles: {exc}")
        if cached is not None:
            return cached
        return []

    # Collapse case-only duplicates (e.g. "Graphic Designer" vs "GRAPHIC
    # DESIGNER"), preferring a mixed-case variant over an all-caps/all-lower one.
    best: dict[str, str] = {}
    for t in titles:
        key = t.lower()
        cur = best.get(key)
        if cur is None:
            best[key] = t
        elif (cur == cur.upper() or cur == cur.lower()) and not (t == t.upper() or t == t.lower()):
            best[key] = t
    result = sorted(best.values(), key=str.lower)
    _job_titles_cache["titles"] = result
    _job_titles_cache["expires_at"] = now + 3600
    return result


# Simple in-memory cache for SP user lookup IDs (email → int)
_sp_user_id_cache: dict = {}


async def resolve_sp_user_lookup_id(email: str) -> Optional[int]:
    """
    Resolve a user's email address to their SharePoint site user lookup ID.

    SharePoint Person/Group columns (written via Graph API) require the
    internal SP site user ID (an integer, not the Entra OID).  This ID is
    retrieved from the hidden "User Information List" that every SharePoint
    site maintains.

    The result is cached in memory for the lifetime of the process.

    Args:
        email: The user's email / UPN (e.g. "daniel@dragnetsolutions.com").

    Returns:
        Integer SP user lookup ID if found, None otherwise.
        None means the Person/Group field write will be skipped gracefully —
        the text column (EntraId) is still written and application logic is
        unaffected.
    """
    if not email:
        return None

    if email in _sp_user_id_cache:
        return _sp_user_id_cache[email]

    try:
        # The User Information List is a hidden SP list present on every site.
        # Filter by the EMail field to find this user's record; the list item
        # id is the SP user lookup ID used for Person/Group column writes.
        url = (
            f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
            f"/lists/User%20Information%20List/items"
            f"?$filter=fields/EMail eq '{email}'&$select=id&$top=1"
            f"&$expand=fields($select=EMail)"
        )
        data = await _request("GET", url, context=f"Resolve SP user lookup ID for {email}")
        items = data.get("value", [])
        if items:
            lookup_id = int(items[0]["id"])
            _sp_user_id_cache[email] = lookup_id
            return lookup_id
    except Exception as exc:
        logger.warning(f"Could not resolve SP user lookup ID for '{email}': {exc}")

    return None


# =============================================================================
#  SharePoint Document Library — file upload / download
# =============================================================================

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


# =============================================================================
#  Compliance library (ORGOS LIBRARY) drive resolution + drive-based file I/O
#
#  The controlled-document library ("ORGOS LIBRARY") lives on the COMPLIANCE
#  site (settings.compliance_site_url — e.g. /sites/everybody), NOT the main
#  OrgOS site. Its drive GUID is resolved dynamically by library name so we
#  never hard-code a fragile GUID and never point at the wrong site.
#
#  This is the single source of truth for that resolution. It was previously
#  duplicated across scripts/ (intake, migrate, count). New CDT file I/O
#  (master templates, source docs, published copies) builds on these helpers.
# =============================================================================

# Resolved (site_id, drive_id) cached for the process lifetime — the drive
# GUID is stable, so we resolve once and reuse.
_compliance_drive_cache: Optional[tuple[str, str]] = None


async def resolve_compliance_drive() -> tuple[str, str]:
    """
    Resolve (site_id, drive_id) for the ORGOS LIBRARY document library on the
    compliance site. Cached per process.

    Returns:
        (site_id, drive_id) — both Graph IDs. Use drive_id for all
        /drives/{drive_id}/root:/... file operations.

    Raises:
        RuntimeError if no drive matching settings.compliance_library_name is
        found on the compliance site (lists the available drives to aid debugging).
    """
    global _compliance_drive_cache
    if _compliance_drive_cache is not None:
        return _compliance_drive_cache

    base = settings.graph_base_url
    url = settings.compliance_site_url.rstrip("/")
    parts = url.replace("https://", "").split("/", 1)
    hostname = parts[0]
    path = parts[1] if len(parts) > 1 else ""

    site = await _request(
        "GET", f"{base}/sites/{hostname}:/{path}", context="Resolve compliance site"
    )
    site_id = site["id"]

    drives = await _request(
        "GET", f"{base}/sites/{site_id}/drives", context="List compliance drives"
    )
    drive_list = drives.get("value", [])
    drive_id = next(
        (d["id"] for d in drive_list if d.get("name") == settings.compliance_library_name),
        None,
    )
    if not drive_id:
        available = [d.get("name") for d in drive_list]
        raise RuntimeError(
            f"Drive '{settings.compliance_library_name}' not found on "
            f"{settings.compliance_site_url}. Available drives: {available}"
        )

    _compliance_drive_cache = (site_id, drive_id)
    logger.info(
        f"Resolved compliance library drive: "
        f"'{settings.compliance_library_name}' -> {drive_id}"
    )
    return _compliance_drive_cache


async def ensure_drive_folder(drive_id: str, folder_path: str) -> str:
    """
    Ensure a (possibly nested) folder path exists under a drive root, creating
    any missing segments. Idempotent. Returns the deepest folder's item ID.

    SharePoint PUT-to-path does not reliably create missing parent folders, so
    publish/source paths call this first. Safe to call repeatedly.
    """
    client = get_client()
    parent_ref = "root"  # first segment is created under the drive root
    deepest_id = ""
    for segment in [s for s in folder_path.strip("/").split("/") if s]:
        headers = await _get_headers()
        # Try to fetch the child folder by name under the current parent.
        if parent_ref == "root":
            list_url = f"{settings.graph_base_url}/drives/{drive_id}/root/children"
            create_url = f"{settings.graph_base_url}/drives/{drive_id}/root/children"
        else:
            list_url = f"{settings.graph_base_url}/drives/{drive_id}/items/{parent_ref}/children"
            create_url = f"{settings.graph_base_url}/drives/{drive_id}/items/{parent_ref}/children"

        existing = await client.get(
            list_url, headers=headers, params={"$select": "id,name,folder", "$top": 200}
        )
        existing.raise_for_status()
        match = next(
            (
                c
                for c in existing.json().get("value", [])
                if c.get("name") == segment and "folder" in c
            ),
            None,
        )
        if match:
            parent_ref = match["id"]
            deepest_id = match["id"]
            continue

        created = await client.post(
            create_url,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "name": segment,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            },
        )
        # 201 = created; 409 = someone created it between our GET and POST (race) —
        # re-fetch and continue rather than error.
        if created.status_code == 409:
            existing = await client.get(
                list_url, headers=headers, params={"$select": "id,name,folder", "$top": 200}
            )
            existing.raise_for_status()
            match = next(
                (c for c in existing.json().get("value", []) if c.get("name") == segment),
                None,
            )
            if not match:
                raise RuntimeError(f"Could not create or find folder segment '{segment}'")
            parent_ref = match["id"]
            deepest_id = match["id"]
            continue
        if created.status_code not in (200, 201):
            body = {}
            try:
                body = created.json()
            except Exception:
                pass
            raise_for_graph_status(
                created.status_code, body, f"Create folder '{segment}' in drive {drive_id}"
            )
        item = created.json()
        parent_ref = item["id"]
        deepest_id = item["id"]

    return deepest_id


async def upload_bytes_to_drive(
    drive_id: str,
    folder: str,
    filename: str,
    file_bytes: bytes,
    content_type: str = _DOCX_CONTENT_TYPE,
) -> dict:
    """
    PUT a small file (<4 MB) to a path under a drive root. Returns the created
    driveItem dict (contains 'id' and 'webUrl').

    The caller is responsible for ensuring the folder exists (call
    ensure_drive_folder first for nested/new paths).
    """
    token = await get_graph_access_token()
    client = get_client()

    safe_folder = folder.strip("/")
    path = f"{safe_folder}/{filename}" if safe_folder else filename
    url = f"{settings.graph_base_url}/drives/{drive_id}/root:/{path}:/content"

    response = await client.put(
        url,
        content=file_bytes,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
    )
    if response.status_code not in (200, 201):
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        logger.error(
            f"Drive upload failed | PUT {url} | status={response.status_code} | {body}"
        )
        raise_for_graph_status(
            response.status_code, body, f"Upload {filename} to drive {drive_id}"
        )
    return response.json()


async def download_drive_item_by_path(drive_id: str, path: str) -> bytes:
    """
    Download a file's bytes from a drive by its root-relative path
    (e.g. "Templates/Procedure.docx"). Complements upload_bytes_to_drive.

    Raises the appropriate graph exception (e.g. GraphNotFoundError) if the
    path does not exist.
    """
    token = await get_graph_access_token()
    client = get_client()

    safe_path = path.strip("/")
    url = f"{settings.graph_base_url}/drives/{drive_id}/root:/{safe_path}:/content"
    # follow_redirects: Graph returns a 302 to a pre-authenticated download URL
    response = await client.get(
        url, headers={"Authorization": f"Bearer {token}"}, follow_redirects=True
    )
    if response.status_code != 200:
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        raise_for_graph_status(
            response.status_code, body, f"Download '{path}' from drive {drive_id}"
        )
    return response.content


async def convert_drive_item_to_pdf(drive_id: str, path: str) -> bytes:
    """
    Return a drive item as a PDF, using Microsoft Graph's native format
    conversion (?format=pdf) — no local converter (LibreOffice/docx2pdf)
    needed. Verified against the ORGOS LIBRARY: 200, valid %PDF- magic bytes.

    `path` is the root-relative path of an item that ALREADY EXISTS in the
    drive — Graph's conversion only works on a real driveItem, not raw bytes,
    so a caller with in-memory bytes (e.g. a fresh merge()) must upload them
    first (see upload_bytes_to_drive) and pass that path here.
    """
    token = await get_graph_access_token()
    client = get_client()

    safe_path = path.strip("/")
    url = f"{settings.graph_base_url}/drives/{drive_id}/root:/{safe_path}:/content"
    response = await client.get(
        url, headers={"Authorization": f"Bearer {token}"},
        params={"format": "pdf"}, follow_redirects=True,
    )
    if response.status_code != 200:
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        raise_for_graph_status(
            response.status_code, body, f"Convert '{path}' to PDF in drive {drive_id}"
        )
    return response.content


async def upload_file_to_sharepoint(
    file_bytes: bytes,
    filename: str,
    folder: str = "Document Lifecycle Drafts",
) -> str:
    """
    Upload a small file to the ORGOS LIBRARY (compliance) document library and
    return its webUrl.

    Thin convenience wrapper over resolve_compliance_drive + upload_bytes_to_drive.
    Previously referenced an undefined settings.sharepoint_drive_id on the wrong
    site; now resolves the correct compliance-library drive dynamically.

    Args:
        file_bytes: Raw file content as bytes.
        filename:   Target filename (e.g. "DRG-CAE-PRO-3CX-01-26.docx").
        folder:     Library-relative folder path. Must exist, or pass a path
                    you have pre-created with ensure_drive_folder.

    Returns:
        The SharePoint webUrl of the uploaded file.
    """
    _, drive_id = await resolve_compliance_drive()
    item = await upload_bytes_to_drive(drive_id, folder, filename, file_bytes)
    web_url = item.get("webUrl", "")
    logger.info(f"Uploaded '{filename}' to ORGOS LIBRARY folder '{folder}': {web_url}")
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
