// frontend/src/components/ProductForm.jsx
// Form for creating new products

import React, { useState } from 'react';

const initialState = { name: '', price: '' };

export default function ProductForm({ onCreate, loading }) {
  const [form, setForm] = useState(initialState);
  const [errors, setErrors] = useState({});

  const validate = () => {
    const newErrors = {};
    if (!form.name.trim()) {
      newErrors.name = 'Product name is required';
    }
    if (form.price === '') {
      newErrors.price = 'Price is required';
    } else if (isNaN(Number(form.price)) || Number(form.price) < 0) {
      newErrors.price = 'Price must be a non-negative number';
    }
    return newErrors;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationErrors = validate();
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }
    setErrors({});
    const success = await onCreate({ name: form.name.trim(), price: Number(form.price) });
    if (success) {
      setForm(initialState);
    }
  };

  const handleChange = (field) => (e) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: '' }));
    }
  };

  return (
    <div className="form-card">
      <div className="form-title">
        <span>➕</span>
        <span>Add New Product</span>
      </div>

      <form onSubmit={handleSubmit} noValidate id="create-product-form">
        <div className="form-grid">
          {/* Name */}
          <div className="form-group">
            <label className="form-label" htmlFor="product-name">
              Product Name
            </label>
            <input
              id="product-name"
              type="text"
              className={`form-input ${errors.name ? 'error-input' : ''}`}
              placeholder="e.g. Cloud Monitor Pro"
              value={form.name}
              onChange={handleChange('name')}
              disabled={loading}
              autoComplete="off"
            />
            {errors.name && (
              <span style={{ fontSize: '11px', color: 'var(--error)', marginTop: '2px' }}>
                {errors.name}
              </span>
            )}
          </div>

          {/* Price */}
          <div className="form-group">
            <label className="form-label" htmlFor="product-price">
              Price (USD)
            </label>
            <input
              id="product-price"
              type="number"
              className={`form-input ${errors.price ? 'error-input' : ''}`}
              placeholder="e.g. 99.99"
              value={form.price}
              onChange={handleChange('price')}
              min="0"
              step="0.01"
              disabled={loading}
            />
            {errors.price && (
              <span style={{ fontSize: '11px', color: 'var(--error)', marginTop: '2px' }}>
                {errors.price}
              </span>
            )}
          </div>

          {/* Submit */}
          <div className="form-group">
            <button
              id="submit-create-product"
              type="submit"
              className="btn btn-primary"
              disabled={loading}
              style={{ height: '40px' }}
            >
              {loading ? (
                <>
                  <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                  Creating…
                </>
              ) : (
                'Create Product'
              )}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
