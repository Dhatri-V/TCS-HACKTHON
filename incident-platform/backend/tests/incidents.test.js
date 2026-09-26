import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import mongoose from "mongoose";
import { MongoMemoryServer } from "mongodb-memory-server";
import { createApp } from "../src/app.js";
import { connectDatabase } from "../src/config/database.js";
import { Incident } from "../src/models/Incident.js";
const app = createApp();
let mongo;
const incident = (overrides = {}) => ({
  incident_id: "INC-001",
  timestamp: "2026-09-25T10:30:00",
  service: "payment-service",
  log_level: "error",
  message: "MongoDB connection timeout",
  classification: "ERROR",
  ...overrides,
});
const analysis = (overrides = {}) => ({
  incident_id: "INC-001",
  status: "completed",
  probable_root_cause: "Connection pool may be exhausted",
  explanation: "The service could not obtain a connection [LOG-1].",
  remediation_steps: ["Inspect active database connections"],
  configuration_changes: [],
  references: ["LOG-1"],
  missing_information: [],
  ...overrides,
});
before(async () => {
  mongo = await MongoMemoryServer.create();
  await connectDatabase(mongo.getUri("incident_platform_test"));
});
after(async () => {
  await mongoose.disconnect();
  await mongo?.stop();
});
beforeEach(async () => {
  await Incident.deleteMany({});
});
const create = async (data = incident()) =>
  request(app).post("/api/incidents").send(data);

test("create persists contract, defaults and UTC timestamp without leaking Mongo internals", async () => {
  const res = await create();
  assert.equal(res.status, 201);
  assert.equal(res.body.status, "INVESTIGATING");
  assert.equal(res.body.analysis, null);
  assert.equal(res.body.timestamp, "2026-09-25T10:30:00.000Z");
  assert.equal(res.body._id, undefined);
  assert.equal(
    (await Incident.findOne({ incident_id: "INC-001" })).service,
    "payment-service",
  );
});
test("required fields reject missing and non-string values", async () => {
  for (const field of [
    "incident_id",
    "timestamp",
    "service",
    "log_level",
    "message",
    "classification",
  ]) {
    const data = incident();
    delete data[field];
    assert.equal((await create(data)).status, 400);
    assert.equal((await create(incident({ [field]: 42 }))).status, 400);
  }
});
test("duplicate incident_id returns conflict, including concurrent requests", async () => {
  const responses = await Promise.all([create(), create()]);
  assert.deepEqual(responses.map((r) => r.status).sort(), [201, 409]);
});
test("list is newest first and get uses public incident_id", async () => {
  await create();
  await create(
    incident({ incident_id: "INC-002", timestamp: "2026-09-26T12:00:00Z" }),
  );
  const list = await request(app).get("/api/incidents");
  assert.equal(list.status, 200);
  assert.deepEqual(
    list.body.map((i) => i.incident_id),
    ["INC-002", "INC-001"],
  );
  const get = await request(app).get("/api/incidents/INC-001");
  assert.equal(get.status, 200);
  assert.equal(get.body.message, incident().message);
  const stored = await Incident.findOne({ incident_id: "INC-001" });
  assert.equal(
    (await request(app).get(`/api/incidents/${stored._id}`)).status,
    404,
  );
});
test("nonexistent incident and unknown route return JSON 404", async () => {
  for (const path of ["/api/incidents/missing", "/no-route"]) {
    const res = await request(app).get(path);
    assert.equal(res.status, 404);
    assert.equal(res.body.error.code, "NOT_FOUND");
  }
});
test("analysis patch preserves exact fields and additive reasoner metadata", async () => {
  await create();
  const data = analysis({
    grounded_claims: [{ evidence_id: "LOG-1", claim: "Connection failed" }],
    remediation_metadata: [{ approval_eligible: false, executable: false }],
  });
  const res = await request(app)
    .patch("/api/incidents/INC-001/analysis")
    .send(data);
  assert.equal(res.status, 200);
  assert.deepEqual(res.body.analysis, data);
  assert.equal(res.body.status, "INVESTIGATING");
  assert.deepEqual(
    (await request(app).get("/api/incidents/INC-001")).body.analysis,
    data,
  );
});
test("insufficient_evidence with null cause is supported", async () => {
  await create();
  const res = await request(app)
    .patch("/api/incidents/INC-001/analysis")
    .send(
      analysis({
        status: "insufficient_evidence",
        probable_root_cause: null,
        missing_information: ["Database logs"],
      }),
    );
  assert.equal(res.status, 200);
});
test("mismatched incident_id rejected on create and analysis patch", async () => {
  assert.equal(
    (await create(incident({ analysis: analysis({ incident_id: "INC-999" }) })))
      .status,
    400,
  );
  await create();
  assert.equal(
    (
      await request(app)
        .patch("/api/incidents/INC-001/analysis")
        .send(analysis({ incident_id: "INC-999" }))
    ).status,
    400,
  );
  assert.equal((await Incident.findOne()).analysis, null);
});
test("invalid analysis structure and unsafe nested keys rejected", async () => {
  await create();
  for (const data of [
    null,
    [],
    {},
    analysis({ references: "LOG-1" }),
    analysis({ status: "success" }),
    analysis({ explanation: "" }),
    analysis({ probable_root_cause: null }),
    analysis({ extra: { $set: "unsafe" } }),
  ]) {
    assert.equal(
      (
        await request(app)
          .patch("/api/incidents/INC-001/analysis")
          .set("Content-Type", "application/json")
          .send(JSON.stringify(data))
      ).status,
      400,
    );
  }
});
test("legacy lifecycle updates cannot bypass verified resolution", async () => {
  await create();
  for (const status of [
    "INVESTIGATING",
    "DIAGNOSED",
    "PENDING_APPROVAL",
    "REMEDIATING",
    "RESOLVED",
    "FAILED",
  ]) {
    const res = await request(app)
      .patch("/api/incidents/INC-001/status")
      .send({ status });
    assert.equal(res.status, status === "RESOLVED" ? 409 : 200);
    if (status !== "RESOLVED") assert.equal(res.body.status, status);
  }
});
test("invalid status and extra fields rejected", async () => {
  await create();
  for (const data of [
    { status: "APPROVED" },
    { status: null },
    {},
    { status: "RESOLVED", command: "shell" },
  ])
    assert.equal(
      (await request(app).patch("/api/incidents/INC-001/status").send(data))
        .status,
      400,
    );
  assert.equal(
    (await create(incident({ incident_id: "INC-002", status: "BAD" }))).status,
    400,
  );
  assert.equal(
    (await create(incident({ incident_id: "INC-002", unexpected: true })))
      .status,
    400,
  );
});
test("patches on nonexistent incidents return 404", async () => {
  assert.equal(
    (
      await request(app)
        .patch("/api/incidents/INC-001/status")
        .send({ status: "RESOLVED" })
    ).status,
    404,
  );
  assert.equal(
    (
      await request(app)
        .patch("/api/incidents/INC-001/analysis")
        .send(analysis())
    ).status,
    404,
  );
});
test("invalid timestamp, ID and query operator input rejected", async () => {
  for (const data of [
    incident({ timestamp: "yesterday" }),
    incident({ timestamp: "2026-02-30T10:00:00Z" }),
    incident({ incident_id: "bad/id" }),
    incident({ service: { $ne: null } }),
  ])
    assert.equal((await create(data)).status, 400);
});
test("malformed and oversized JSON return safe errors without stack traces", async () => {
  for (const [data, status] of [
    ["{", 400],
    [JSON.stringify(incident({ message: "a".repeat(300000) })), 413],
  ]) {
    const res = await request(app)
      .post("/api/incidents")
      .set("Content-Type", "application/json")
      .send(data);
    assert.equal(res.status, status);
    assert.deepEqual(Object.keys(res.body), ["error"]);
    assert.equal(res.body.error.stack, undefined);
  }
});
test("health pings actual database and configured CORS origin is returned", async () => {
  const res = await request(app)
    .get("/health")
    .set("Origin", "http://localhost:5173");
  assert.equal(res.status, 200);
  assert.equal(res.body.database, "connected");
  assert.equal(
    res.headers["access-control-allow-origin"],
    "http://localhost:5173",
  );
});
test("database outage reports unhealthy and blocks API without leaking connection details", async () => {
  await mongoose.disconnect();
  try {
    const res = await request(app).get("/health");
    assert.equal(res.status, 503);
    assert.equal(res.body.database, "unavailable");
    const api = await request(app).get("/api/incidents");
    assert.equal(api.status, 503);
    assert.equal(api.body.error.code, "DATABASE_UNAVAILABLE");
  } finally {
    await connectDatabase(mongo.getUri("incident_platform_test"));
  }
});
