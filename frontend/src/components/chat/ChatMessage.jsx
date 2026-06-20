import SourcesAccordion from './SourcesAccordion.jsx';

const MODE_LABELS = {
  compliance: { label: 'Compliance', bg: '#dbeafe', color: '#1d4ed8' },
  procedural: { label: 'How-to',     bg: '#d1fae5', color: '#065f46' },
  combined:   { label: 'Combined',   bg: '#ede9fe', color: '#5b21b6' },
};

// =============================================================================
//  Markdown renderer
//  Handles: **bold**, *italic*, numbered lists (with sub-items), bullet lists,
//  ### headers, **bold-only lines** (section headings), blank lines.
//
//  Key invariant: ordered items accumulate into ONE <ol> without flushing
//  between items. Italic sub-lines attach to their parent <li>.
// =============================================================================

function renderMarkdown(text) {
  if (!text) return null;

  const lines   = text.split('\n');
  const elements = [];

  // orderedItems stores { text: string, subs: string[] }
  let orderedItems = [];
  let listItems    = [];

  // ── Flush helpers ──────────────────────────────────────────────────────────

  const flushOrdered = (key) => {
    if (!orderedItems.length) return;
    elements.push(
      <ol
        key={`ol-${key}`}
        style={{ margin: '10px 0', padding: 0, listStyle: 'none' }}
      >
        {orderedItems.map((item, i) => (
          <li
            key={i}
            style={{
              display:      'flex',
              gap:          '10px',
              marginBottom: item.subs.length ? '10px' : '5px',
              alignItems:   'flex-start',
            }}
          >
            {/* Number badge */}
            <span
              style={{
                flexShrink:      0,
                minWidth:        '22px',
                height:          '22px',
                borderRadius:    '50%',
                background:      '#dbeafe',
                color:           '#1d4ed8',
                fontSize:        '11px',
                fontWeight:      700,
                display:         'flex',
                alignItems:      'center',
                justifyContent:  'center',
                marginTop:       '1px',
              }}
            >
              {i + 1}
            </span>
            {/* Step text + optional sub-items */}
            <span style={{ flex: 1, lineHeight: 1.55 }}>
              <span>{parseLine(item.text)}</span>
              {item.subs.length > 0 && (
                <div style={{ marginTop: '5px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                  {item.subs.map((sub, j) => (
                    <span
                      key={j}
                      style={{
                        fontSize:     '11px',
                        color:        '#6b7280',
                        background:   '#f3f4f6',
                        borderRadius: '4px',
                        padding:      '2px 7px',
                      }}
                    >
                      {sub}
                    </span>
                  ))}
                </div>
              )}
            </span>
          </li>
        ))}
      </ol>
    );
    orderedItems = [];
  };

  const flushUnordered = (key) => {
    if (!listItems.length) return;
    elements.push(
      <ul key={`ul-${key}`} style={{ margin: '7px 0', paddingLeft: '20px' }}>
        {listItems.map((t, i) => (
          <li key={i} style={{ marginBottom: '4px', lineHeight: 1.55 }}>
            {parseLine(t)}
          </li>
        ))}
      </ul>
    );
    listItems = [];
  };

  const flushAll = (key) => {
    flushOrdered(key);
    flushUnordered(key);
  };

  // ── Line-by-line processing ────────────────────────────────────────────────

  lines.forEach((line, idx) => {

    // ### Section header
    if (line.startsWith('### ')) {
      flushAll(idx);
      elements.push(
        <p
          key={idx}
          style={{ fontWeight: 700, margin: '13px 0 4px', fontSize: '13px', color: '#111827' }}
        >
          {parseLine(line.slice(4))}
        </p>
      );
      return;
    }

    // **Bold-only line** — treat as a lightweight heading
    if (/^\*\*[^*]+\*\*$/.test(line)) {
      flushAll(idx);
      elements.push(
        <p key={idx} style={{ fontWeight: 600, margin: '9px 0 3px', fontSize: '13px' }}>
          {line.slice(2, -2)}
        </p>
      );
      return;
    }

    // Ordered list item (1. 2. 3. ...)
    const ordMatch = line.match(/^(\d+)\. (.*)/);
    if (ordMatch) {
      flushUnordered(`pre-ord-${idx}`);   // switch list type — flush bullets only
      orderedItems.push({ text: ordMatch[2], subs: [] });
      return;
    }

    // Indented italic sub-line  (   *text*)  — attach to last ordered item
    if (/^\s{2,}\*[^*].*\*\s*$/.test(line) || /^\s{2,}\*[^*]\*\s*$/.test(line)) {
      const subText = line.trim().replace(/^\*|\*$/g, '');
      if (orderedItems.length > 0) {
        orderedItems[orderedItems.length - 1].subs.push(subText);
      } else {
        // Outside of a list — render as standalone grey note
        flushAll(idx);
        elements.push(
          <div key={idx} style={{ fontSize: '11px', color: '#6b7280', marginLeft: '8px', marginBottom: '3px' }}>
            {subText}
          </div>
        );
      }
      return;
    }

    // Unordered list
    if (line.startsWith('- ') || line.startsWith('* ')) {
      flushOrdered(`pre-ul-${idx}`);   // switch list type — flush ordered only
      listItems.push(line.slice(2));
      return;
    }

    // Blank line — flush everything
    if (!line.trim()) {
      flushAll(idx);
      return;
    }

    // Normal paragraph line
    flushAll(idx);
    elements.push(
      <p key={idx} style={{ margin: '4px 0', lineHeight: 1.6 }}>
        {parseLine(line)}
      </p>
    );
  });

  flushAll('end');
  return elements.length ? elements : null;
}


// =============================================================================
//  Inline parser — handles **bold** and *italic* within a line
// =============================================================================

function parseLine(text) {
  if (!text) return text;

  // First split on **bold** markers
  const boldParts = text.split(/(\*\*[^*]+\*\*)/g);

  return boldParts.flatMap((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return [<strong key={`b-${i}`}>{part.slice(2, -2)}</strong>];
    }
    // Within a non-bold segment, handle *italic*
    const italicParts = part.split(/(\*[^*]+\*)/g);
    return italicParts.map((ip, j) => {
      if (ip.startsWith('*') && ip.endsWith('*') && ip.length > 2) {
        return (
          <em key={`i-${i}-${j}`} style={{ color: '#6b7280', fontStyle: 'italic' }}>
            {ip.slice(1, -1)}
          </em>
        );
      }
      return ip;
    });
  });
}


// =============================================================================
//  ChatMessage component
// =============================================================================

export default function ChatMessage({ message }) {
  const isUser   = message.role === 'user';
  const modeInfo = message.mode ? MODE_LABELS[message.mode] : null;

  // Detect "I don't have information" type responses for subtle styling
  const isNoInfo = !message.loading && /i (don't|do not|couldn't|didn't|cannot) (have|find|know)/i.test(
    message.content || ''
  );

  if (isUser) {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '14px' }}>
        <div
          style={{
            maxWidth:     '82%',
            background:   '#1d4ed8',
            color:        '#fff',
            borderRadius: '14px 14px 2px 14px',
            padding:      '9px 14px',
            fontSize:     '13.5px',
            lineHeight:   1.5,
          }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  // ── Assistant message ──────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '16px' }}>
      <div
        style={{
          maxWidth:     '92%',
          background:   isNoInfo ? '#fffbeb' : '#f9fafb',
          border:       `1px solid ${isNoInfo ? '#fde68a' : '#e5e7eb'}`,
          borderLeft:   isNoInfo ? '3px solid #d97706' : undefined,
          borderRadius: '2px 14px 14px 14px',
          padding:      '11px 14px',
          fontSize:     '13px',
          lineHeight:   1.55,
          color:        '#111827',
        }}
      >
        {/* Mode badge */}
        {modeInfo && !message.loading && (
          <span
            style={{
              display:      'inline-block',
              padding:      '2px 8px',
              borderRadius: '10px',
              fontSize:     '10px',
              fontWeight:   600,
              letterSpacing:'0.03em',
              background:   modeInfo.bg,
              color:        modeInfo.color,
              marginBottom: '8px',
            }}
          >
            {modeInfo.label}
          </span>
        )}

        {/* Loading dots */}
        {message.loading ? (
          <div style={{ display: 'flex', gap: '4px', alignItems: 'center', padding: '4px 0' }}>
            {[0, 1, 2].map(i => (
              <span
                key={i}
                style={{
                  width: '6px', height: '6px', borderRadius: '50%',
                  background: '#9ca3af',
                  animation: `chatdot 1.2s ease-in-out ${i * 0.2}s infinite`,
                }}
              />
            ))}
            <style>{`@keyframes chatdot { 0%,80%,100%{opacity:.3;transform:scale(.8)} 40%{opacity:1;transform:scale(1)} }`}</style>
          </div>
        ) : (
          <div>{renderMarkdown(message.content)}</div>
        )}

        {/* Sources accordion */}
        {!message.loading && message.sources?.length > 0 && (
          <div style={{ marginTop: '8px' }}>
            <SourcesAccordion sources={message.sources} />
          </div>
        )}
      </div>
    </div>
  );
}
