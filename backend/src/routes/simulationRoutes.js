// backend/src/routes/simulationRoutes.js
// Routes for triggering and simulating 10 distinct cloud error logs

const express = require('express');
const router = express.Router();
const logger = require('../utils/logger');

// Define 10 realistic cloud log error scenarios
const ERROR_SCENARIOS = [
  {
    id: 'DATABASE_TIMEOUT',
    title: 'Database Timeout Error',
    level: 'error',
    statusCode: 504,
    errorType: 'MongoNetworkTimeoutError',
    message: 'MongoDB query operation timed out after 5000ms on shard ac-onwutx1-shard-00-00',
    endpoint: '/api/products',
    method: 'GET',
    category: 'Database'
  },
  {
    id: 'AUTH_EXPIRED',
    title: 'JWT Authentication Expired',
    level: 'warn',
    statusCode: 401,
    errorType: 'TokenExpiredError',
    message: 'JWT token expired at 2026-09-25T22:00:00Z. Signature verification failed for user_id: usr_99482',
    endpoint: '/api/auth/verify',
    method: 'POST',
    category: 'Security'
  },
  {
    id: 'MEMORY_EXCEEDED',
    title: 'Heap Out of Memory',
    level: 'critical',
    statusCode: 500,
    errorType: 'HeapOutOfMemoryError',
    message: 'Node.js process allocation failed — JavaScript heap out of memory (used: 1420MB, limit: 1432MB)',
    endpoint: '/api/reports/generate',
    method: 'POST',
    category: 'Infrastructure'
  },
  {
    id: 'PAYMENT_GATEWAY_DOWN',
    title: 'Payment Gateway Down',
    level: 'error',
    statusCode: 503,
    errorType: 'ThirdPartyServiceUnavailable',
    message: 'Stripe API call failed — 503 Service Unavailable (connect ETIMEDOUT 54.187.205.47:443)',
    endpoint: '/api/checkout/process',
    method: 'POST',
    category: 'External Services'
  },
  {
    id: 'RATE_LIMIT_EXCEEDED',
    title: 'Rate Limit Exceeded',
    level: 'warn',
    statusCode: 429,
    errorType: 'TooManyRequestsError',
    message: 'Client 192.168.1.105 exceeded rate limit threshold of 100 requests per minute',
    endpoint: '/api/products',
    method: 'GET',
    category: 'Network / Security'
  },
  {
    id: 'DISK_FULL',
    title: 'Disk Space Full (ENOSPC)',
    level: 'critical',
    statusCode: 507,
    errorType: 'ENOSPC',
    message: 'No space left on device while writing log buffer to /var/log/application.log (0 bytes remaining)',
    endpoint: '/api/system/log-flush',
    method: 'POST',
    category: 'Infrastructure'
  },
  {
    id: 'MICROSERVICE_UNREACHABLE',
    title: 'Microservice Unreachable',
    level: 'error',
    statusCode: 502,
    errorType: 'ECONNREFUSED',
    message: 'Service discovery failed for dependency inventory-service:8080 — Connection refused',
    endpoint: '/api/inventory/sync',
    method: 'GET',
    category: 'Microservices'
  },
  {
    id: 'NULL_POINTER',
    title: 'Null Pointer / Undefined Property',
    level: 'error',
    statusCode: 500,
    errorType: 'TypeError',
    message: "Unhandled Exception: Cannot read properties of undefined (reading 'tenant_id') at Object.createProduct",
    endpoint: '/api/products',
    method: 'POST',
    category: 'Application Bug'
  },
  {
    id: 'DEADLOCK_DETECTED',
    title: 'Database Transaction Deadlock',
    level: 'error',
    statusCode: 409,
    errorType: 'TransactionDeadlockError',
    message: 'Deadlock detected during concurrent update on products collection (Lock acquire timeout: 10000ms)',
    endpoint: '/api/products/batch-update',
    method: 'PUT',
    category: 'Database'
  },
  {
    id: 'CRITICAL_SECURITY_ALERT',
    title: 'SQL Injection / Malicious Payload Alert',
    level: 'critical',
    statusCode: 403,
    errorType: 'SecurityPolicyViolation',
    message: 'Malicious payload pattern matching SQL/NoSQL injection detected in request header X-Forwarded-For',
    endpoint: '/api/products/search',
    method: 'POST',
    category: 'Security'
  }
];

/**
 * GET /api/simulate-errors
 * Returns list of 10 available error scenarios
 */
router.get('/', (req, res) => {
  res.json({
    success: true,
    scenarios: ERROR_SCENARIOS
  });
});

/**
 * POST /api/simulate-errors/trigger
 * Body: { type: "DATABASE_TIMEOUT" } or empty for random
 * Triggers and writes the corresponding error to application.log via Winston
 */
router.post('/trigger', (req, res) => {
  const { type } = req.body || {};
  let target = ERROR_SCENARIOS.find(s => s.id === type);

  if (!target) {
    // Pick random scenario if type is invalid or unspecified
    const randomIndex = Math.floor(Math.random() * ERROR_SCENARIOS.length);
    target = ERROR_SCENARIOS[randomIndex];
  }

  const logMeta = {
    timestamp: new Date().toISOString(),
    service: 'backend',
    message: target.message,
    method: target.method,
    endpoint: target.endpoint,
    statusCode: target.statusCode,
    errorType: target.errorType,
    category: target.category,
    simulated: true
  };

  // Write log to application.log using Winston according to level
  if (target.level === 'critical') {
    logger.error(`[CRITICAL SIMULATED ERROR] ${target.message}`, logMeta);
  } else if (target.level === 'error') {
    logger.error(target.message, logMeta);
  } else {
    logger.warn(target.message, logMeta);
  }

  res.status(target.statusCode < 500 ? target.statusCode : 500).json({
    success: false,
    simulated: true,
    error: {
      id: target.id,
      title: target.title,
      level: target.level.toUpperCase(),
      statusCode: target.statusCode,
      errorType: target.errorType,
      message: target.message,
      category: target.category,
      loggedAt: logMeta.timestamp
    }
  });
});

module.exports = router;
