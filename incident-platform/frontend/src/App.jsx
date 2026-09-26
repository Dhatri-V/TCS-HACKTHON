import React, { useEffect, useState } from "react";
import { getIncident, listIncidents } from "./services/api.js";
import IncidentList from "./components/IncidentList.jsx";
import IncidentDetail from "./components/IncidentDetail.jsx";
export default function App() {
  const [incidents, setIncidents] = useState([]),
    [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null),
    [loading, setLoading] = useState(true),
    [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(""),
    [detailError, setDetailError] = useState(""),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    listIncidents(controller.signal)
      .then((data) => {
        setIncidents(data);
        setSelected((old) =>
          data.some((i) => i.incident_id === old)
            ? old
            : data[0]?.incident_id || null,
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setDetailError("");
    if (!selected) {
      setDetailLoading(false);
      return () => controller.abort();
    }
    setDetailLoading(true);
    getIncident(selected, controller.signal)
      .then(setDetail)
      .catch((e) => {
        if (!controller.signal.aborted) setDetailError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [selected, revision]);
  const open = incidents.filter(
    (i) => !["RESOLVED", "FAILED"].includes(i.status),
  ).length;
  return (
    <main>
      <header>
        <div className="brand">
          <span className="brand-mark">C</span>
          <div>
            Cloud Incident Copilot<small>OPERATIONS CONSOLE</small>
          </div>
        </div>
        <span className="workspace">LOCAL WORKSPACE</span>
      </header>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Incident management</p>
          <h1>Understand. Investigate. Recover.</h1>
          <p className="muted">
            A shared view of service incidents and agent findings.
          </p>
        </div>
        <button
          className="refresh"
          onClick={() => setRevision((v) => v + 1)}
          disabled={loading}
        >
          ↻ Refresh
        </button>
      </div>
      {!loading && !error && (
        <div className="metrics">
          <div>
            <span>Total incidents</span>
            <strong>{incidents.length}</strong>
          </div>
          <div>
            <span>Active incidents</span>
            <strong>{open}</strong>
          </div>
          <div>
            <span>Awaiting approval</span>
            <strong>
              {incidents.filter((i) => i.status === "PENDING_APPROVAL").length}
            </strong>
          </div>
          <div>
            <span>Resolved</span>
            <strong>
              {incidents.filter((i) => i.status === "RESOLVED").length}
            </strong>
          </div>
        </div>
      )}
      <section className="panel">
        <div className="panel-title">
          <h2>Incident stream</h2>
          <span className="muted">Newest first · Manual refresh</span>
        </div>
        {loading ? (
          <p className="empty" role="status">
            Loading incidents…
          </p>
        ) : error ? (
          <div className="empty error" role="alert">
            <h3>Unable to reach the incident API</h3>
            <p>{error}</p>
            <p>Check the backend and MongoDB connection, then refresh.</p>
          </div>
        ) : !incidents.length ? (
          <div className="empty">
            <h3>All quiet here</h3>
            <p>
              No incidents have been reported. New incidents sent to the API
              will appear here.
            </p>
          </div>
        ) : (
          <IncidentList
            incidents={incidents}
            selected={selected}
            onSelect={setSelected}
          />
        )}
      </section>
      {!loading && !error && selected && (
        <section className="panel" aria-live="polite">
          {detailLoading ? (
            <p className="empty">Loading investigation…</p>
          ) : detailError ? (
            <p className="empty error" role="alert">
              {detailError}
            </p>
          ) : (
            detail && <IncidentDetail incident={detail} onRefresh={() => setRevision((v) => v + 1)} />
          )}
        </section>
      )}
      <footer>
        Cloud Incident Copilot{" "}
        <span>Human-approved demo recovery · Agent integration via REST</span>
      </footer>
    </main>
  );
}
