# =============================================================================
# agents/nl_search/embedder.py — Text embedding service
#
# Provider routing (mirrors llm_client.py pattern):
#   LLM_PROVIDER=runpod  → BGE-M3 on RunPod (runpod_embed_endpoint_id)
#   LLM_PROVIDER=ollama  → nomic-embed-text via local Ollama
#
# BGE-M3 produces 1024-dim vectors. nomic-embed-text produces 768-dim vectors.
# ChromaDB handles both — dimensions are fixed per collection at creation time.
# Both collections specify their dimension explicitly to avoid silent mismatch.
# =============================================================================

import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_RUNPOD_BASE = "https://api.runpod.ai/v2"

# Dimension produced by each model — stored as collection metadata so the
# vector_store can validate on startup.
EMBED_DIM_BGE_M3 = 1024
EMBED_DIM_NOMIC = 768


def get_embed_dim() -> int:
    """Return the embedding dimension for the currently configured model."""
    if settings.llm_provider == "runpod" and settings.runpod_embed_endpoint_id:
        return EMBED_DIM_BGE_M3
    return EMBED_DIM_NOMIC


async def get_embedding(text: str) -> Optional[list[float]]:
    """
    Embed a single text string. Returns a float list, or None on failure.
    Caller must handle None gracefully — embedding failure must not crash
    the Zone 1 cascade or the extractor pipeline.
    """
    if not text or not text.strip():
        logger.warning("embed: empty text, skipping")
        return None

    if settings.llm_provider == "runpod" and settings.runpod_embed_endpoint_id:
        return await _runpod_embed(text)
    return await _ollama_embed(text)


async def get_embeddings_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """
    Embed a list of texts. Returns a list of the same length; failed items are None.
    Used by the index/rebuild endpoint to batch-embed existing controls.
    """
    results: list[Optional[list[float]]] = []
    for text in texts:
        vec = await get_embedding(text)
        results.append(vec)
    return results


# =============================================================================
#  RunPod BGE-M3 backend
# =============================================================================

async def _runpod_embed(text: str) -> Optional[list[float]]:
    """
    Call the RunPod BGE-M3 embedding endpoint.
    Expected response shape: {"output": [[float, ...]]}  (list of embeddings)
    or {"output": {"embeddings": [[float, ...]]}} depending on worker.
    """
    endpoint_id = settings.runpod_embed_endpoint_id
    url = f"{_RUNPOD_BASE}/{endpoint_id}/runsync"
    headers = {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type":  "application/json",
    }
    payload = {"input": {"texts": [text]}}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        ) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        output = data.get("output")
        if output is None:
            logger.warning(f"RunPod embed: no 'output' in response: {data}")
            return None

        # Shape 1: output = [[float, ...]]  (list of embedding vectors)
        if isinstance(output, list) and output and isinstance(output[0], list):
            return [float(v) for v in output[0]]

        # Shape 2: output = {"embeddings": [[float, ...]]}
        if isinstance(output, dict):
            embeddings = output.get("embeddings") or output.get("data")
            if embeddings and isinstance(embeddings[0], list):
                return [float(v) for v in embeddings[0]]
            # Shape 3: output = {"data": [{"embedding": [float, ...]}]} (OpenAI-compat)
            if embeddings and isinstance(embeddings[0], dict):
                return [float(v) for v in embeddings[0].get("embedding", [])]

        # Shape 4: output = [float, ...]  (flat vector directly)
        if isinstance(output, list) and output and isinstance(output[0], (int, float)):
            return [float(v) for v in output]

        logger.warning(f"RunPod embed: unrecognised output shape: {type(output)}")
        return None

    except Exception as exc:
        logger.warning(f"RunPod embed failed: {exc}")
        return None


# =============================================================================
#  Ollama nomic-embed-text backend
# =============================================================================

async def _ollama_embed(text: str) -> Optional[list[float]]:
    """
    Call Ollama /api/embeddings with nomic-embed-text (or configured embed model).
    Response shape: {"embedding": [float, ...]}
    """
    payload = {
        "model": settings.ollama_embed_model,
        "prompt": text,
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        ) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        embedding = data.get("embedding")
        if not embedding or not isinstance(embedding, list):
            logger.warning(f"Ollama embed: unexpected response shape: {data}")
            return None
        return [float(v) for v in embedding]

    except Exception as exc:
        logger.warning(f"Ollama embed failed: {exc}")
        return None


async def check_embed_connectivity() -> dict:
    """Health check for the embedding service."""
    test_vec = await get_embedding("test connectivity")
    if test_vec:
        provider = "runpod" if (
            settings.llm_provider == "runpod" and settings.runpod_embed_endpoint_id
        ) else "ollama"
        return {
            "status":    "ok",
            "provider":  provider,
            "model":     "bge-m3" if provider == "runpod" else settings.ollama_embed_model,
            "dimension": len(test_vec),
        }
    return {
        "status":  "error",
        "detail":  "Embedding test failed — check RunPod endpoint ID or Ollama model availability",
    }
