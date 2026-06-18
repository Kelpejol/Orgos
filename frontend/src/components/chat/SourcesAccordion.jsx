import { useState } from 'react';
import { ChevronDown, ChevronUp, FileText, ExternalLink } from 'lucide-react';

export default function SourcesAccordion({ sources = [] }) {
  const [open, setOpen] = useState(false);

  if (!sources || sources.length === 0) return null;

  return (
    <div style={{ marginTop: '8px', borderTop: '1px solid #e5e7eb', paddingTop: '6px' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display:        'flex',
          alignItems:     'center',
          gap:            '6px',
          background:     'none',
          border:         'none',
          cursor:         'pointer',
          color:          '#6b7280',
          fontSize:       '12px',
          padding:        '2px 0',
          width:          '100%',
          justifyContent: 'flex-start',
        }}
      >
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        {sources.length} source{sources.length !== 1 ? 's' : ''}
      </button>

      {open && (
        <ul style={{ listStyle: 'none', margin: '6px 0 0 0', padding: 0 }}>
          {sources.map((src, i) => (
            <li
              key={i}
              style={{
                display:     'flex',
                alignItems:  'center',
                gap:         '6px',
                padding:     '4px 0',
                fontSize:    '12px',
                color:       '#374151',
                borderBottom: i < sources.length - 1 ? '1px solid #f3f4f6' : 'none',
              }}
            >
              <FileText size={12} color="#9ca3af" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <span style={{ fontWeight: 500 }}>
                  {src.document_code || src.title}
                </span>
                {src.clause && (
                  <span style={{ color: '#6b7280', marginLeft: '6px' }}>
                    §{src.clause}
                  </span>
                )}
              </div>
              {src.link && (
                <a
                  href={src.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open document"
                  style={{ color: '#2563eb', flexShrink: 0 }}
                >
                  <ExternalLink size={12} />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
