// frontend/src/App.jsx
// Root component — manages global toast state and online/offline status

import React, { useState, useCallback } from 'react';
import Header from './components/Header';
import Dashboard from './pages/Dashboard';
import { ToastContainer } from './components/Toast';

let toastIdCounter = 0;

export default function App() {
  const [toasts, setToasts] = useState([]);
  const [isOnline, setIsOnline] = useState(true);

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const id = ++toastIdCounter;
    setToasts((prev) => [...prev, { id, message, type, duration }]);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <div className="app-layout">
      <Header isOnline={isOnline} />

      <main className="main-content">
        <Dashboard addToast={addToast} setOnline={setIsOnline} />
      </main>

      <footer className="footer">
        <span>TCS Cloud Incident Monitor</span>
        <span style={{ margin: '0 8px', color: 'var(--border-subtle)' }}>|</span>
        <span>Built for TCS Hackathon 2026</span>
        <span style={{ margin: '0 8px', color: 'var(--border-subtle)' }}>|</span>
        <span>React + Node.js + MongoDB + Python</span>
      </footer>

      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </div>
  );
}
