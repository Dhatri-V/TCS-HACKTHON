import React from "react";
import RemediationPanel from "./RemediationPanel.jsx";
import { Status, formatTime } from "./IncidentList.jsx";
function Items({ title, values }) {
  return values?.length ? (
    <section>
      <h3>{title}</h3>
      <ul>
        {values.map((value, index) => (
          <li key={index}>{value}</li>
        ))}
      </ul>
    </section>
  ) : null;
}
export default function IncidentDetail({ incident, onRefresh, onNotify }) {
  const a = incident.analysis;
  return (
    <article className="detail">
      <div className="detail-heading">
        <div>
          <p className="eyebrow">Investigation details</p>
          <h2>{incident.incident_id}</h2>
        </div>
        <Status value={incident.status} />
      </div>
      {incident.status === "PENDING_APPROVAL" && (
        <p className="notice">
          Awaiting authenticated operator review of the proposed demo recovery.
        </p>
      )}
      <dl className="facts">
        <div>
          <dt>Service</dt>
          <dd>{incident.service}</dd>
        </div>
        <div>
          <dt>Timestamp</dt>
          <dd>{formatTime(incident.timestamp)}</dd>
        </div>
        <div>
          <dt>Log level</dt>
          <dd>{incident.log_level}</dd>
        </div>
        <div>
          <dt>Classification</dt>
          <dd>{incident.classification}</dd>
        </div>
      </dl>
      <section>
        <h3>Error message</h3>
        <p className="log-message">{incident.message}</p>
      </section>
      <RemediationPanel key={incident.incident_id} incident={incident} onRefresh={onRefresh} onNotify={onNotify} />
      {!a ? (
        <div className="empty analysis-empty">
          <h3>
            {incident.status === "INVESTIGATING"
              ? "AI investigation in progress"
              : "No AI analysis available"}
          </h3>
          <p>
            Analysis will appear here when the agent publishes its findings.
          </p>
        </div>
      ) : (
        <>
          <section>
            <h3>
              Probable root cause{" "}
              <span className="analysis-status">
                {a.status.replaceAll("_", " ")}
              </span>
            </h3>
            <p>
              {a.probable_root_cause ||
                "Insufficient evidence to establish a root cause."}
            </p>
          </section>
          <section>
            <h3>Explanation</h3>
            <p className="explanation">{a.explanation}</p>
          </section>
          <Items
            title="Remediation recommendations"
            values={a.remediation_steps}
          />
          <Items
            title="Configuration changes"
            values={a.configuration_changes}
          />
          <Items title="Missing information" values={a.missing_information} />
          <section>
            <h3>Evidence references</h3>
            {a.references.length ? (
              <div className="references">
                {a.references.map((ref, i) => (
                  <code key={i}>{ref}</code>
                ))}
              </div>
            ) : (
              <p className="muted">No references supplied.</p>
            )}
          </section>
          <p className="muted footer-note">
            AI recommendations remain informational. Only the separately reviewed
            demo recovery action can execute through the approval panel.
          </p>
        </>
      )}
    </article>
  );
}
