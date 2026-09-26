import "dotenv/config";
import mongoose from "mongoose";
import { connectDatabase } from "../src/config/database.js";
import { Incident } from "../src/models/Incident.js";

// This is an offline demo operator utility, never an HTTP endpoint. It frees
// the one fixed demo ID between presentations without changing lifecycle rules.
if (process.env.DEMO_RESET_CONFIRM !== "INC-DEMO-001") {
  console.error("Demo reset confirmation is missing.");
  process.exitCode = 2;
} else {
  try {
    await connectDatabase(process.env.MONGODB_URI);
    const incident = await Incident.findOne({ incident_id: "INC-DEMO-001" })
      .select({ incident_id: 1, status: 1, remediation: 1 });
    if (!incident) {
      console.log("Demo incident is already absent.");
    } else {
      const workflow = incident.remediation?.state;
      const activeStatuses = new Set(["PENDING_APPROVAL", "REMEDIATING", "VERIFYING"]);
      const activeWorkflows = new Set(["PREPARING", "CHECKING_READINESS", "PENDING_APPROVAL",
        "APPROVED", "EXECUTING", "VERIFYING"]);
      if (activeStatuses.has(incident.status) || activeWorkflows.has(workflow)) {
        throw new Error("active_demo_workflow");
      }
      const result = await Incident.deleteOne({ _id: incident._id, incident_id: "INC-DEMO-001",
        status: incident.status });
      if (result.deletedCount !== 1) throw new Error("demo_reset_raced");
      console.log("Demo incident reset.");
    }
  } catch {
    console.error("Demo reset failed. Confirm MongoDB is reachable and no remediation is active.");
    process.exitCode = 1;
  } finally {
    await mongoose.disconnect();
  }
}
