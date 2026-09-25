// frontend/src/components/ErrorSimulator.jsx
// Interactive component to simulate 10 distinct cloud error logs

import React, { useState, useEffect } from 'react';
import { simulationApi } from '../services/api';

export default function ErrorSimulator({ addToast }) {
  const [scenarios, setScenarios] = useState([]);
  const [loading, setLoading] = useState(false);
  const [triggeringId, setTriggeringId] = useState(null);
  const [lastTriggered, setLastTriggered] = useState(null);

  useEffect(() => {
    fetchScenarios();
  }, []);

  const fetchScenarios = async () => {
    setLoading(true);
    try {
      const res = await simulationApi.getScenarios();
      setScenarios(res.data.scenarios);
    } catch (err) {
      addToast('Failed to load error scenarios', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleTrigger = async (typeId) => {
    setTriggeringId(typeId);
    try {
      const res = await simulationApi.triggerError(typeId);
      const errInfo = res.data?.error || {};
      setLastTriggered(errInfo);
      addToast(`🚨 Triggered ${errInfo.level || 'ERROR'}: ${errInfo.title}`, 'error');
    } catch (err) {
      const errInfo = err.response?.data?.error;
      if (errInfo) {
        setLastTriggered(errInfo);
        addToast(`🚨 Triggered ${errInfo.level || 'ERROR'}: ${errInfo.title}`, 'error');
      } else {
        addToast('Error simulation failed', 'error');
      }
    } finally {
      setTriggeringId(null);
    }
  };

  const handleTriggerRandom = () => {
    if (scenarios.length === 0) return;
    const randomScenario = scenarios[Math.floor(Math.random() * scenarios.length)];
    handleTrigger(randomScenario.id);
  };

  return (
    <div className="card" style={{ marginBottom: '2rem', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '1.4rem' }}>⚡</span> Cloud Error Log Generator (10 Scenarios)
          </h2>
          <p style={{ fontSize: '0.85rem', color: '#94a3b8', marginTop: '0.25rem' }}>
            Click any button below to trigger and log realistic cloud error entries directly into <code style={{ color: '#60a5fa' }}>application.log</code> for Python AI processing.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={handleTriggerRandom}
          style={{
            background: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
            boxShadow: '0 4px 14px rgba(239, 68, 68, 0.4)',
            whiteSpace: 'nowrap'
          }}
        >
          🎲 Trigger Random Error Log
        </button>
      </div>

      {loading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8' }}>Loading 10 Cloud Error Scenarios…</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.75rem', marginTop: '1rem' }}>
          {scenarios.map((s, idx) => {
            const isTriggering = triggeringId === s.id;
            const isCritical = s.level === 'critical';
            const isWarn = s.level === 'warn';

            const badgeColor = isCritical ? '#ef4444' : isWarn ? '#f59e0b' : '#f97316';

            return (
              <div
                key={s.id}
                style={{
                  background: 'rgba(15, 23, 42, 0.6)',
                  border: `1px solid ${isCritical ? 'rgba(239, 68, 68, 0.4)' : 'rgba(255, 255, 255, 0.08)'}`,
                  borderRadius: '10px',
                  padding: '0.85rem',
                  display: 'flex',
                  flexDirection: 'column',
                  justify: 'space-between',
                  transition: 'all 0.2s ease',
                  position: 'relative'
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, background: 'rgba(255,255,255,0.06)', padding: '2px 8px', borderRadius: '4px', color: '#94a3b8' }}>
                      #{idx + 1} {s.category}
                    </span>
                    <span style={{ fontSize: '0.7rem', fontWeight: 700, color: badgeColor, textTransform: 'uppercase', background: `${badgeColor}15`, padding: '2px 6px', borderRadius: '4px', border: `1px solid ${badgeColor}40` }}>
                      {s.level} ({s.statusCode})
                    </span>
                  </div>

                  <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.3rem' }}>
                    {s.title}
                  </h3>

                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontFamily: 'monospace', marginBottom: '0.6rem', wordBreak: 'break-all' }}>
                    {s.errorType}
                  </div>
                </div>

                <button
                  onClick={() => handleTrigger(s.id)}
                  disabled={isTriggering}
                  className="btn"
                  style={{
                    width: '100%',
                    padding: '0.45rem',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    background: isCritical
                      ? 'linear-gradient(135deg, rgba(239,68,68,0.2) 0%, rgba(220,38,38,0.3) 100%)'
                      : 'linear-gradient(135deg, rgba(249,115,22,0.15) 0%, rgba(234,88,12,0.25) 100%)',
                    color: isCritical ? '#fca5a5' : '#fdba74',
                    border: `1px solid ${isCritical ? 'rgba(239,68,68,0.5)' : 'rgba(249,115,22,0.4)'}`,
                    borderRadius: '6px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.3rem'
                  }}
                >
                  {isTriggering ? (
                    'Logging Error…'
                  ) : (
                    <>
                      <span>💥</span> Trigger {s.level.toUpperCase()} Log
                    </>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {lastTriggered && (
        <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'rgba(239, 68, 68, 0.1)', border: '1px dashed rgba(239, 68, 68, 0.3)', borderRadius: '8px', fontSize: '0.8rem', color: '#fca5a5' }}>
          <strong>Last Logged Error:</strong> <code style={{ color: '#fff' }}>[{lastTriggered.level}] {lastTriggered.errorType}</code> — {lastTriggered.message}
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '2px' }}>
            Logged at {lastTriggered.loggedAt} to <code style={{ color: '#60a5fa' }}>backend/logs/application.log</code>
          </div>
        </div>
      )}
    </div>
  );
}
