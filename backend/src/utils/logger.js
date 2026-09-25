// backend/src/utils/logger.js
// Winston structured JSON logger
// Writes to both console (dev) and application.log file

const { createLogger, format, transports } = require('winston');
const path = require('path');
const fs = require('fs');

// Ensure logs directory exists
const logsDir = path.join(__dirname, '../../logs');
if (!fs.existsSync(logsDir)) {
  fs.mkdirSync(logsDir, { recursive: true });
}

const LOG_FILE = path.join(logsDir, 'application.log');

// Custom format: structured JSON log with all important fields
const structuredJsonFormat = format.combine(
  format.timestamp({ format: 'YYYY-MM-DDTHH:mm:ss.SSSZ' }),
  format.errors({ stack: false }), // do not expose stack traces in output
  format.printf((info) => {
    // Build a clean, flat JSON log entry
    const logEntry = {
      timestamp: info.timestamp,
      level: info.level,
      service: info.service || 'backend',
      message: info.message,
    };

    // Attach optional structured fields if present
    if (info.method)      logEntry.method      = info.method;
    if (info.endpoint)    logEntry.endpoint    = info.endpoint;
    if (info.statusCode)  logEntry.statusCode  = info.statusCode;
    if (info.errorType)   logEntry.errorType   = info.errorType;
    if (info.requestId)   logEntry.requestId   = info.requestId;
    if (info.durationMs)  logEntry.durationMs  = info.durationMs;

    // NOTE: Never log passwords, tokens, API keys, credentials
    return JSON.stringify(logEntry);
  })
);

// Console format for development readability
const consoleFormat = format.combine(
  format.colorize(),
  format.timestamp({ format: 'HH:mm:ss' }),
  format.printf((info) => {
    let line = `[${info.timestamp}] ${info.level}: ${info.message}`;
    if (info.method && info.endpoint) {
      line += ` | ${info.method} ${info.endpoint}`;
    }
    if (info.statusCode) {
      line += ` → ${info.statusCode}`;
    }
    if (info.errorType) {
      line += ` (${info.errorType})`;
    }
    return line;
  })
);

const logger = createLogger({
  level: 'info',
  defaultMeta: { service: 'backend' },
  transports: [
    // Write JSON structured logs to file (used by Python log processor)
    new transports.File({
      filename: LOG_FILE,
      format: structuredJsonFormat,
    }),

    // Human-readable output to console during development
    new transports.Console({
      format: consoleFormat,
      silent: process.env.NODE_ENV === 'test',
    }),
  ],
});

module.exports = logger;
