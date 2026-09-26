import React, { useEffect } from "react";

// Adapted from PR #6's notification component for this dashboard only.
export function Toast({ id, message, tone = "info", onDismiss, duration = 5000 }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), duration);
    return () => clearTimeout(timer);
  }, [duration, id, onDismiss]);
  return <div className={`toast toast-${tone}`} role={tone === "error" ? "alert" : "status"}>
    <span>{message}</span>
    <button type="button" aria-label="Dismiss notification" onClick={() => onDismiss(id)}>×</button>
  </div>;
}

export function ToastContainer({ toasts, onDismiss }) {
  return <div className="toast-container" aria-live="polite" aria-atomic="false">
    {toasts.map(toast => <Toast key={toast.id} {...toast} onDismiss={onDismiss} />)}
  </div>;
}
