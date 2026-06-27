// Thin API client. All calls are same-origin (/api/...), proxied to FastAPI in dev.

async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => req("/api/health"),
  login: (worker_id, name) =>
    req("/api/login", { method: "POST", body: JSON.stringify({ worker_id, name }) }),
  triage: (payload) =>
    req("/api/triage", { method: "POST", body: JSON.stringify(payload) }),
  resolveDistrict: (district, pincode) =>
    req("/api/geo/resolve", {
      method: "POST",
      body: JSON.stringify({ district, pincode }),
    }),
  reverseLabel: (lat, lng) =>
    req("/api/geo/label", { method: "POST", body: JSON.stringify({ lat, lng }) }),
  facilities: (lat, lng, urgency = "emergency") =>
    req(`/api/facilities?lat=${lat}&lng=${lng}&urgency=${urgency}`),
  history: (session_id) => req(`/api/history?session_id=${session_id}`),
  getCase: (caseId) => req(`/api/case/${caseId}`),
};

// --- tiny session persistence (sessionStorage, no PII in URLs) ---
const KEY = "asha_session";
export const session = {
  get: () => {
    try {
      return JSON.parse(sessionStorage.getItem(KEY) || "null");
    } catch {
      return null;
    }
  },
  set: (s) => sessionStorage.setItem(KEY, JSON.stringify(s)),
  clear: () => sessionStorage.removeItem(KEY),
};
