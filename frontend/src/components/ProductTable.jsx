// frontend/src/components/ProductTable.jsx
// Table displaying all products with inline edit and delete

import React, { useState } from 'react';

function formatDate(dateStr) {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function EditRow({ product, onSave, onCancel, loading }) {
  const [form, setForm] = useState({ name: product.name, price: product.price });
  const [errors, setErrors] = useState({});

  const validate = () => {
    const e = {};
    if (!form.name.trim()) e.name = 'Required';
    if (form.price === '' || isNaN(Number(form.price)) || Number(form.price) < 0)
      e.price = 'Must be ≥ 0';
    return e;
  };

  const handleSave = () => {
    const errs = validate();
    if (Object.keys(errs).length) { setErrors(errs); return; }
    onSave({ name: form.name.trim(), price: Number(form.price) });
  };

  return (
    <tr className="edit-row">
      <td>
        <span className="product-id">{product._id}</span>
      </td>
      <td>
        <input
          id={`edit-name-${product._id}`}
          className="edit-input"
          value={form.name}
          onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
          style={errors.name ? { borderColor: 'var(--error)' } : {}}
          autoFocus
        />
        {errors.name && <span style={{ fontSize: '11px', color: 'var(--error)' }}>{errors.name}</span>}
      </td>
      <td>
        <input
          id={`edit-price-${product._id}`}
          className="edit-input"
          type="number"
          min="0"
          step="0.01"
          value={form.price}
          onChange={(e) => setForm((p) => ({ ...p, price: e.target.value }))}
          style={{ ...(errors.price ? { borderColor: 'var(--error)' } : {}), width: '120px' }}
        />
        {errors.price && <span style={{ fontSize: '11px', color: 'var(--error)' }}>{errors.price}</span>}
      </td>
      <td>{formatDate(product.createdAt)}</td>
      <td>
        <div className="action-buttons">
          <button
            id={`save-product-${product._id}`}
            className="btn btn-success btn-sm"
            onClick={handleSave}
            disabled={loading}
          >
            {loading ? '…' : '✓ Save'}
          </button>
          <button
            id={`cancel-edit-${product._id}`}
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </button>
        </div>
      </td>
    </tr>
  );
}

export default function ProductTable({ products, onUpdate, onDelete, loading }) {
  const [editingId, setEditingId] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);

  const handleEdit = (id) => setEditingId(id);
  const handleCancel = () => setEditingId(null);

  const handleSave = async (id, data) => {
    setActionLoading(id);
    const success = await onUpdate(id, data);
    setActionLoading(null);
    if (success) setEditingId(null);
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this product? This action cannot be undone.')) return;
    setActionLoading(id);
    await onDelete(id);
    setActionLoading(null);
  };

  if (loading && products.length === 0) {
    return (
      <div className="card">
        <table className="products-table">
          <thead>
            <tr>
              <th>ID</th><th>Name</th><th>Price</th><th>Created</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr className="loading-row">
              <td colSpan={5}>
                <div className="spinner" />
                <div style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 13 }}>
                  Loading products…
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  if (!loading && products.length === 0) {
    return (
      <div className="card">
        <div className="empty-state">
          <div className="empty-icon">📦</div>
          <div className="empty-title">No products yet</div>
          <div className="empty-desc">Create your first product using the form above.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="table-wrapper">
        <table className="products-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Price</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.map((product) =>
              editingId === product._id ? (
                <EditRow
                  key={product._id}
                  product={product}
                  onSave={(data) => handleSave(product._id, data)}
                  onCancel={handleCancel}
                  loading={actionLoading === product._id}
                />
              ) : (
                <tr key={product._id}>
                  <td>
                    <span className="product-id">{product._id.slice(-8)}…</span>
                  </td>
                  <td>
                    <span className="product-name">{product.name}</span>
                  </td>
                  <td>
                    <span className="price-badge">${Number(product.price).toFixed(2)}</span>
                  </td>
                  <td>
                    <span className="date-text">{formatDate(product.createdAt)}</span>
                  </td>
                  <td>
                    <div className="action-buttons">
                      <button
                        id={`edit-product-${product._id}`}
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleEdit(product._id)}
                        disabled={actionLoading === product._id || !!editingId}
                      >
                        ✏️ Edit
                      </button>
                      <button
                        id={`delete-product-${product._id}`}
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDelete(product._id)}
                        disabled={actionLoading === product._id}
                      >
                        {actionLoading === product._id ? '…' : '🗑 Delete'}
                      </button>
                    </div>
                  </td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
