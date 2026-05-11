# =============================================================================
# graph/exceptions.py — Graph API error types
# Custom exceptions for every error condition that can come from Microsoft Graph.
# Depends on: nothing (no internal imports — imported by everything else)
# =============================================================================

from typing import Optional


class GraphAPIError(Exception):
    """
    Base exception for all Microsoft Graph API errors.
    status_code mirrors the HTTP status returned by Graph.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        detail: Optional[dict] = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}
        super().__init__(message)


class GraphAuthError(GraphAPIError):
    """Raised when token acquisition fails or incoming token is rejected (401/403)."""

    def __init__(self, message: str = "Graph API authentication failed") -> None:
        super().__init__(401, message)


class GraphPermissionError(GraphAPIError):
    """Raised when the service account lacks permission for an operation (403)."""

    def __init__(self, message: str = "Graph API permission denied") -> None:
        super().__init__(403, message)


class GraphNotFoundError(GraphAPIError):
    """Raised when the requested SharePoint list item does not exist (404)."""

    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(404, f"Not found: {resource}")


class GraphRateLimitError(GraphAPIError):
    """Raised when Graph API returns 429 Too Many Requests."""

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__(
            429,
            f"Graph API rate limit exceeded. Retry after {retry_after}s.",
            {"retry_after": retry_after},
        )


class GraphServiceUnavailableError(GraphAPIError):
    """Raised when Graph API returns 503 or is unreachable."""

    def __init__(self, message: str = "Graph API is unavailable") -> None:
        super().__init__(503, message)


class SharePointListNotConfiguredError(GraphAPIError):
    """
    Raised when a required SharePoint List ID is still set to 'placeholder'.
    This is expected during development before lists are created.
    Returns 503 to frontend — not a code error, a configuration gap.
    """

    def __init__(self, list_name: str) -> None:
        super().__init__(
            503,
            (
                f"SharePoint list '{list_name}' is not configured. "
                "Set the List ID in .env after creating the list in SharePoint."
            ),
        )


def raise_for_graph_status(
    status_code: int, body: dict, context: str = ""
) -> None:
    """
    Inspect a Graph API response and raise the appropriate exception.
    Call this after every Graph API request that is not 200/201/204.

    Args:
        status_code: HTTP status code from Graph API response
        body: Parsed JSON response body
        context: Human-readable description of what was being attempted
    """
    error_block = body.get("error", {})
    message = error_block.get("message", "Unknown Graph API error")
    full_message = f"{context}: {message}" if context else message

    if status_code == 401:
        raise GraphAuthError(full_message)
    elif status_code == 403:
        raise GraphPermissionError(full_message)
    elif status_code == 404:
        raise GraphNotFoundError(context or message)
    elif status_code == 429:
        retry_after = int(body.get("retry-after", 60))
        raise GraphRateLimitError(retry_after)
    elif status_code >= 500:
        raise GraphServiceUnavailableError(full_message)
    else:
        raise GraphAPIError(status_code, full_message, error_block)
