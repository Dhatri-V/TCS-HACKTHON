const base = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:3000"
).replace(/\/$/, "");
export async function remediationRequest(id, operation, token, body) {
  const response = await fetch(`${base}/api/incidents/${encodeURIComponent(id)}/remediation${operation ? `/${operation}` : ""}`, {
    method: operation ? "POST" : "GET",
    headers: operation ? { "Content-Type": "application/json", Authorization: `Bearer ${token}` } : {},
    ...(operation ? { body: JSON.stringify(body) } : {}),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.error?.message || "Remediation request failed");
  return payload;
}
async function get(path, signal) {
  const response = await fetch(`${base}${path}`, { signal });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(
      payload?.error?.message || `API request failed (${response.status})`,
    );
  }
  return response.json();
}
export const listIncidents = (signal) => get("/api/incidents", signal);
export const getIncident = (id, signal) =>
  get(`/api/incidents/${encodeURIComponent(id)}`, signal);
