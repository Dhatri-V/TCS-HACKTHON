import express from "express";
import mongoose from "mongoose";
import cors from "cors";
import incidents from "./routes/incidents.js";
import { remediationRoutes } from "./routes/remediation.js";
import { databaseHealthy } from "./config/database.js";
import { ApiError, errorHandler } from "./middleware/errors.js";
export function createApp({ frontendOrigin = "http://localhost:5173", remediation = {} } = {}) {
  const app = express();
  app.disable("x-powered-by");
  app.use(cors({ origin: frontendOrigin }));
  app.use(express.json({ limit: "256kb" }));
  app.get("/health", async (req, res) => {
    const healthy = await databaseHealthy();
    res
      .status(healthy ? 200 : 503)
      .json({
        status: healthy ? "healthy" : "unhealthy",
        backend: "up",
        database: healthy ? "connected" : "unavailable",
      });
  });
  app.use(
    "/api/incidents",
    (req, res, next) => {
      // Disable Mongoose buffering and reject outages promptly.
      if (mongoose.connection.readyState !== 1)
        return next(
          new ApiError(
            503,
            "DATABASE_UNAVAILABLE",
            "Database unavailable; try again later",
          ),
        );
      next();
    },
    remediationRoutes({ ...remediation, frontendOrigin }),
    incidents,
  );
  app.use((req, res, next) =>
    next(new ApiError(404, "NOT_FOUND", "Route not found")),
  );
  app.use(errorHandler);
  return app;
}
