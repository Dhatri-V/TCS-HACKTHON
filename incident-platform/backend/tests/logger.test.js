import { test } from "node:test";
import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import winston from "winston";
import {
  createOperationalLogger,
  sanitizeOperationalFields,
} from "../src/utils/logger.js";

test("operational field sanitizer keeps allowlisted metadata only", () => {
  assert.deepEqual(
    sanitizeOperationalFields({
      method: "POST",
      status_code: 503,
      incident_id: "INC-DEMO-001",
      token: "never-log-this",
      password: "never-log-this",
      body: { Authorization: "Bearer never-log-this" },
      error_message: "mongodb://user:password@host/database",
    }),
    { method: "POST", status_code: 503, incident_id: "INC-DEMO-001" },
  );
});

test("Winston emits parseable structured JSON without secret fields", async () => {
  const stream = new PassThrough();
  let output = "";
  stream.on("data", chunk => { output += chunk; });
  const logger = createOperationalLogger({
    transports: [new winston.transports.Stream({ stream })],
  });
  logger.info("request_completed", {
    event: "request_completed",
    ...sanitizeOperationalFields({ method: "GET", status_code: 200, token: "secret" }),
  });
  await new Promise(resolve => logger.on("finish", resolve).end());
  const record = JSON.parse(output.trim());
  assert.equal(record.event, "request_completed");
  assert.equal(record.method, "GET");
  assert.equal(record.status_code, 200);
  assert.equal(record.token, undefined);
  assert.match(record.timestamp, /^\d{4}-\d{2}-\d{2}T/);
});
