import React, { useEffect, useState } from "react";
import { remediationRequest } from "../services/api.js";
export default function RemediationPanel({ incident, onRefresh }) {
  const [token, setToken] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(incident.remediation);
  useEffect(() => { setResult(incident.remediation); setReviewed(false); }, [incident.remediation]);
  if (incident.incident_id !== "INC-DEMO-001" || incident.service !== "orders-api") return null;
  const run = async (operation, body) => {
    setBusy(true); setError("");
    try {
      let next = await remediationRequest(incident.incident_id, operation, token, body);
      setResult(next);
      if (operation === "proposal" && next.state === "BLOCKED") {
        next = await remediationRequest(incident.incident_id, "readiness", token, {
          action_id: next.action_id,
          proposal_fingerprint: next.action.proposal_fingerprint,
        });
        setResult(next);
      }
      setToken(""); setReviewed(false); onRefresh?.();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const pending = result?.state === "PENDING_APPROVAL";
  const blocked = result?.state === "BLOCKED";
  const canPropose = !result && incident.status === "DIAGNOSED" && incident.analysis;
  return <section className="remediation-panel" aria-label="Demo recovery approval">
    <h3>Demo PostgreSQL recovery</h3>
    <p>Only the existing stopped PostgreSQL container can be started. Its data volume is retained.</p>
    {result && <>
      <p><strong>Workflow: {result.state}</strong></p>
      <p>{result.proposal?.description}</p>
      {result.plan && <dl>{Object.entries(result.plan).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>}
      <p>Lifecycle: {result.history?.join(" → ")}</p>
      {result.decision && <p>Decision: {result.decision.decision} · {result.decision.actor}</p>}
      {result.health && <p role="status">Verification: {result.health.status} — {result.health.details}</p>}
      {result.failure_code && <p role="alert">Recovery failed: {result.failure_code}. Inspect manually; this action will not be replayed.</p>}
      {blocked && <p role="alert">Readiness is incomplete. The backend will attest only requirements proven by the bound container, fixed runbook and orders-api outage checks. Nothing will execute.</p>}
      {result.readiness?.checks && <ul>{Object.entries(result.readiness.checks).map(([name, verified]) => <li key={name}>{name}: {verified ? "verified" : "not verified"}</li>)}</ul>}
      {["PREPARING", "CHECKING_READINESS", "EXECUTING", "VERIFYING"].includes(result.state) && <p>Use Refresh to check progress. If the backend restarted or an attempt is uncertain, inspect manually; do not replay it.</p>}
    </>}
    {(canPropose || pending || blocked) && <>
      <label>Operator token <input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} disabled={busy} /></label>
      <p className="muted">The backend operator token stays in this component’s memory and is cleared after success. Never enter it in incident text.</p>
      {canPropose && <button disabled={busy || !token} onClick={() => run("proposal", {})}>Prepare recovery proposal</button>}
      {blocked && <button disabled={busy || !token} onClick={() => run("readiness", {
        action_id: result.action_id, proposal_fingerprint: result.action.proposal_fingerprint,
      })}>Verify readiness again</button>}
      {pending && <>
        <p>Approval applies to action {result.action_id}. Starting PostgreSQL and health verification run immediately after approval.</p>
        <label><input type="checkbox" checked={reviewed} disabled={busy} onChange={e => setReviewed(e.target.checked)} /> I reviewed the target, impact, rollback plan and verification requirements.</label>
        <div className="remediation-actions">{["APPROVED", "REJECTED"].map(decision => <button key={decision} disabled={busy || !token || !reviewed}
          onClick={() => run("decision", { action_id: result.action_id, proposal_fingerprint: result.action.proposal_fingerprint, decision, reviewed: true })}>
          {decision === "APPROVED" ? "Approve and recover" : "Reject"}</button>)}</div>
      </>}
    </>}
    {busy && <p role="status">Processing recovery request… execution requires approval and resolution requires verified health.</p>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
