// backend/src/middleware/errorMiddleware.js
// Centralized Express error handler
// All unhandled errors from controllers reach here via next(error)
// Logs the error using Winston, then sends a clean JSON response

const logger = require('../utils/logger');

const errorMiddleware = (err, req, res, next) => {
  // Determine appropriate HTTP status code
  let statusCode = err.statusCode || err.status || 500;

  // Mongoose CastError (e.g., invalid ObjectId passed through)
  if (err.name === 'CastError') {
    statusCode = 400;
  }

  // MongoDB duplicate key error
  if (err.code === 11000) {
    statusCode = 409;
  }

  // Mongoose validation error
  if (err.name === 'ValidationError') {
    statusCode = 422;
  }

  // Log the error — but NEVER expose stack traces or credentials
  logger.error(err.message || 'Unexpected server error', {
    method: req.method,
    endpoint: req.originalUrl,
    statusCode,
    errorType: err.name || 'UnknownError',
    message: err.message,
  });

  // Build a clean response — no stack traces exposed to frontend
  const response = {
    success: false,
    error: getClientMessage(err, statusCode),
  };

  // In development, add errorType for easier debugging (still no stack trace)
  if (process.env.NODE_ENV === 'development') {
    response.errorType = err.name;
  }

  res.status(statusCode).json(response);
};

/**
 * Map internal errors to safe, user-facing messages.
 */
function getClientMessage(err, statusCode) {
  switch (statusCode) {
    case 400:
      return 'Bad request — check your input';
    case 404:
      return 'Resource not found';
    case 409:
      return 'Conflict — duplicate resource';
    case 422:
      return err.message || 'Validation failed';
    case 500:
    default:
      return 'Internal server error — please try again later';
  }
}

module.exports = errorMiddleware;
