import mongoose from "mongoose";
import { STATUSES } from "../middleware/validation.js";
const schema = new mongoose.Schema(
  {
    incident_id: {
      type: String,
      required: true,
      unique: true,
      immutable: true,
    },
    timestamp: { type: Date, required: true, index: true },
    service: { type: String, required: true },
    log_level: { type: String, required: true },
    message: { type: String, required: true },
    classification: { type: String, required: true },
    status: {
      type: String,
      enum: STATUSES,
      default: "INVESTIGATING",
      required: true,
    },
    analysis: { type: mongoose.Schema.Types.Mixed, default: null },
    remediation: { type: mongoose.Schema.Types.Mixed, default: null },
  },
  {
    strict: "throw",
    // ActionProposal restart parameters are intentionally {}. Removing that
    // empty object changes the immutable proposal shape on later requests.
    minimize: false,
    versionKey: false,
    bufferCommands: false,
    toJSON: {
      transform: (_doc, result) => {
        delete result._id;
        return result;
      },
    },
  },
);
export const Incident = mongoose.model("Incident", schema);
