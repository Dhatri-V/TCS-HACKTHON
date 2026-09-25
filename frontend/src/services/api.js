// frontend/src/services/api.js
// Axios instance configured to talk to the Express backend
// All product API calls live here — keeps components clean

import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ── Product API calls ──────────────────────────────────────────────────────────

export const productApi = {
  /**
   * GET /api/products
   */
  getAll: () => api.get('/api/products'),

  /**
   * GET /api/products/:id
   */
  getById: (id) => api.get(`/api/products/${id}`),

  /**
   * POST /api/products
   * @param {{ name: string, price: number }} data
   */
  create: (data) => api.post('/api/products', data),

  /**
   * PUT /api/products/:id
   */
  update: (id, data) => api.put(`/api/products/${id}`, data),

  /**
   * DELETE /api/products/:id
   */
  remove: (id) => api.delete(`/api/products/${id}`),
};

// ── Error Simulator API calls ──────────────────────────────────────────────────

export const simulationApi = {
  /**
   * GET /api/simulate-errors
   */
  getScenarios: () => api.get('/api/simulate-errors'),

  /**
   * POST /api/simulate-errors/trigger
   * @param {string} type
   */
  triggerError: (type) => api.post('/api/simulate-errors/trigger', { type }),
};

export default api;
