import "dotenv/config";
import mongoose from "mongoose";
import { createApp } from "./src/app.js";
import { connectDatabase } from "./src/config/database.js";
import { operationalLog } from "./src/utils/logger.js";
const port = Number(process.env.PORT || 3000);
if (!Number.isInteger(port) || port < 1 || port > 65535)
  throw new Error("Invalid PORT");
try {
  await connectDatabase(process.env.MONGODB_URI);
  const server = createApp({
    frontendOrigin: process.env.FRONTEND_ORIGIN,
  }).listen(port, process.env.HOST || "127.0.0.1", () =>
    operationalLog("info", "backend_started", { port }),
  );
  server.on("error", async () => {
    operationalLog("error", "http_server_failed");
    await mongoose.disconnect();
    process.exitCode = 1;
  });
  for (const signal of ["SIGINT", "SIGTERM"])
    process.once(signal, () => {
      operationalLog("info", "shutdown_requested", { signal });
      const timer = setTimeout(() => process.exit(1), 10000);
      timer.unref();
      server.close(async () => {
        await mongoose.disconnect();
        clearTimeout(timer);
      });
    });
} catch {
  operationalLog("error", "database_startup_failed", {
    error_code: "DATABASE_UNAVAILABLE",
  });
  await mongoose.disconnect();
  process.exitCode = 1;
}
