# =============================================================================
# tests/agents/test_extractor_degraded.py — extraction degraded signal (R3)
#
# A total LLM outage must NOT be reported as "0 controls" (silent success):
# run_extraction raises LLMUnavailable when the model is unreachable for every
# chunk, but returns [] (no raise) when the model genuinely returns nothing.
# =============================================================================

from unittest.mock import AsyncMock, patch

import pytest

import agents.extractor.ollama_client as oc
from agents.extractor.ollama_client import DocumentType
from agents.llm_client import LLMUnavailable


async def test_total_outage_raises_not_silent_zero():
    with patch("agents.extractor.ollama_client.llm_generate",
               new=AsyncMock(side_effect=LLMUnavailable("gateway down"))):
        with pytest.raises(LLMUnavailable):
            await oc.run_extraction("Some short policy text.", "DRG-X-POL-Y-01-26", DocumentType.POLICY)


async def test_empty_completion_returns_empty_list_no_raise():
    # Model reachable but found nothing → genuine 0, not a failure.
    with patch("agents.extractor.ollama_client.llm_generate", new=AsyncMock(return_value="")):
        result = await oc.run_extraction("Policy with no controls.", "DRG-X-POL-Y-01-26", DocumentType.POLICY)
    assert result == []


async def test_partial_outage_returns_successful_chunk():
    # Two chunks: first LLM-unavailable, second returns one control → partial OK.
    long_text = "\n\n".join("para " + "x" * 1000 for _ in range(120))  # forces >1 chunk
    good = '[{"s":"The CX Officer shall log all calls","r":"Unlogged calls","o":"CX Officer","c":"A.5"}]'
    # First chunk fails (LLM unavailable); all remaining chunks succeed (same
    # control → deduped to one). Plenty of `good` responses so the count of
    # chunks doesn't matter to the test.
    with patch("agents.extractor.ollama_client.llm_generate",
               new=AsyncMock(side_effect=[LLMUnavailable("blip")] + [good] * 30)):
        result = await oc.run_extraction(long_text, "DRG-X-POL-Y-01-26", DocumentType.POLICY)
    assert len(result) == 1
    assert result[0]["statement"].startswith("The CX Officer shall log")


async def test_reachable_but_zero_across_multiple_chunks_is_zero_not_failure():
    long_text = "\n\n".join("para " + "x" * 1000 for _ in range(120))
    with patch("agents.extractor.ollama_client.llm_generate", new=AsyncMock(return_value="[]")):
        result = await oc.run_extraction(long_text, "DRG-X-POL-Y-01-26", DocumentType.POLICY)
    assert result == []
