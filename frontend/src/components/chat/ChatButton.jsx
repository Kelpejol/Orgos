import { MessageCircle } from 'lucide-react';

export default function ChatButton({ onClick, hasUnread = false }) {
  return (
    <button
      onClick={onClick}
      aria-label="Open AI Assistant"
      style={{
        position:     'fixed',
        bottom:       '28px',
        right:        '28px',
        zIndex:       1200,
        width:        '52px',
        height:       '52px',
        borderRadius: '50%',
        background:   'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
        border:       'none',
        cursor:       'pointer',
        display:      'flex',
        alignItems:   'center',
        justifyContent: 'center',
        boxShadow:    '0 4px 16px rgba(37,99,235,0.35)',
        transition:   'transform 0.15s ease, box-shadow 0.15s ease',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'scale(1.08)';
        e.currentTarget.style.boxShadow = '0 6px 20px rgba(37,99,235,0.45)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = 'scale(1)';
        e.currentTarget.style.boxShadow = '0 4px 16px rgba(37,99,235,0.35)';
      }}
    >
      <MessageCircle size={22} color="#fff" strokeWidth={2} />
      {hasUnread && (
        <span style={{
          position:     'absolute',
          top:          '6px',
          right:        '6px',
          width:        '10px',
          height:       '10px',
          borderRadius: '50%',
          background:   '#ef4444',
          border:       '2px solid #fff',
        }} />
      )}
    </button>
  );
}
