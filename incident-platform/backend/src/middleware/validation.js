import { ApiError } from "./errors.js";
export const STATUSES = [
  "INVESTIGATING",
  "DIAGNOSED",
  "PENDING_APPROVAL",
  "REMEDIATING",
  "VERIFYING",
  "RESOLVED",
  "FAILED",
];
const fail = (message) => {
  throw new ApiError(400, "INVALID_REQUEST", message);
};
const object = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value) => typeof value === "string" && value.trim().length > 0;
function body(value) {
  if (!object(value)) fail("Body must be a JSON object");
}
function keys(value, allowed) {
  if (Object.keys(value).some((key) => !allowed.includes(key)))
    fail("Unexpected request field");
}
export function validateStatus(status) {
  if (!STATUSES.includes(status)) fail("Invalid lifecycle status");
}
export function validateAnalysis(analysis, incidentId) {
  body(analysis);
  if (!["completed", "insufficient_evidence"].includes(analysis.status))
    fail("Invalid analysis status");
  if (analysis.incident_id !== incidentId)
    fail("analysis.incident_id must match incident_id");
  if (!text(analysis.explanation)) fail("analysis.explanation is required");
  if (
    analysis.status === "completed"
      ? !text(analysis.probable_root_cause)
      : analysis.probable_root_cause !== null
  )
    fail("Root cause must agree with analysis status");
  for (const field of [
    "remediation_steps",
    "configuration_changes",
    "references",
    "missing_information",
  ]) {
    if (!Array.isArray(analysis[field]) || !analysis[field].every(text))
      fail(`analysis.${field} must be an array of nonempty strings`);
  }
  // Preserve additive reasoner metadata without coupling to its internal schemas.
  // Never use analysis data as query operators, commands, or approval instructions.
  function safeKeys(value) {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (
        key.startsWith("$") ||
        key.includes(".") ||
        ["__proto__", "constructor", "prototype"].includes(key)
      )
        fail("Unsupported analysis field name");
      safeKeys(child);
    }
  }
  safeKeys(analysis);
  return analysis;
}
export function validateIncident(value) {
  body(value);
  keys(value, [
    "incident_id",
    "timestamp",
    "service",
    "log_level",
    "message",
    "classification",
    "status",
    "analysis",
  ]);
  for (const field of [
    "incident_id",
    "timestamp",
    "service",
    "log_level",
    "message",
    "classification",
  ]) {
    if (!text(value[field]))
      fail(`${field} is required and must be a nonempty string`);
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value.incident_id))
    fail("Invalid incident_id format");
  const timestamp = value.timestamp;
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})?$/.test(
      timestamp,
    ) ||
    !Number.isFinite(Date.parse(timestamp))
  )
    fail("timestamp must be an ISO datetime");
  const [year, month, day] = timestamp.slice(0, 10).split("-").map(Number);
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (day < 1 || day > daysInMonth)
    fail("timestamp contains an invalid calendar date");
  const status = value.status === undefined ? "INVESTIGATING" : value.status;
  validateStatus(status);
  const analysis = value.analysis === undefined ? null : value.analysis;
  if (analysis !== null) validateAnalysis(analysis, value.incident_id);
  // Treat timezone-free incident timestamps as UTC, consistently across hosts.
  return {
    ...value,
    timestamp: /(?:Z|[+-]\d{2}:\d{2})$/.test(timestamp)
      ? timestamp
      : `${timestamp}Z`,
    status,
    analysis,
  };
}
export function validateStatusBody(value) {
  body(value);
  keys(value, ["status"]);
  validateStatus(value.status);
  return value.status;
}
