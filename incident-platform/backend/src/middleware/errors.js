export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
export function errorHandler(error, req, res, next) {
  if (res.headersSent) return next(error);
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
