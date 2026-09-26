import { Incident } from "../models/Incident.js";
import { ApiError } from "../middleware/errors.js";
import {
  validateAnalysis,
  validateIncident,
  validateStatusBody,
} from "../middleware/validation.js";
const found = (incident) => {
  if (!incident) throw new ApiError(404, "NOT_FOUND", "Incident not found");
  return incident;
};
export async function list(req, res) {
  res.json(
    await Incident.find()
      .sort({ timestamp: -1, incident_id: 1 })
      .maxTimeMS(5000),
  );
}
export async function get(req, res) {
  res.json(
    found(
      await Incident.findOne({ incident_id: req.params.id }).maxTimeMS(5000),
    ),
  );
}
export async function create(req, res) {
  const value = validateIncident(req.body);
  if (value.status === "RESOLVED") throw new ApiError(409, "VERIFICATION_REQUIRED", "Resolution requires verified remediation.");
  res.status(201).json(await Incident.create(value));
}
async function requireUnmanaged(id) {
  const incident = found(await Incident.findOne({ incident_id: id }));
  if (incident.remediation) throw new ApiError(409, "REMEDIATION_MANAGED", "This incident is controlled by its remediation workflow.");
}
export async function analysis(req, res) {
  const value = validateAnalysis(req.body, req.params.id);
  await requireUnmanaged(req.params.id);
  res.json(
    found(
      await Incident.findOneAndUpdate(
        { incident_id: req.params.id, remediation: null },
        { $set: { analysis: value } },
        { new: true, runValidators: true, maxTimeMS: 5000 },
      ),
    ),
  );
}
export async function status(req, res) {
  const value = validateStatusBody(req.body);
  await requireUnmanaged(req.params.id);
  if (value === "RESOLVED") throw new ApiError(409, "VERIFICATION_REQUIRED", "Resolution requires successful health verification.");
  res.json(
    found(
      await Incident.findOneAndUpdate(
        { incident_id: req.params.id, remediation: null },
        { $set: { status: value } },
        { new: true, runValidators: true, maxTimeMS: 5000 },
      ),
    ),
  );
}
