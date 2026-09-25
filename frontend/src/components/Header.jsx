// frontend/src/components/Header.jsx
// Sticky app header with logo and backend connection status

import React from 'react';

export default function Header({ isOnline }) {
  return (
    <header className="header">
      <div className="header-logo">
        <div className="header-logo-icon">🛡️</div>
        <div className="header-logo-text">
          <span className="header-logo-title">TCS Incident Monitor</span>
          <span className="header-logo-subtitle">Cloud Operations Platform</span>
        </div>
      </div>

      <div className="header-status">
        <div className={`status-dot ${isOnline ? '' : 'offline'}`} />
        <span>{isOnline ? 'Backend Connected' : 'Backend Offline'}</span>
        <span style={{ color: 'var(--border-subtle)', margin: '0 4px' }}>|</span>
        <a
          href="http://localhost:5000/api-docs"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--brand-1)', textDecoration: 'none', fontSize: '12px', fontWeight: 600 }}
        >
          API Docs ↗
        </a>
      </div>
    </header>
  );
}
