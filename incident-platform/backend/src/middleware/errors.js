export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
export function errorHandler(error, req, res, next) {
  if (res.headersSent) return next(error);
  const status = error instanceof ApiError ? error.status
    : error.code === 11000 ? 409
      : error.type === "entity.too.large" ? 413
        : error.type === "entity.parse.failed" || ["ValidationError", "CastError", "StrictModeError"].includes(error.name) ? 400
          : /Mongo|MongooseServerSelection/.test(error.name) ? 503 : 500;
  const code = error instanceof ApiError ? error.code
    : error.code === 11000 ? "INCIDENT_EXISTS"
      : error.type === "entity.too.large" ? "BODY_TOO_LARGE"
        : status === 400 ? "INVALID_REQUEST"
          : status === 503 ? "DATABASE_UNAVAILABLE" : "INTERNAL_ERROR";
  operationalLog(status >= 500 ? "error" : "warn", "request_failed", {
    method: req.method, status_code: status, error_code: code,
  });
  if (error instanceof ApiError)
    return res
      .status(error.status)
      .json({ error: { code: error.code, message: error.message } });
  if (error.code === 11000)
    return res
      .status(409)
      .json({
        error: {
          code: "INCIDENT_EXISTS",
          message: "incident_id already exists",
        },
      });
  if (error.type === "entity.too.large")
    return res
      .status(413)
      .json({
        error: { code: "BODY_TOO_LARGE", message: "JSON body exceeds 256 KB" },
      });
  if (
    error.type === "entity.parse.failed" ||
    ["ValidationError", "CastError", "StrictModeError"].includes(error.name)
  ) {
    return res
      .status(400)
      .json({
        error: {
          code: "INVALID_REQUEST",
          message: "Invalid JSON or incident data",
        },
      });
  }
  if (/Mongo|MongooseServerSelection/.test(error.name))
    return res
      .status(503)
      .json({
        error: {
          code: "DATABASE_UNAVAILABLE",
          message: "Database unavailable; try again later",
        },
      });
  res
    .status(500)
    .json({
      error: { code: "INTERNAL_ERROR", message: "Unexpected server error" },
    });
}
import { operationalLog } from "../utils/logger.js";
