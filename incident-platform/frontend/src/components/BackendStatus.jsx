import React from "react";

export default function BackendStatus({ online }) {
  const state = online === null ? "checking" : online ? "online" : "offline";
  const label = online === null ? "Checking backend" : online ? "Backend online" : "Backend offline";
  return <span className={`backend-status backend-${state}`} role="status">
    <span className="status-dot" aria-hidden="true" />{label}
  </span>;
}
