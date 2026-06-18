// =============================================================================
// frontend/src/hooks/useAiSuggestion.js — Cached AI suggestion hook
//
// Wraps any AI suggestion API call with IndexedDB persistence.
// On mount: checks IndexedDB first. If a valid (non-expired) suggestion exists,
// returns it immediately without an API call.
// On generate(): calls the API, persists result, returns it.
//
// Usage:
//   const { suggestion, loading, isFromCache, generatedAt, generate } =
//     useAiSuggestion(docId, 'cdi_fix', () => lifecycleApi.cdiFix(docId));
//
// suggestion_type values (see aiDb.js):
//   "cdi_fix" | "lifecycle_assessment" | "feedback_suggestions" |
//   "gap_remediation_preview" | "extraction_suggestion"
// =============================================================================

import { useState, useEffect, useCallback } from 'react';
import { getSuggestion, saveSuggestion, deleteSuggestion } from '../services/aiDb.js';

/**
 * @param {string} itemId        — SharePoint item ID
 * @param {string} suggestionType — One of the suggestion_type constants
 * @param {Function} apiFn       — Async function that calls the backend and returns the result
 */
export function useAiSuggestion(itemId, suggestionType, apiFn) {
  const [suggestion, setSuggestion]   = useState(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState(null);
  const [isFromCache, setIsFromCache] = useState(false);
  const [generatedAt, setGeneratedAt] = useState(null);

  // On mount (and when itemId/type changes): check IndexedDB
  useEffect(() => {
    if (!itemId || !suggestionType) return;
    let cancelled = false;

    getSuggestion(itemId, suggestionType).then(record => {
      if (cancelled) return;
      if (record) {
        setSuggestion(record.content);
        setIsFromCache(true);
        setGeneratedAt(record.generated_at);
      }
    });

    return () => { cancelled = true; };
  }, [itemId, suggestionType]);

  // generate(): call API, persist, update state
  const generate = useCallback(async () => {
    if (!apiFn) return;
    setLoading(true);
    setError(null);
    try {
      const result = await apiFn();
      await saveSuggestion(itemId, suggestionType, result);
      setSuggestion(result);
      setIsFromCache(false);
      setGeneratedAt(new Date().toISOString());
      return result;
    } catch (err) {
      setError(err?.message || 'Failed to generate suggestion');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [itemId, suggestionType, apiFn]);

  // regenerate(): force a fresh API call, replacing the cached version
  const regenerate = useCallback(async () => {
    if (itemId && suggestionType) {
      await deleteSuggestion(itemId, suggestionType);
    }
    setSuggestion(null);
    setIsFromCache(false);
    return generate();
  }, [itemId, suggestionType, generate]);

  return {
    suggestion,
    loading,
    error,
    isFromCache,
    generatedAt,
    generate,
    regenerate,
    hasSuggestion: suggestion !== null,
  };
}
