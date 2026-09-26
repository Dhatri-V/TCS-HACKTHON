import winston from "winston";

// Adapted from PR #6's Winston logger for the existing incident API. Callers
// can emit only this small operational field set; request bodies, credentials,
// database URIs, exception messages and remediation tokens are never logged.
const stringFields = new Set([
  "error_code",
  "incident_id",
  "method",
  "remediation_state",
  "service",
  "signal",
]);
const numberFields = new Set(["duration_ms", "port", "status_code"]);

export function sanitizeOperationalFields(fields = {}) {
  const safe = {};
  for (const [key, value] of Object.entries(fields)) {
    if (stringFields.has(key) && typeof value === "string" && value.length <= 160)
      safe[key] = value;
    if (numberFields.has(key) && Number.isFinite(value)) safe[key] = value;
  }
  return safe;
}

export function createOperationalLogger({ transports } = {}) {
  return winston.createLogger({
    level: "info",
    format: winston.format.combine(
      winston.format.timestamp(),
      winston.format.json(),
    ),
    transports: transports || [new winston.transports.Console()],
  });
}

export const logger = createOperationalLogger();

export function operationalLog(level, event, fields = {}) {
  logger.log({
    level,
    message: event,
    event,
    service: "incident-platform-backend",
    ...sanitizeOperationalFields(fields),
  });
}
