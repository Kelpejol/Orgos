# =============================================================================
# agents/nl_search/memory_service.py — Mem0 conversation memory
#
# Provides persistent, cross-session memory for the NL Search chatbot.
# Uses the user's Entra OID as the memory key so facts persist across
# browser sessions and devices.
#
# Architecture:
#   - Custom LLM provider: sync httpx → gateway (production) → Ollama (dev)
#   - Custom Embedder: sync httpx → GPU endpoint (production) → Ollama (dev)
#   - Vector store: ChromaDB (existing ./chroma_db/, new collection "nl_search_memory")
#   - History DB: SQLite at {chroma_persist_dir}/mem0_history.db (Mem0 conflict resolution)
#
# Both providers follow the exact same fallback chain as the rest of the system:
#   CHAT_API_URL / EMBED_API_URL → Ollama
# No new env vars needed. No Ollama required in production as long as the
# gateway is configured.
#
# The sync providers run in a thread pool (run_in_executor) so they never
# block the FastAPI event loop.
#
# Public API:
#   get_context(user_oid, question, limit=5) → str   # call before search + classify
#   add_exchange(user_oid, question, answer)  → None  # call fire-and-forget after response
# =============================================================================

import asyncio
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


# =============================================================================
#  Custom synchronous LLM provider for Mem0
#  Routes: gateway (CHAT_API_URL) → Ollama fallback
# =============================================================================

class _OrgOSLLM:
    """
    Synchronous LLM provider that mirrors our llm_client.py gateway chain.
    Mem0 calls generate_response() from a thread pool — sync httpx is correct here.
    """

    def generate_response(
        self,
        messages: list[dict],
        response_format: Optional[dict] = None,
        tools=None,
        tool_choice=None,
    ) -> str:
        json_mode = isinstance(response_format, dict) and response_format.get("type") == "json_object"

        headers: dict[str, str] = {}
        if settings.inference_api_key:
            headers["Authorization"] = f"Bearer {settings.inference_api_key}"

        # ── Gateway (production) ─────────────────────────────────────────────
        if settings.chat_api_url:
            try:
                payload: dict = {
                    "messages": messages,
                    "max_tokens": 1000,
                    "temperature": 0.1,
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}

                with httpx.Client(timeout=30) as client:
                    resp = client.post(settings.chat_api_url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                # Handle gateway's {"output": "..."} shape and standard OpenAI shape
                choices = data.get("choices") or []
                if choices:
                    return str(choices[0].get("message", {}).get("content", "")).strip()
                return str(
                    data.get("output") or data.get("content") or data.get("text") or ""
                ).strip()

            except Exception as exc:
                logger.warning(f"Mem0 gateway LLM failed, falling back to Ollama: {exc}")

        # ── Ollama fallback (local dev) ──────────────────────────────────────
        try:
            # Flatten message list into a prompt string for Ollama /api/generate
            prompt_parts: list[str] = []
            for m in messages:
                role = m.get("role", "user").upper()
                content = m.get("content", "")
                if role == "SYSTEM":
                    prompt_parts.append(f"[SYSTEM]\n{content}")
                else:
                    prompt_parts.append(f"{role}: {content}")
            prompt = "\n\n".join(prompt_parts) + "\n\nASSISTANT:"

            payload = {
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            }
            if json_mode:
                payload["format"] = "json"

            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json().get("response", "").strip()

        except Exception as exc:
            logger.warning(f"Mem0 Ollama LLM fallback failed: {exc}")
            return ""


# =============================================================================
#  Custom synchronous embedder for Mem0
#  Routes: EMBED_API_URL → Ollama fallback
# =============================================================================

class _OrgOSEmbedder:
    """
    Synchronous embedder that mirrors our embedder.py GPU → Ollama chain.
    Mem0 calls embed() from a thread pool — sync httpx is correct here.
    """

    def embed(self, text: str) -> list[float]:
        headers: dict[str, str] = {}
        if settings.inference_api_key:
            headers["Authorization"] = f"Bearer {settings.inference_api_key}"

        # ── GPU endpoint (production) ────────────────────────────────────────
        if settings.embed_api_url:
            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.post(
                        settings.embed_api_url,
                        json={"text": text},   # API expects "text", not "input"
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                # Handle all response shapes (mirrors embedder.py logic)
                if isinstance(data, list):
                    embedding = data[0] if data and isinstance(data[0], list) else data
                else:
                    embedding = (
                        data.get("embedding")
                        or (data.get("embeddings") or [[]])[0]
                        or (data.get("data") or [{}])[0].get("embedding")
                        or []
                    )
                # Unwrap double-nested arrays [[float, ...]]
                if embedding and isinstance(embedding[0], list):
                    embedding = embedding[0]
                return embedding or []

            except Exception as exc:
                logger.warning(f"Mem0 GPU embed failed, falling back to Ollama: {exc}")

        # ── Ollama fallback (local dev) ──────────────────────────────────────
        try:
            embed_model = getattr(settings, "ollama_embed_model", "nomic-embed-text")
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{settings.ollama_base_url}/api/embeddings",
                    json={"model": embed_model, "prompt": text},
                )
                resp.raise_for_status()
                return resp.json().get("embedding", [])

        except Exception as exc:
            logger.warning(f"Mem0 Ollama embed fallback failed: {exc}")
            return []


# =============================================================================
#  Mem0 initialization — lazy singleton
# =============================================================================

_mem0_instance: Optional[object] = None  # type: Memory | None


def _build_mem0() -> Optional[object]:
    """
    Build the Mem0 Memory instance with our custom providers.
    Uses Ollama as the base config (safe to init without a live connection)
    then immediately overrides llm and embedding_model with our sync providers
    that route through the full gateway → Ollama chain.
    """
    try:
        from mem0 import Memory

        config: dict = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": settings.ollama_model,
                    "ollama_base_url": settings.ollama_base_url,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": getattr(settings, "ollama_embed_model", "nomic-embed-text"),
                    "ollama_base_url": settings.ollama_base_url,
                },
            },
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": "nl_search_memory",
                    "path": settings.chroma_persist_dir,
                },
            },
            # SQLite history DB for Mem0's AUDN conflict resolution cycle
            # Stored alongside ChromaDB so all persistence is in one place
            "history_db_path": f"{settings.chroma_persist_dir}/mem0_history.db",
            "version": "v1.1",
        }

        m = Memory.from_config(config)

        # Override with our providers — these are used for all subsequent
        # add() and search() calls regardless of the init config
        m.llm = _OrgOSLLM()
        m.embedding_model = _OrgOSEmbedder()

        logger.info("Mem0 memory service initialised (collection: nl_search_memory)")
        return m

    except ImportError:
        logger.warning("mem0ai not installed — memory features disabled. Run: pip install mem0ai")
        return None
    except Exception as exc:
        logger.error(f"Mem0 init failed: {exc}")
        return None


def _get_mem0() -> Optional[object]:
    global _mem0_instance
    if _mem0_instance is None:
        _mem0_instance = _build_mem0()
    return _mem0_instance


# =============================================================================
#  Sync helpers — run inside thread pool (never in the event loop directly)
# =============================================================================

def _sync_add(user_oid: str, question: str, answer: str) -> None:
    """Extract and store facts from one Q&A exchange. Runs in thread pool."""
    m = _get_mem0()
    if not m:
        return
    messages = [
        {"role": "user",      "content": question},
        {"role": "assistant", "content": answer[:800]},  # cap long answers
    ]
    m.add(messages, user_id=user_oid)


def _sync_search(user_oid: str, question: str, limit: int) -> str:
    """Search memory for facts relevant to the current question. Runs in thread pool."""
    m = _get_mem0()
    if not m:
        return ""
    results = m.search(question, user_id=user_oid, limit=limit)
    # Mem0 v1.1 wraps results as {"results": [...], "relations": [...]} instead of a plain list.
    # Iterating a dict gives string keys ("results", "relations") — calling .get() on a str crashes.
    if isinstance(results, dict):
        results = results.get("results") or []
    if not results:
        return ""
    facts = [r.get("memory") or r.get("text", "") for r in results if isinstance(r, dict) and (r.get("memory") or r.get("text"))]
    return "; ".join(f for f in facts if f)


# =============================================================================
#  Public async API
# =============================================================================

async def get_context(user_oid: str, question: str, limit: int = 5) -> str:
    """
    Retrieve relevant memory facts for a user, scoped to the current question.
    Returns a compact semicolon-separated fact string, or "" if nothing relevant.

    Called once per request in the router BEFORE classification and search,
    so the same context can be reused by both the classifier and the generator.

    Example return value:
      "User asked about IT change requests; prior answer discussed CAB reviews
       every Thursday and CISO sign-off for significant changes"
    """
    if not user_oid:
        return ""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_search, user_oid, question, limit)
    except Exception as exc:
        logger.warning(f"Mem0 get_context failed for {user_oid}: {exc}")
        return ""


async def add_exchange(user_oid: str, question: str, answer: str) -> None:
    """
    Extract facts from a completed Q&A exchange and store them in memory.

    ALWAYS called fire-and-forget (asyncio.create_task) after the response
    is sent — the user never waits for this.

    Mem0's AUDN cycle handles conflicts automatically:
      ADD   — new fact not seen before
      UPDATE — fact updates a previous one (e.g. policy changed)
      DELETE — new info contradicts and removes old fact
      NOOP  — already known, no change needed
    """
    if not user_oid or not question or not answer:
        return
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _sync_add, user_oid, question, answer)
    except Exception as exc:
        logger.warning(f"Mem0 add_exchange failed for {user_oid}: {exc}")
