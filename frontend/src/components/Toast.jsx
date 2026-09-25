// frontend/src/components/Toast.jsx
// Global toast notification system

import React, { useEffect } from 'react';

/**
 * Single toast notification
 */
export function Toast({ toast, onRemove }) {
  useEffect(() => {
    const timer = setTimeout(() => onRemove(toast.id), toast.duration || 4000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onRemove]);

  const icons = {
    success: '✓',
    error: '✕',
    info: 'ℹ',
    warning: '⚠',
  };

  return (
    <div className={`toast ${toast.type}`} role="alert">
      <span style={{ fontSize: '16px', flexShrink: 0 }}>
        {icons[toast.type] || 'ℹ'}
      </span>
      <span className="toast-message">{toast.message}</span>
      <button
        onClick={() => onRemove(toast.id)}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          color: 'inherit',
          opacity: 0.6,
          fontSize: '14px',
          padding: '0 4px',
          flexShrink: 0,
        }}
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}

/**
 * Toast container — renders all active toasts
 */
export function ToastContainer({ toasts, onRemove }) {
  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onRemove={onRemove} />
      ))}
    </div>
  );
}
