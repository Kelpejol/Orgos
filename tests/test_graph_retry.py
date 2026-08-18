# =============================================================================
# tests/test_graph_retry.py — _request transient-retry behaviour (R2)
#
# The safety-critical property: 429/503 are retried for ANY method (Graph
# rejected them, unprocessed), but 502/504/network/timeout are retried ONLY for
# idempotent reads — never for writes — so a write is never duplicated.
# =============================================================================

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

import graph.client as gc
from graph.exceptions import GraphRateLimitError, GraphServiceUnavailableError

BASE = "https://graph.microsoft.com/v1.0/probe"


@pytest.fixture(autouse=True)
async def _client():
    await gc.startup()
    # No real token acquisition, no real sleeping between retries.
    with patch("graph.client.get_graph_access_token", new=AsyncMock(return_value="tok")), \
         patch("graph.client.invalidate_token_cache", new=lambda: None), \
         patch("graph.client.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        yield sleep_mock
    await gc.shutdown()


async def test_get_retries_429_then_succeeds_and_honours_retry_after(_client):
    with respx.mock:
        route = respx.get(BASE).mock(side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {}}),
            httpx.Response(200, json={"ok": True}),
        ])
        result = await gc._request("GET", BASE, context="probe")
    assert result == {"ok": True}
    assert route.call_count == 2
    _client.assert_awaited()                       # slept between attempts
    assert _client.await_args.args[0] == 7.0       # honoured Retry-After header


async def test_post_IS_retried_on_503(_client):
    # 503 means "not processed" → safe to retry writes.
    with respx.mock:
        route = respx.post(BASE).mock(side_effect=[
            httpx.Response(503, json={"error": {}}),
            httpx.Response(201, json={"id": "1"}),
        ])
        result = await gc._request("POST", BASE, json={"x": 1}, context="probe")
    assert result == {"id": "1"}
    assert route.call_count == 2


async def test_post_NOT_retried_on_504(_client):
    # 504 is ambiguous for a write (may have been processed) → do NOT retry.
    with respx.mock:
        route = respx.post(BASE).mock(return_value=httpx.Response(504, json={"error": {}}))
        with pytest.raises(GraphServiceUnavailableError):
            await gc._request("POST", BASE, json={"x": 1}, context="probe")
    assert route.call_count == 1


async def test_post_NOT_retried_on_timeout(_client):
    # Network timeout on a write: outcome unknown → never retry (no double-write).
    with respx.mock:
        route = respx.post(BASE).mock(side_effect=httpx.ConnectTimeout("boom"))
        with pytest.raises(GraphServiceUnavailableError):
            await gc._request("POST", BASE, json={"x": 1}, context="probe")
    assert route.call_count == 1


async def test_get_retried_on_timeout(_client):
    with respx.mock:
        route = respx.get(BASE).mock(side_effect=[
            httpx.ReadTimeout("slow"),
            httpx.Response(200, json={"ok": 1}),
        ])
        result = await gc._request("GET", BASE, context="probe")
    assert result == {"ok": 1}
    assert route.call_count == 2


async def test_gives_up_after_max_attempts_and_raises_rate_limit(_client):
    # Persistent 429 → exhaust retries → GraphRateLimitError (429 mapped).
    with respx.mock:
        route = respx.get(BASE).mock(return_value=httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {}}))
        with pytest.raises(GraphRateLimitError):
            await gc._request("GET", BASE, context="probe")
    assert route.call_count == gc._MAX_ATTEMPTS


async def test_401_refreshes_once_then_succeeds_not_counted_as_retry(_client):
    with respx.mock:
        route = respx.get(BASE).mock(side_effect=[
            httpx.Response(401, json={"error": {}}),
            httpx.Response(200, json={"ok": 1}),
        ])
        result = await gc._request("GET", BASE, context="probe")
    assert result == {"ok": 1}
    assert route.call_count == 2


async def test_non_retryable_404_raises_immediately(_client):
    from graph.exceptions import GraphNotFoundError
    with respx.mock:
        route = respx.get(BASE).mock(return_value=httpx.Response(404, json={"error": {"message": "nope"}}))
        with pytest.raises(GraphNotFoundError):
            await gc._request("GET", BASE, context="probe")
    assert route.call_count == 1
