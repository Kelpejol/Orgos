import SourcesAccordion from './SourcesAccordion.jsx';

const MODE_LABELS = {
  compliance:  { label: 'Compliance', bg: '#dbeafe', color: '#1d4ed8' },
  procedural:  { label: 'How-to',     bg: '#d1fae5', color: '#065f46' },
  combined:    { label: 'Combined',   bg: '#ede9fe', color: '#5b21b6' },
};

// Very light markdown renderer — handles **bold**, numbered lists, bullet lists
function renderMarkdown(text) {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let listItems = [];
  let orderedItems = [];

  const flushList = (key) => {
    if (listItems.length) {
      elements.push(
        <ul key={`ul-${key}`} style={{ margin: '6px 0', paddingLeft: '18px' }}>
          {listItems.map((t, i) => <li key={i} style={{ marginBottom: '2px' }}>{parseLine(t)}</li>)}
        </ul>
      );
      listItems = [];
    }
    if (orderedItems.length) {
      elements.push(
        <ol key={`ol-${key}`} style={{ margin: '6px 0', paddingLeft: '18px' }}>
          {orderedItems.map((t, i) => <li key={i} style={{ marginBottom: '3px' }}>{parseLine(t)}</li>)}
        </ol>
      );
      orderedItems = [];
    }
  };

  lines.forEach((line, idx) => {
    // Headers (###)
    if (line.startsWith('### ')) {
      flushList(idx);
      elements.push(
        <p key={idx} style={{ fontWeight: 700, margin: '10px 0 4px', fontSize: '13px' }}>
          {parseLine(line.slice(4))}
        </p>
      );
      return;
    }
    // Bold header (**)
    if (line.startsWith('**') && line.endsWith('**') && line.length > 4) {
      flushList(idx);
      elements.push(
        <p key={idx} style={{ fontWeight: 600, margin: '8px 0 2px' }}>
          {line.slice(2, -2)}
        </p>
      );
      return;
    }
    // Ordered list
    const orderedMatch = line.match(/^(\d+)\. (.*)/);
    if (orderedMatch) {
      flushList(`pre-${idx}`);
      orderedItems.push(orderedMatch[2]);
      return;
    }
    // Unordered list
    if (line.startsWith('- ') || line.startsWith('* ')) {
      flushList(`pre-${idx}`);
      listItems.push(line.slice(2));
      return;
    }
    // Italic prefix (   *...*) — step detail lines
    if (line.match(/^\s{2,}\*.*\*$/)) {
      elements.push(
        <div key={idx} style={{ fontSize: '11px', color: '#6b7280', marginLeft: '16px', marginBottom: '2px' }}>
          {line.trim().replace(/^\*|\*$/g, '')}
        </div>
      );
      return;
    }
    // Blank line
    if (!line.trim()) {
      flushList(idx);
      return;
    }
    // Normal line
    flushList(idx);
    elements.push(
      <p key={idx} style={{ margin: '3px 0' }}>{parseLine(line)}</p>
    );
  });
  flushList('end');
  return elements;
}

// Inline bold: **text**
function parseLine(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

export default function ChatMessage({ message }) {
  const isUser = message.role === 'user';
  const modeInfo = message.mode ? MODE_LABELS[message.mode] : null;

  if (isUser) {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '12px' }}>
        <div
          style={{
            maxWidth:     '82%',
            background:   '#1d4ed8',
            color:        '#fff',
            borderRadius: '14px 14px 2px 14px',
            padding:      '9px 13px',
            fontSize:     '13.5px',
            lineHeight:   1.45,
          }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '14px' }}>
      <div
        style={{
          maxWidth:     '90%',
          background:   '#f9fafb',
          border:       '1px solid #e5e7eb',
          borderRadius: '2px 14px 14px 14px',
          padding:      '10px 13px',
          fontSize:     '13px',
          lineHeight:   1.5,
          color:        '#111827',
        }}
      >
        {/* Mode badge */}
        {modeInfo && (
          <span
            style={{
              display:      'inline-block',
              padding:      '1px 7px',
              borderRadius: '9px',
              fontSize:     '10px',
              fontWeight:   600,
              background:   modeInfo.bg,
              color:        modeInfo.color,
              marginBottom: '7px',
            }}
          >
            {modeInfo.label}
          </span>
        )}

        {/* Loading state */}
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

        {/* Sources */}
        {!message.loading && message.sources?.length > 0 && (
          <SourcesAccordion sources={message.sources} />
        )}
      </div>
    </div>
  );
}
