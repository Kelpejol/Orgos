// =============================================================================
// frontend/src/services/aiDb.js — IndexedDB service for AI persistence
//
// Database: orgos_ai_db (version 1)
// Object stores:
//   chat_sessions   — full conversation history per session
//   ai_suggestions  — persisted AI response per item (CDI fix, assessments, etc.)
//   search_cache    — short-lived cache for repeated NL search queries
//
// All functions are async. Import and call directly — no provider/context needed.
// Never access IndexedDB directly from components; always go through this module.
// =============================================================================

import { openDB } from 'idb';

const DB_NAME    = 'orgos_ai_db';
const DB_VERSION = 1;

// Suggestion expiry: 7 days
const SUGGESTION_TTL_MS = 7 * 24 * 60 * 60 * 1000;
// Search cache expiry: 15 minutes for compliance, 1 hour for procedural
const CACHE_TTL_COMPLIANCE_MS  = 15 * 60 * 1000;
const CACHE_TTL_PROCEDURAL_MS  = 60 * 60 * 1000;

// ---------------------------------------------------------------------------
//  DB initialisation
// ---------------------------------------------------------------------------

let _db = null;

async function getDb() {
  if (_db) return _db;
  _db = await openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      // chat_sessions — keyed by session ID
      if (!db.objectStoreNames.contains('chat_sessions')) {
        const sessionStore = db.createObjectStore('chat_sessions', { keyPath: 'id' });
        sessionStore.createIndex('last_active', 'last_active');
      }

      // ai_suggestions — keyed by "<item_id>:<suggestion_type>"
      if (!db.objectStoreNames.contains('ai_suggestions')) {
        const suggStore = db.createObjectStore('ai_suggestions', { keyPath: 'id' });
        suggStore.createIndex('item_id', 'item_id');
        suggStore.createIndex('expires_at', 'expires_at');
      }

      // search_cache — keyed by "<mode>:<query_hash>"
      if (!db.objectStoreNames.contains('search_cache')) {
        const cacheStore = db.createObjectStore('search_cache', { keyPath: 'id' });
        cacheStore.createIndex('expires_at', 'expires_at');
      }
    },
  });
  return _db;
}

// ---------------------------------------------------------------------------
//  Helpers
// ---------------------------------------------------------------------------

function _now() { return new Date().toISOString(); }
function _expiry(ms) { return new Date(Date.now() + ms).toISOString(); }
function _isExpired(record) {
  if (!record?.expires_at) return false;
  return new Date(record.expires_at) < new Date();
}

// Simple deterministic hash for cache keys (not crypto — just collision-resistant for strings)
function _hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

// ---------------------------------------------------------------------------
//  Chat sessions
// ---------------------------------------------------------------------------

export async function createSession() {
  const db = await getDb();
  const id = `session_${Date.now()}`;
  const session = {
    id,
    started_at:  _now(),
    last_active: _now(),
    title:       'New conversation',
    messages:    [],
  };
  await db.put('chat_sessions', session);
  return id;
}

export async function getSession(sessionId) {
  const db = await getDb();
  return db.get('chat_sessions', sessionId) ?? null;
}

export async function getAllSessions() {
  const db = await getDb();
  const all = await db.getAllFromIndex('chat_sessions', 'last_active');
  // Most recent first
  return all.sort((a, b) => new Date(b.last_active) - new Date(a.last_active));
}

export async function saveMessage(sessionId, message) {
  const db = await getDb();
  let session = await db.get('chat_sessions', sessionId);
  if (!session) {
    // Auto-create session if it no longer exists
    session = {
      id:          sessionId,
      started_at:  _now(),
      last_active: _now(),
      title:       '',
      messages:    [],
    };
  }

  session.messages = [...(session.messages || []), message];
  session.last_active = _now();

  // Set title from first user message
  if (!session.title || session.title === 'New conversation') {
    const firstUser = session.messages.find(m => m.role === 'user');
    if (firstUser) {
      session.title = firstUser.content.slice(0, 60) + (firstUser.content.length > 60 ? '…' : '');
    }
  }

  await db.put('chat_sessions', session);
}

export async function deleteSession(sessionId) {
  const db = await getDb();
  await db.delete('chat_sessions', sessionId);
}

export async function clearAllSessions() {
  const db = await getDb();
  await db.clear('chat_sessions');
}

// ---------------------------------------------------------------------------
//  AI suggestions
// ---------------------------------------------------------------------------

/**
 * suggestion_type values:
 *   "cdi_fix" | "lifecycle_assessment" | "feedback_suggestions" |
 *   "gap_remediation_preview" | "extraction_suggestion"
 */
export async function saveSuggestion(itemId, suggestionType, content) {
  const db = await getDb();
  const id = `${itemId}:${suggestionType}`;
  await db.put('ai_suggestions', {
    id,
    item_id:         itemId,
    suggestion_type: suggestionType,
    content,
    generated_at:    _now(),
    expires_at:      _expiry(SUGGESTION_TTL_MS),
  });
}

export async function getSuggestion(itemId, suggestionType) {
  const db = await getDb();
  const record = await db.get('ai_suggestions', `${itemId}:${suggestionType}`);
  if (!record) return null;
  if (_isExpired(record)) {
    await db.delete('ai_suggestions', record.id);
    return null;
  }
  return record;
}

export async function deleteSuggestion(itemId, suggestionType) {
  const db = await getDb();
  await db.delete('ai_suggestions', `${itemId}:${suggestionType}`);
}

export async function clearExpiredSuggestions() {
  const db = await getDb();
  const all = await db.getAll('ai_suggestions');
  const now = new Date();
  await Promise.all(
    all
      .filter(r => r.expires_at && new Date(r.expires_at) < now)
      .map(r => db.delete('ai_suggestions', r.id))
  );
}

// ---------------------------------------------------------------------------
//  Search cache
// ---------------------------------------------------------------------------

export async function cacheSearchResult(mode, query, result) {
  const db   = await getDb();
  const ttl  = mode === 'compliance' ? CACHE_TTL_COMPLIANCE_MS : CACHE_TTL_PROCEDURAL_MS;
  const id   = `${mode}:${_hashString(query.toLowerCase().trim())}`;
  await db.put('search_cache', {
    id,
    query,
    mode,
    result,
    cached_at:  _now(),
    expires_at: _expiry(ttl),
  });
}

export async function getCachedSearchResult(mode, query) {
  const db   = await getDb();
  const id   = `${mode}:${_hashString(query.toLowerCase().trim())}`;
  const record = await db.get('search_cache', id);
  if (!record) return null;
  if (_isExpired(record)) {
    await db.delete('search_cache', id);
    return null;
  }
  return record;
}

export async function clearSearchCache() {
  const db = await getDb();
  await db.clear('search_cache');
}

// ---------------------------------------------------------------------------
//  Startup cleanup — call once on app init
// ---------------------------------------------------------------------------

export async function runStartupCleanup() {
  try {
    await clearExpiredSuggestions();
    // Clear expired search cache entries
    const db  = await getDb();
    const all = await db.getAll('search_cache');
    const now = new Date();
    await Promise.all(
      all
        .filter(r => r.expires_at && new Date(r.expires_at) < now)
        .map(r => db.delete('search_cache', r.id))
    );
  } catch {
    // Startup cleanup is best-effort — never block the app
  }
}
