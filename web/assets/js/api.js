// Tiny fetch wrapper: adds the session token, turns API errors into readable Error messages.
const KEY = "tnp.session";

export const session = {
  get() { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } },
  set(s) { localStorage.setItem(KEY, JSON.stringify(s)); },
  clear() { localStorage.removeItem(KEY); },
};

export async function api(path, { method = "GET", body, quiet = false } = {}) {
  const s = session.get();
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(s ? { Authorization: `Bearer ${s.token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    if (res.status === 401 && s) window.dispatchEvent(new CustomEvent("tnp:signed-out"));
    const msg = (data && (typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg)) || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.quiet = quiet;
    throw err;
  }
  return data;
}

export const qs = (o) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, v === true ? "true" : v); });
  const s = p.toString();
  return s ? `?${s}` : "";
};
