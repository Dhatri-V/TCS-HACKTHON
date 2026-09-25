// backend/index.js
// Express server entry point
// Starts the server, connects to MongoDB, mounts routes

require('dotenv').config(); // load .env first

const express = require('express');
const cors = require('cors');
const swaggerJsdoc = require('swagger-jsdoc');
const swaggerUi = require('swagger-ui-express');

const connectDB = require('./src/utils/db');
const logger = require('./src/utils/logger');
const productRoutes = require('./src/routes/productRoutes');
const simulationRoutes = require('./src/routes/simulationRoutes');
const errorMiddleware = require('./src/middleware/errorMiddleware');

// ─── App Setup ────────────────────────────────────────────────────────────────
const app = express();
const PORT = process.env.PORT || 5000;

// ─── Middleware ───────────────────────────────────────────────────────────────
app.use(cors({
  origin: true, // allow all origins — fine for hackathon/dev; restrict in production
  credentials: true,
}));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ─── Swagger / OpenAPI Documentation ─────────────────────────────────────────
/**
 * @swagger
 * components:
 *   schemas:
 *     Product:
 *       type: object
 *       properties:
 *         _id:
 *           type: string
 *           example: "64f3a2b1c7e8a9d1234abcde"
 *         name:
 *           type: string
 *           example: "Cloud Monitoring Pro"
 *         price:
 *           type: number
 *           example: 99.99
 *         createdAt:
 *           type: string
 *           format: date-time
 *         updatedAt:
 *           type: string
 *           format: date-time
 *     ProductInput:
 *       type: object
 *       required:
 *         - name
 *         - price
 *       properties:
 *         name:
 *           type: string
 *           example: "Cloud Monitoring Pro"
 *         price:
 *           type: number
 *           minimum: 0
 *           example: 99.99
 */

const swaggerOptions = {
  definition: {
    openapi: '3.0.0',
    info: {
      title: 'TCS Cloud Incident Monitor API',
      version: '1.0.0',
      description:
        'REST API for the TCS Cloud Incident Monitor — manages products and generates structured logs consumed by the Python log processor.',
    },
    servers: [
      {
        url: `http://localhost:${PORT}`,
        description: 'Development server',
      },
    ],
  },
  apis: ['./index.js', './src/routes/*.js'],
};

const swaggerSpec = swaggerJsdoc(swaggerOptions);
app.use('/api-docs', swaggerUi.serve, swaggerUi.setup(swaggerSpec, {
  customSiteTitle: 'TCS Incident Monitor API Docs',
}));

// ─── Routes ───────────────────────────────────────────────────────────────────
app.use('/api/products', productRoutes);
app.use('/api/simulate-errors', simulationRoutes);

// Health check endpoint
app.get('/health', (req, res) => {
  logger.info('Health check', { method: 'GET', endpoint: '/health', statusCode: 200 });
  res.status(200).json({ status: 'ok', service: 'tcs-cloud-incident-monitor' });
});

// 404 handler for unknown routes
app.use((req, res) => {
  logger.warn(`Route not found: ${req.method} ${req.originalUrl}`, {
    method: req.method,
    endpoint: req.originalUrl,
    statusCode: 404,
    errorType: 'RouteNotFound',
    message: 'The requested endpoint does not exist',
  });
  res.status(404).json({ success: false, error: 'Route not found' });
});

// ─── Centralized Error Handler ────────────────────────────────────────────────
// Must be registered AFTER all routes
app.use(errorMiddleware);

// ─── Start Server ─────────────────────────────────────────────────────────────
const startServer = async () => {
  await connectDB();

  app.listen(PORT, () => {
    logger.info(`Server running on http://localhost:${PORT}`, { service: 'server' });
    logger.info(`Swagger docs at http://localhost:${PORT}/api-docs`, { service: 'server' });
  });
};

startServer();
