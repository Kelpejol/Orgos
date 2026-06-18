# =============================================================================
# agents/nl_search/vector_store.py — ChromaDB vector store wrapper
#
# Two collections:
#   controls_v1    — embeddings of accepted control statements (Control Register)
#   procedures_v1  — embeddings of procedural step text (Procedural Steps Index)
#
# ChromaDB is file-based (./chroma_db/) — no separate server required.
# Collections are created on first access with explicit embedding dimensions
# to prevent silent dimension mismatches when switching embed providers.
#
# All public functions are async-friendly — ChromaDB calls are synchronous
# but fast (in-process), so they do not block the event loop meaningfully.
# =============================================================================

import logging
from typing import Optional

from config import settings
from agents.nl_search.embedder import get_embedding, get_embed_dim

logger = logging.getLogger(__name__)

_COLLECTION_CONTROLS   = "controls_v1"
_COLLECTION_PROCEDURES = "procedures_v1"

_chroma_client = None
_col_controls   = None
_col_procedures = None


def _get_client():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        logger.info(f"ChromaDB initialised at {settings.chroma_persist_dir}")
    return _chroma_client


def _get_controls_collection():
    global _col_controls
    if _col_controls is None:
        client = _get_client()
        _col_controls = client.get_or_create_collection(
            name=_COLLECTION_CONTROLS,
            metadata={"hnsw:space": "cosine", "embed_dim": get_embed_dim()},
        )
        logger.info(
            f"Collection '{_COLLECTION_CONTROLS}' ready "
            f"({_col_controls.count()} documents)"
        )
    return _col_controls


def _get_procedures_collection():
    global _col_procedures
    if _col_procedures is None:
        client = _get_client()
        _col_procedures = client.get_or_create_collection(
            name=_COLLECTION_PROCEDURES,
            metadata={"hnsw:space": "cosine", "embed_dim": get_embed_dim()},
        )
        logger.info(
            f"Collection '{_COLLECTION_PROCEDURES}' ready "
            f"({_col_procedures.count()} documents)"
        )
    return _col_procedures


# =============================================================================
#  Controls index
# =============================================================================

async def embed_and_store_control(
    control_id: str,
    control_statement: str,
    metadata: dict,
) -> bool:
    """
    Embed a control statement and upsert it into controls_v1.
    Returns True on success. Fails soft — never raises.
    Called from Zone 1 accept cascade after a control is written to the Control Register.
    """
    try:
        vec = await get_embedding(control_statement)
        if vec is None:
            logger.warning(f"embed_and_store_control: embedding failed for control {control_id}")
            return False

        col = _get_controls_collection()
        safe_meta = {k: str(v) for k, v in (metadata or {}).items() if v is not None}
        col.upsert(
            ids=[control_id],
            embeddings=[vec],
            documents=[control_statement],
            metadatas=[safe_meta],
        )
        logger.debug(f"Indexed control {control_id}")
        return True
    except Exception as exc:
        logger.warning(f"embed_and_store_control failed for {control_id}: {exc}")
        return False


async def delete_control(control_id: str) -> None:
    """Remove a control from the vector index (e.g., when withdrawn)."""
    try:
        col = _get_controls_collection()
        col.delete(ids=[control_id])
    except Exception as exc:
        logger.warning(f"delete_control {control_id} failed: {exc}")


async def search_controls(query: str, n_results: int = 5) -> list[dict]:
    """
    Semantic search over accepted controls.
    Returns list of dicts: {id, document, metadata, distance}.
    """
    try:
        vec = await get_embedding(query)
        if vec is None:
            return []

        col = _get_controls_collection()
        if col.count() == 0:
            return []

        results = col.query(
            query_embeddings=[vec],
            n_results=min(n_results, col.count()),
            include=["documents", "metadatas", "distances"],
        )
        items = []
        for i, doc_id in enumerate(results["ids"][0]):
            items.append({
                "id":       doc_id,
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return items
    except Exception as exc:
        logger.warning(f"search_controls failed: {exc}")
        return []


# =============================================================================
#  Procedures index
# =============================================================================

async def embed_and_store_procedural_step(
    step_id: str,
    step_text: str,
    metadata: dict,
) -> bool:
    """
    Embed a procedural step and upsert into procedures_v1.
    Returns True on success. Fails soft.
    """
    try:
        vec = await get_embedding(step_text)
        if vec is None:
            logger.warning(f"embed_and_store_procedural_step: embedding failed for step {step_id}")
            return False

        col = _get_procedures_collection()
        safe_meta = {k: str(v) for k, v in (metadata or {}).items() if v is not None}
        col.upsert(
            ids=[step_id],
            embeddings=[vec],
            documents=[step_text],
            metadatas=[safe_meta],
        )
        logger.debug(f"Indexed procedural step {step_id}")
        return True
    except Exception as exc:
        logger.warning(f"embed_and_store_procedural_step failed for {step_id}: {exc}")
        return False


async def delete_procedural_steps_by_document(document_code: str) -> int:
    """
    Remove all procedural steps for a document from the index.
    Called before re-indexing a revised document so old steps don't accumulate.
    Returns count of deleted items.
    """
    try:
        col = _get_procedures_collection()
        existing = col.get(where={"document_code": document_code})
        ids_to_delete = existing.get("ids", [])
        if ids_to_delete:
            col.delete(ids=ids_to_delete)
            logger.info(
                f"Deleted {len(ids_to_delete)} procedural steps for {document_code}"
            )
        return len(ids_to_delete)
    except Exception as exc:
        logger.warning(f"delete_procedural_steps_by_document failed for {document_code}: {exc}")
        return 0


async def search_procedures(query: str, n_results: int = 5) -> list[dict]:
    """
    Semantic search over procedural steps.
    Returns list of dicts: {id, document, metadata, distance}.
    The caller (procedural_search.py) then expands each hit to the full process.
    """
    try:
        vec = await get_embedding(query)
        if vec is None:
            return []

        col = _get_procedures_collection()
        if col.count() == 0:
            return []

        results = col.query(
            query_embeddings=[vec],
            n_results=min(n_results, col.count()),
            include=["documents", "metadatas", "distances"],
        )
        items = []
        for i, doc_id in enumerate(results["ids"][0]):
            items.append({
                "id":       doc_id,
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return items
    except Exception as exc:
        logger.warning(f"search_procedures failed: {exc}")
        return []


# =============================================================================
#  Utility
# =============================================================================

def get_collection_stats() -> dict:
    """Returns count of indexed items per collection. Used by health endpoint."""
    try:
        controls_count   = _get_controls_collection().count()
        procedures_count = _get_procedures_collection().count()
        return {
            "controls_v1":   controls_count,
            "procedures_v1": procedures_count,
        }
    except Exception as exc:
        return {"error": str(exc)}
