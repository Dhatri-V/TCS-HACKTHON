import React from "react";
export const formatTime = (value) => new Date(value).toLocaleString();
export function Status({ value }) {
  return (
    <span className={`badge status-${value.toLowerCase()}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
export default function IncidentList({ incidents, selected, onSelect }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Incident / service</th>
            <th>Timestamp</th>
            <th>Severity</th>
            <th>Lifecycle</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((incident) => (
            <tr
              key={incident.incident_id}
              className={selected === incident.incident_id ? "selected" : ""}
            >
              <td>
                <button
                  className="incident-link"
                  onClick={() => onSelect(incident.incident_id)}
                  aria-pressed={selected === incident.incident_id}
                >
                  {incident.incident_id}
                </button>
                <span className="service">{incident.service}</span>
              </td>
              <td className="timestamp">{formatTime(incident.timestamp)}</td>
              <td>
                <span className="severity">{incident.log_level}</span>
              </td>
              <td>
                <Status value={incident.status} />
              </td>
              <td className="message">{incident.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
