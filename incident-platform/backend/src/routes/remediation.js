import { Router } from "express";
import { randomUUID, timingSafeEqual, createHash } from "node:crypto";
import { Incident } from "../models/Incident.js";
import { ApiError } from "../middleware/errors.js";
import { remediationWorker } from "../services/remediationWorker.js";
import { operationalLog } from "../utils/logger.js";

const fail = (status, code, message) => { throw new ApiError(status, code, message); };
const exact = (body, names) => body && typeof body === "object" && !Array.isArray(body)
  && Object.keys(body).length === names.length && names.every(k => Object.hasOwn(body, k));
const hash = text => createHash("sha256").update(text).digest();
const found = incident => incident || fail(404, "NOT_FOUND", "Incident not found");
const publicState = incident => incident.remediation || null;
const readinessNames = ["health_check_ready", "impact_reviewed",
  "rollback_plan_verified", "target_scope_reviewed"];
const scope = incident => {
  if (incident.incident_id !== "INC-DEMO-001" || incident.service !== "orders-api")
    fail(409, "OUTSIDE_DEMO_SCOPE", "Only the orders-api incident INC-DEMO-001 is enabled for demo remediation.");
};
const persistedProposal = remediation => {
  const proposal = remediation?.proposal;
  if (!proposal || typeof proposal !== "object" || Array.isArray(proposal))
    fail(409, "INVALID_PERSISTED_PROPOSAL", "The persisted remediation proposal is invalid.");
  if (Object.hasOwn(proposal, "parameters")) return proposal;
  const keys = Object.keys(proposal).sort();
  const legacyRestartKeys = ["action_id", "action_type", "description", "incident_id", "service"].sort();
  if (JSON.stringify(keys) !== JSON.stringify(legacyRestartKeys)
      || proposal.action_type !== "restart_service" || proposal.service !== "postgres")
    fail(409, "INVALID_PERSISTED_PROPOSAL", "The persisted remediation proposal is invalid.");
  // Mongoose previously minimized the contract's required empty object. The
  // worker recomputes the full proposal fingerprint, so this repair succeeds
  // only when {} is exactly what the stored fingerprint originally bound.
  return { ...proposal, parameters: {} };
};

export function remediationRoutes({ worker = remediationWorker, operatorToken = process.env.REMEDIATION_OPERATOR_TOKEN,
  frontendOrigin = "http://localhost:5173" } = {}) {
  const router = Router();
  router.get("/:id/remediation", async (req, res) => {
    res.json(publicState(found(await Incident.findOne({ incident_id: req.params.id }))));
  });
  router.use("/:id/remediation", (req, res, next) => {
    if (req.method === "GET") return next();
    if (!operatorToken || operatorToken.length < 32)
      return next(new ApiError(503, "OPERATOR_NOT_CONFIGURED", "Configure a remediation operator token of at least 32 characters on the backend."));
    if (req.get("Origin") && req.get("Origin") !== frontendOrigin)
      return next(new ApiError(403, "ORIGIN_REJECTED", "Untrusted approval origin."));
    const supplied = req.get("Authorization") || "";
    if (!timingSafeEqual(hash(supplied), hash(`Bearer ${operatorToken}`)))
      return next(new ApiError(401, "OPERATOR_REQUIRED", "Operator authentication required."));
    next();
  });
  router.post("/:id/remediation/proposal", async (req, res) => {
    if (!exact(req.body, [])) fail(400, "INVALID_REQUEST", "Proposal accepts an empty object only.");
    const incident = found(await Incident.findOne({ incident_id: req.params.id }));
    scope(incident);
    if (incident.status !== "DIAGNOSED" || !incident.analysis || incident.remediation)
      fail(409, "PROPOSAL_NOT_ALLOWED", "A diagnosed incident without an existing remediation attempt is required.");
    const actionId = randomUUID();
    const reserved = await Incident.findOneAndUpdate({ incident_id: req.params.id, status: "DIAGNOSED", remediation: null },
      { $set: { remediation: { state: "PREPARING", action_id: actionId, created_at: new Date().toISOString() } } }, { new: true });
    if (!reserved) fail(409, "ALREADY_RESERVED", "A remediation proposal is already reserved.");
    let result;
    try {
      result = await worker({ operation: "prepare", incident: incident.toJSON(), action_id: actionId });
      if (result.proposal.action_id !== actionId || result.proposal.incident_id !== incident.incident_id
          || result.proposal.service !== "postgres" || result.proposal.action_type !== "restart_service"
          || result.state !== "BLOCKED"
          || !/^[a-f0-9]{64}$/.test(result.action.proposal_fingerprint)
          || result.action.approval_eligible !== false) throw new Error();
    } catch {
      await Incident.updateOne({ incident_id: req.params.id, "remediation.action_id": actionId },
        { $set: { "remediation.state": "FAILED", "remediation.failure_code": "preparation_failed" } });
      fail(502, "PREPARATION_FAILED", "Could not prepare a verified demo proposal. No action was executed.");
    }
    const remediation = { ...result, action_id: actionId, created_at: reserved.remediation.created_at };
    await Incident.updateOne({ incident_id: req.params.id, "remediation.action_id": actionId, "remediation.state": "PREPARING" },
      { $set: { remediation, status: "DIAGNOSED" } });
    operationalLog("info", "remediation_proposal_prepared", {
      incident_id: incident.incident_id, remediation_state: remediation.state,
    });
    res.status(201).json(remediation);
  });
  router.post("/:id/remediation/readiness", async (req, res) => {
    if (!exact(req.body, ["action_id", "proposal_fingerprint"])
        || typeof req.body.action_id !== "string"
        || !/^[a-f0-9]{64}$/.test(req.body.proposal_fingerprint))
      fail(400, "INVALID_READINESS_REQUEST", "Provide the exact action and proposal fingerprint.");
    const incident = found(await Incident.findOne({ incident_id: req.params.id }));
    scope(incident);
    const prior = incident.remediation;
    if (!prior || prior.state !== "BLOCKED" || prior.action_id !== req.body.action_id
        || prior.action?.proposal_fingerprint !== req.body.proposal_fingerprint)
      fail(409, "STALE_READINESS_REQUEST", "The blocked proposal is stale or unavailable.");
    const proposal = persistedProposal(prior);
    const reserved = await Incident.findOneAndUpdate({ incident_id: req.params.id,
      "remediation.state": "BLOCKED", "remediation.action_id": prior.action_id,
      "remediation.action.proposal_fingerprint": prior.action.proposal_fingerprint },
      { $set: { "remediation.state": "CHECKING_READINESS" } }, { new: true });
    if (!reserved) fail(409, "READINESS_ALREADY_RUNNING", "Readiness is already being checked.");
    try {
      const result = await worker({ operation: "readiness", incident: incident.toJSON(), proposal });
      const checks = result.readiness?.checks;
      const verified = result.readiness?.verified_requirements;
      const expectedVerified = checks && readinessNames.filter(name => checks[name]);
      const expectedMissing = checks && readinessNames.filter(name => !checks[name]);
      const allVerified = expectedVerified?.length === readinessNames.length;
      const valid = result.proposal?.action_id === prior.action_id
        && JSON.stringify(result.proposal) === JSON.stringify(proposal)
        && result.action?.proposal_fingerprint === prior.action.proposal_fingerprint
        && exact(checks, readinessNames) && readinessNames.every(name => typeof checks[name] === "boolean")
        && Array.isArray(verified) && JSON.stringify(verified) === JSON.stringify(expectedVerified)
        && Array.isArray(result.action?.missing_requirements)
        && JSON.stringify(result.action.missing_requirements) === JSON.stringify(expectedMissing)
        && result.action.approval_eligible === allVerified
        && result.state === (allVerified ? "PENDING_APPROVAL" : "BLOCKED");
      if (!valid) throw new Error();
      const remediation = { ...prior, ...result, action_id: prior.action_id,
        created_at: prior.created_at, readiness_checked_at: new Date().toISOString() };
      const saved = await Incident.findOneAndUpdate({ incident_id: req.params.id,
        "remediation.state": "CHECKING_READINESS", "remediation.action_id": prior.action_id },
        { $set: { remediation, status: result.state === "PENDING_APPROVAL" ? "PENDING_APPROVAL" : "DIAGNOSED" } },
        { new: true });
      if (!saved) throw new Error();
      operationalLog("info", "remediation_readiness_checked", {
        incident_id: incident.incident_id, remediation_state: result.state,
      });
      return res.json(publicState(saved));
    } catch {
      await Incident.updateOne({ incident_id: req.params.id,
        "remediation.state": "CHECKING_READINESS", "remediation.action_id": prior.action_id },
        { $set: { "remediation.state": "BLOCKED", "remediation.failure_code": "readiness_check_failed" } });
      fail(502, "READINESS_CHECK_FAILED", "Concrete demo readiness checks could not be completed. Nothing was executed; retry the check after inspection.");
    }
  });
  router.post("/:id/remediation/decision", async (req, res) => {
    if (!exact(req.body, ["action_id", "proposal_fingerprint", "decision", "reviewed"])
        || typeof req.body.action_id !== "string" || !/^[a-f0-9]{64}$/.test(req.body.proposal_fingerprint)
        || !["APPROVED", "REJECTED"].includes(req.body.decision) || req.body.reviewed !== true)
      fail(400, "INVALID_DECISION", "Provide the exact action, fingerprint, approval/rejection and reviewed=true.");
    const incident = found(await Incident.findOne({ incident_id: req.params.id }));
    scope(incident);
    const prior = incident.remediation;
    if (!prior || prior.state !== "PENDING_APPROVAL" || prior.action_id !== req.body.action_id
        || prior.action.proposal_fingerprint !== req.body.proposal_fingerprint)
      fail(409, "STALE_DECISION", "The proposal is stale, already decided or unavailable.");
    const decision = { action_id: prior.action_id, proposal_fingerprint: prior.action.proposal_fingerprint,
      decision: req.body.decision, actor: "demo-operator" };
    const rejected = decision.decision === "REJECTED";
    // One atomic durable reservation before any subprocess/machine mutation.
    // This survives server restarts. Uncertain attempts remain consumed.
    const reserved = await Incident.findOneAndUpdate({ incident_id: req.params.id,
      "remediation.state": "PENDING_APPROVAL", "remediation.action_id": prior.action_id,
      "remediation.action.proposal_fingerprint": decision.proposal_fingerprint },
      { $set: { status: rejected ? "DIAGNOSED" : "REMEDIATING",
        "remediation.state": rejected ? "REJECTED" : "EXECUTING",
        "remediation.decision": { ...decision, recorded_at: new Date().toISOString() },
        "remediation.attempt_reserved": !rejected,
        "remediation.action.approval_status": decision.decision,
        "remediation.action.executable": false },
        $push: { "remediation.history": { $each: rejected ? ["REJECTED"] : ["APPROVED", "EXECUTING"] } } }, { new: true });
    if (!reserved) fail(409, "ALREADY_DECIDED", "This action has already been decided.");
    operationalLog("info", "remediation_decision_recorded", {
      incident_id: incident.incident_id, remediation_state: rejected ? "REJECTED" : "EXECUTING",
    });
    if (rejected) return res.json(publicState(reserved));
    let result;
    try {
      let verifying = false;
      result = await worker({ operation: "execute", incident: incident.toJSON(), proposal: prior.proposal, decision }, async event => {
        if (verifying || event.event !== "VERIFYING" || event.action_id !== prior.action_id) throw new Error();
        const saved = await Incident.updateOne({ incident_id: req.params.id,
          "remediation.action_id": prior.action_id, "remediation.state": "EXECUTING",
          "remediation.attempt_reserved": true },
          { $set: { status: "VERIFYING", "remediation.state": "VERIFYING" },
            $push: { "remediation.history": "VERIFYING" } });
        if (saved.modifiedCount !== 1) throw new Error();
        verifying = true;
        operationalLog("info", "remediation_verification_started", {
          incident_id: incident.incident_id, remediation_state: "VERIFYING",
        });
      });
      const verified = verifying && result.state === "RESOLVED" && result.execution?.status === "succeeded"
        && result.execution.action_id === prior.action_id && result.execution.service === "postgres"
        && result.health?.service === "postgres" && result.health.status === "healthy"
        && result.action?.proposal_fingerprint === decision.proposal_fingerprint
        && JSON.stringify(result.proposal) === JSON.stringify(prior.proposal)
        && result.history.includes("VERIFYING");
      if (!verified) result = { ...result, state: "FAILED", failure_code: result.failure_code || "verification_failed" };
      const remediation = { ...prior, ...result, decision: reserved.remediation.decision,
        action_id: prior.action_id, attempt_reserved: true, finished_at: new Date().toISOString() };
      await Incident.updateOne({ incident_id: req.params.id, "remediation.action_id": prior.action_id, "remediation.state": { $in: ["EXECUTING", "VERIFYING"] } },
        { $set: { remediation, status: verified ? "RESOLVED" : "FAILED" } });
      operationalLog(verified ? "info" : "error", "remediation_finished", {
        incident_id: incident.incident_id, remediation_state: verified ? "RESOLVED" : "FAILED",
      });
      return res.json(remediation);
    } catch {
      await Incident.updateOne({ incident_id: req.params.id, "remediation.action_id": prior.action_id, "remediation.state": { $in: ["EXECUTING", "VERIFYING"] } },
        { $set: { status: "FAILED", "remediation.state": "FAILED", "remediation.failure_code": "execution_uncertain" } });
      fail(502, "EXECUTION_UNCERTAIN", "Execution or persistence failed. This attempt is consumed; inspect manually, do not replay.");
    }
  });
  return router;
}
