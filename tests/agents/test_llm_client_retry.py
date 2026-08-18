# =============================================================================
# tests/agents/test_llm_client_retry.py — LLM client resilience (R1)
#
# Verifies: transient errors are retried; a hard failure returns "" by default
# (back-compat) but raises LLMUnavailable when raise_on_failure=True; a genuine
# empty completion returns "" (never raises); Retry-After honoured.
# =============================================================================

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

import agents.llm_client as llm
from agents.llm_client import LLMUnavailable, llm_generate

CHAT_URL = "https://gpu.example.test/chat"


@pytest.fixture(autouse=True)
def _gateway_env():
    # Force the gateway backend and make sleeps instant.
    with patch.object(llm.settings, "chat_api_url", CHAT_URL), \
         patch.object(llm.settings, "inference_api_key", "k"), \
         patch("agents.llm_client.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        yield sleep_mock


def _ok(text="hello"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


async def test_success_returns_text():
    with respx.mock:
        respx.post(CHAT_URL).mock(return_value=_ok("hi"))
        assert await llm_generate("p") == "hi"


async def test_retries_transient_then_succeeds(_gateway_env):
    with respx.mock:
        route = respx.post(CHAT_URL).mock(side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}, json={}),
            httpx.Response(503, json={}),
            _ok("recovered"),
        ])
        result = await llm_generate("p")
    assert result == "recovered"
    assert route.call_count == 3
    assert _gateway_env.await_args_list[0].args[0] == 3.0   # honoured Retry-After


async def test_hard_failure_returns_empty_by_default():
    with respx.mock:
        respx.post(CHAT_URL).mock(return_value=httpx.Response(503, json={}))
        result = await llm_generate("p")          # default raise_on_failure=False
    assert result == ""                            # back-compat: silent empty


async def test_hard_failure_raises_when_opted_in():
    with respx.mock:
        respx.post(CHAT_URL).mock(return_value=httpx.Response(503, json={}))
        with pytest.raises(LLMUnavailable):
            await llm_generate("p", raise_on_failure=True)


async def test_timeout_is_retried_then_raises_when_opted_in():
    with respx.mock:
        route = respx.post(CHAT_URL).mock(side_effect=httpx.ConnectTimeout("t"))
        with pytest.raises(LLMUnavailable):
            await llm_generate("p", raise_on_failure=True)
    assert route.call_count == llm._LLM_MAX_ATTEMPTS   # retried, then gave up


async def test_genuine_empty_completion_returns_empty_never_raises():
    # 200 OK with an empty content string is a real (empty) answer, not a failure.
    with respx.mock:
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}))
        assert await llm_generate("p", raise_on_failure=True) == ""


async def test_non_json_200_is_treated_as_unavailable():
    with respx.mock:
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text="<html>not json</html>"))
        with pytest.raises(LLMUnavailable):
            await llm_generate("p", raise_on_failure=True)
        # default still swallows to ""
        assert await llm_generate("p") == ""
