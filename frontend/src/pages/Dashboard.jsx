// frontend/src/pages/Dashboard.jsx
// Main dashboard page — orchestrates product CRUD operations

import React, { useState, useEffect, useCallback } from 'react';
import { productApi } from '../services/api';
import ProductForm from '../components/ProductForm';
import ProductTable from '../components/ProductTable';
import ErrorSimulator from '../components/ErrorSimulator';

export default function Dashboard({ addToast, setOnline }) {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  // ── Fetch products ──────────────────────────────────────────────────────────
  const fetchProducts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await productApi.getAll();
      setProducts(res.data.data);
      setOnline(true);
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Failed to fetch products';
      setError(msg);
      setOnline(false);
      addToast(msg, 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast, setOnline]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  // ── Create product ──────────────────────────────────────────────────────────
  const handleCreate = async (data) => {
    setCreating(true);
    try {
      const res = await productApi.create(data);
      setProducts((prev) => [res.data.data, ...prev]);
      addToast(`Product "${res.data.data.name}" created successfully! ✓`, 'success');
      return true;
    } catch (err) {
      const errData = err.response?.data;
      if (errData?.details) {
        addToast(`Validation failed: ${errData.details.join(', ')}`, 'error');
      } else {
        addToast(errData?.error || 'Failed to create product', 'error');
      }
      return false;
    } finally {
      setCreating(false);
    }
  };

  // ── Update product ──────────────────────────────────────────────────────────
  const handleUpdate = async (id, data) => {
    try {
      const res = await productApi.update(id, data);
      setProducts((prev) =>
        prev.map((p) => (p._id === id ? res.data.data : p))
      );
      addToast(`Product updated successfully! ✓`, 'success');
      return true;
    } catch (err) {
      const errData = err.response?.data;
      if (errData?.details) {
        addToast(`Validation failed: ${errData.details.join(', ')}`, 'error');
      } else {
        addToast(errData?.error || 'Failed to update product', 'error');
      }
      return false;
    }
  };

  // ── Delete product ──────────────────────────────────────────────────────────
  const handleDelete = async (id) => {
    try {
      await productApi.remove(id);
      setProducts((prev) => prev.filter((p) => p._id !== id));
      addToast('Product deleted successfully', 'info');
    } catch (err) {
      const msg = err.response?.data?.error || 'Failed to delete product';
      addToast(msg, 'error');
    }
  };

  // ── Stats ───────────────────────────────────────────────────────────────────
  const totalProducts = products.length;
  const avgPrice =
    totalProducts > 0
      ? (products.reduce((sum, p) => sum + p.price, 0) / totalProducts).toFixed(2)
      : '0.00';
  const maxPrice = totalProducts > 0 ? Math.max(...products.map((p) => p.price)).toFixed(2) : '0.00';

  return (
    <>
      {/* ── Hero ── */}
      <div className="hero">
        <div className="hero-badge">🛡️ TCS Hackathon 2026</div>
        <h1>Cloud Incident Monitor</h1>
        <p>
          Manage products, generate structured logs, and automatically detect incidents using the
          Python log-processor pipeline.
        </p>
      </div>

      {/* ── Stats Bar ── */}
      <div className="stats-bar">
        <div className="stat-card">
          <div className="stat-icon blue">📦</div>
          <div className="stat-info">
            <div className="stat-value">{totalProducts}</div>
            <div className="stat-label">Total Products</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon green">💰</div>
          <div className="stat-info">
            <div className="stat-value">${avgPrice}</div>
            <div className="stat-label">Average Price</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon amber">📈</div>
          <div className="stat-info">
            <div className="stat-value">${maxPrice}</div>
            <div className="stat-label">Highest Price</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon blue">📋</div>
          <div className="stat-info">
            <div className="stat-value" style={{ fontSize: 14, color: 'var(--brand-1)' }}>Active</div>
            <div className="stat-label">Log Processor</div>
          </div>
        </div>
      </div>

      {/* ── Error Log Simulator (10 Scenarios) ── */}
      <ErrorSimulator addToast={addToast} />

      {/* ── Error Banner ── */}
      {error && (
        <div className="alert alert-error" role="alert">
          <span style={{ fontSize: 18 }}>⚠️</span>
          <div>
            <strong>Connection Error</strong>
            <div className="alert-message">{error}</div>
            <button
              id="retry-fetch-btn"
              onClick={fetchProducts}
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 8 }}
            >
              ↺ Retry
            </button>
          </div>
        </div>
      )}

      {/* ── Create Product Form ── */}
      <div className="section-header">
        <div>
          <div className="section-title">Product Management</div>
          <div className="section-subtitle">
            Each operation generates a structured Winston log consumed by the Python processor
          </div>
        </div>
        <button
          id="refresh-products-btn"
          className="btn btn-secondary btn-sm"
          onClick={fetchProducts}
          disabled={loading}
        >
          {loading ? <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> : '↺'}
          Refresh
        </button>
      </div>

      <ProductForm onCreate={handleCreate} loading={creating} />

      {/* ── Products Table ── */}
      <ProductTable
        products={products}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        loading={loading}
      />

      {/* ── Log Pipeline Info ── */}
      <div className="card" style={{ marginTop: 'var(--space-xl)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>🔄</span>
          <div>
            <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>Log Processing Pipeline</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Automatic incident detection on ERROR/CRITICAL logs</div>
          </div>
        </div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
        }}>
          {['React', '→', 'Axios', '→', 'Express', '→', 'MongoDB', '→', 'Winston', '→', 'application.log', '→', 'Python Processor', '→', 'Classifier', '→', 'Agent API'].map((item, i) => (
            item === '→' ? (
              <span key={i} style={{ color: 'var(--text-muted)' }}>→</span>
            ) : (
              <span key={i} style={{
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '2px 8px',
                color: item === 'Agent API' ? 'var(--brand-2)' : item === 'Classifier' ? 'var(--success)' : 'var(--text-primary)',
              }}>
                {item}
              </span>
            )
          ))}
        </div>
      </div>
    </>
  );
}
