import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Send, Plus, Clock, Trash2 } from 'lucide-react';
import ChatMessage from './ChatMessage.jsx';
import {
  createSession,
  getSession,
  getAllSessions,
  saveMessage,
  deleteSession,
} from '../../services/aiDb.js';
import { nlSearchApi } from '../../api/grcApi.js';

const PANEL_WIDTH = 480;

export default function ChatPanel({ isOpen, onClose }) {
  const [sessions, setSessions]             = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages]             = useState([]);
  const [input, setInput]                   = useState('');
  const [sending, setSending]               = useState(false);
  const [showHistory, setShowHistory]       = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef       = useRef(null);

  // ── Load sessions when panel opens ──────────────────────────────────────
  useEffect(() => {
    if (!isOpen) return;
    (async () => {
      const all = await getAllSessions();
      setSessions(all);
      // Resume most recent session or start fresh
      if (all.length > 0 && !activeSessionId) {
        const latest = all[0];
        setActiveSessionId(latest.id);
        setMessages(latest.messages || []);
      } else if (!activeSessionId) {
        await _startNewSession();
      }
    })();
  }, [isOpen]);

  // ── Scroll to bottom when messages change ───────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── Focus input when panel opens ────────────────────────────────────────
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // ── Keyboard: Escape closes panel ───────────────────────────────────────
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // ── Start a new session ─────────────────────────────────────────────────
  const _startNewSession = async () => {
    const id = await createSession();
    setActiveSessionId(id);
    setMessages([]);
    // Add a greeting message
    const greeting = {
      id:      'greeting',
      role:    'assistant',
      content: 'Hi! Ask me anything about Dragnet\'s policies, controls, or procedures.\n\nTry: "What are the password requirements?" or "How do I request a laptop?"',
      timestamp: new Date().toISOString(),
      mode:    null,
      sources: [],
    };
    setMessages([greeting]);
    return id;
  };

  const handleNewSession = async () => {
    setShowHistory(false);
    await _startNewSession();
    const all = await getAllSessions();
    setSessions(all);
  };

  // ── Switch to a previous session ────────────────────────────────────────
  const handleSelectSession = async (sessionId) => {
    const session = await getSession(sessionId);
    if (!session) return;
    setActiveSessionId(sessionId);
    setMessages(session.messages || []);
    setShowHistory(false);
  };

  // ── Delete a session ────────────────────────────────────────────────────
  const handleDeleteSession = async (e, sessionId) => {
    e.stopPropagation();
    await deleteSession(sessionId);
    const all = await getAllSessions();
    setSessions(all);
    if (sessionId === activeSessionId) {
      if (all.length > 0) {
        await handleSelectSession(all[0].id);
      } else {
        await _startNewSession();
      }
    }
  };

  // ── Send a message ───────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || sending) return;

    const sessionId = activeSessionId || (await _startNewSession());
    setInput('');
    setSending(true);

    // Add user message immediately
    const userMsg = {
      id:        `msg_${Date.now()}`,
      role:      'user',
      content:   question,
      timestamp: new Date().toISOString(),
    };
    const loadingMsg = {
      id:      'loading',
      role:    'assistant',
      content: '',
      loading: true,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg, loadingMsg]);
    await saveMessage(sessionId, userMsg);

    try {
      // Send the last 6 messages as conversation context (3 user+assistant pairs)
      // Filter out the greeting, loading indicator, and current question just pushed
      const conversationHistory = messages
        .filter(m => !m.loading && m.id !== 'greeting' && (m.role === 'user' || m.role === 'assistant'))
        .slice(-6)
        .map(m => ({ role: m.role, content: m.content }));

      const response = await nlSearchApi.query(question, sessionId, conversationHistory);
      const assistantMsg = {
        id:        `msg_${Date.now() + 1}`,
        role:      'assistant',
        content:   response.answer,
        timestamp: new Date().toISOString(),
        mode:      response.mode,
        sources:   response.sources || [],
      };
      setMessages(prev => prev.filter(m => m.id !== 'loading').concat(assistantMsg));
      await saveMessage(sessionId, assistantMsg);

      // Refresh session list (title may have updated)
      const all = await getAllSessions();
      setSessions(all);

    } catch (err) {
      const raw = err?.message || '';
      // Pydantic validation errors come back as a JSON array — show a clean message instead
      let friendly = raw;
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed[0]?.msg) {
          friendly = parsed[0].msg;
        }
      } catch { /* not JSON — use raw */ }
      const errorMsg = {
        id:        `msg_err_${Date.now()}`,
        role:      'assistant',
        content:   `Sorry, I couldn't process that. ${friendly || 'Please try again.'}`,
        timestamp: new Date().toISOString(),
        mode:      null,
        sources:   [],
      };
      setMessages(prev => prev.filter(m => m.id !== 'loading').concat(errorMsg));
    } finally {
      setSending(false);
    }
  }, [input, sending, activeSessionId]);

  // ── Handle Enter key in textarea ────────────────────────────────────────
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!isOpen) return null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position:   'fixed',
          inset:      0,
          background: 'rgba(0,0,0,0.45)',
          zIndex:     1299,
          transition: 'opacity 0.2s ease',
        }}
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-label="OrgOS AI Assistant"
        aria-modal="true"
        style={{
          position:    'fixed',
          top:         0,
          right:       0,
          bottom:      0,
          width:       `${PANEL_WIDTH}px`,
          maxWidth:    '100vw',
          background:  '#fff',
          zIndex:      1300,
          display:     'flex',
          flexDirection:'column',
          boxShadow:   '-4px 0 24px rgba(0,0,0,0.12)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display:         'flex',
            alignItems:      'center',
            justifyContent:  'space-between',
            padding:         '14px 16px',
            borderBottom:    '1px solid #e5e7eb',
            flexShrink:      0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '28px', height: '28px', borderRadius: '50%',
                background: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <span style={{ color: '#fff', fontSize: '13px', fontWeight: 700 }}>A</span>
            </div>
            <span style={{ fontWeight: 600, fontSize: '14px', color: '#111827' }}>
              OrgOS AI Assistant
            </span>
          </div>

          <div style={{ display: 'flex', gap: '6px' }}>
            {/* Session history toggle */}
            <button
              onClick={() => setShowHistory(h => !h)}
              title="Conversation history"
              style={_iconBtn(showHistory ? '#dbeafe' : 'transparent')}
            >
              <Clock size={16} color={showHistory ? '#1d4ed8' : '#6b7280'} />
            </button>
            {/* New conversation */}
            <button onClick={handleNewSession} title="New conversation" style={_iconBtn()}>
              <Plus size={16} color="#6b7280" />
            </button>
            {/* Close */}
            <button onClick={onClose} title="Close" style={_iconBtn()}>
              <X size={16} color="#6b7280" />
            </button>
          </div>
        </div>

        {/* Session history drawer */}
        {showHistory && (
          <div
            style={{
              borderBottom: '1px solid #e5e7eb',
              maxHeight:    '200px',
              overflowY:    'auto',
              background:   '#f9fafb',
              flexShrink:   0,
            }}
          >
            <div style={{ padding: '8px 14px', fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Previous conversations
            </div>
            {sessions.length === 0 ? (
              <div style={{ padding: '8px 14px', fontSize: '12px', color: '#9ca3af' }}>No history yet</div>
            ) : (
              sessions.map(s => (
                <div
                  key={s.id}
                  onClick={() => handleSelectSession(s.id)}
                  style={{
                    display:        'flex',
                    alignItems:     'center',
                    justifyContent: 'space-between',
                    padding:        '7px 14px',
                    cursor:         'pointer',
                    background:     s.id === activeSessionId ? '#dbeafe' : 'transparent',
                    fontSize:       '12px',
                    color:          '#374151',
                    gap:            '8px',
                  }}
                  onMouseEnter={e => { if (s.id !== activeSessionId) e.currentTarget.style.background = '#f3f4f6'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = s.id === activeSessionId ? '#dbeafe' : 'transparent'; }}
                >
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.title || 'Untitled'}
                  </span>
                  <button
                    onClick={(e) => handleDeleteSession(e, s.id)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', flexShrink: 0 }}
                  >
                    <Trash2 size={12} color="#9ca3af" />
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {/* Messages area */}
        <div
          style={{
            flex:      1,
            overflowY: 'auto',
            padding:   '16px',
          }}
        >
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div
          style={{
            borderTop:  '1px solid #e5e7eb',
            padding:    '12px 14px',
            flexShrink: 0,
            background: '#fff',
          }}
        >
          <div
            style={{
              display:      'flex',
              gap:          '8px',
              alignItems:   'flex-end',
              background:   '#f9fafb',
              border:       '1px solid #e5e7eb',
              borderRadius: '10px',
              padding:      '8px 10px',
            }}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about controls, policies, procedures..."
              rows={1}
              style={{
                flex:       1,
                border:     'none',
                background: 'transparent',
                resize:     'none',
                outline:    'none',
                fontSize:   '13.5px',
                lineHeight: 1.45,
                color:      '#111827',
                maxHeight:  '100px',
                overflowY:  'auto',
                fontFamily: 'inherit',
              }}
              onInput={e => {
                e.target.style.height = 'auto';
                e.target.style.height = Math.min(e.target.scrollHeight, 100) + 'px';
              }}
              disabled={sending}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              style={{
                background:   !input.trim() || sending ? '#e5e7eb' : '#2563eb',
                border:       'none',
                borderRadius: '7px',
                width:        '32px',
                height:       '32px',
                display:      'flex',
                alignItems:   'center',
                justifyContent:'center',
                cursor:        !input.trim() || sending ? 'not-allowed' : 'pointer',
                flexShrink:    0,
                transition:    'background 0.15s',
              }}
            >
              <Send size={15} color={!input.trim() || sending ? '#9ca3af' : '#fff'} />
            </button>
          </div>
          <p style={{ fontSize: '10.5px', color: '#9ca3af', margin: '5px 0 0 2px' }}>
            Enter to send · Shift+Enter for new line
          </p>
        </div>
      </div>
    </>,
    document.body
  );
}

function _iconBtn(bg = 'transparent') {
  return {
    background:   bg,
    border:       'none',
    borderRadius: '6px',
    width:        '28px',
    height:       '28px',
    display:      'flex',
    alignItems:   'center',
    justifyContent:'center',
    cursor:       'pointer',
    transition:   'background 0.1s',
  };
}
