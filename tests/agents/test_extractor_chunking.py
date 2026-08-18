# =============================================================================
# tests/agents/test_extractor_chunking.py — extractor chunking unit tests
#
# _chunk_text is pure (no LLM/Graph), so it is fully unit-testable. It guards
# the fix for the "only first 8000 chars were extracted" bug: long documents
# must now be split into <= MAX_CHUNK_CHARS windows with nothing dropped.
# =============================================================================

from agents.extractor.ollama_client import MAX_CHUNK_CHARS, MAX_CHUNKS, _chunk_text


def test_short_text_is_single_chunk():
    assert _chunk_text("hello world", 50000) == ["hello world"]


def test_empty_or_blank_yields_no_chunks():
    assert _chunk_text("", 50000) == []
    assert _chunk_text("   \n\n  ", 50000) == []


def test_exactly_max_is_single_chunk():
    exact = "z" * 50000
    assert _chunk_text(exact, 50000) == [exact]


def test_splits_on_paragraph_boundaries_without_losing_content():
    paras = "\n\n".join(f"PARA{i} " + "x" * 1000 for i in range(120))  # ~120k chars
    chunks = _chunk_text(paras, 50000)
    assert len(chunks) >= 3
    assert all(len(c) <= 50000 for c in chunks)          # every chunk within cap
    joined = "\n\n".join(chunks)
    assert all(f"PARA{i} " in joined for i in range(120))  # nothing dropped


def test_oversized_single_paragraph_is_hard_sliced():
    big = "y" * 130000  # one paragraph, no boundaries
    chunks = _chunk_text(big, 50000)
    assert all(len(c) <= 50000 for c in chunks)
    assert sum(len(c) for c in chunks) == 130000          # every character preserved


def test_defaults_are_sane():
    assert MAX_CHUNK_CHARS == 50000
    assert MAX_CHUNKS >= 1
