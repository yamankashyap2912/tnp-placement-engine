// The frame around every page: top bar, icon rail, router, theme, account menu.
import { api, session } from "./api.js";
import { h, icon, toast, modal } from "./ui.js";

export const app = { user: null, meta: null, cycle: 2026, posting: null };

const NAV = {
  ADMIN: [["home", "Home", "home"], ["dashboard", "Dashboard", "grid"], ["shortlist", "Shortlists", "target"], ["students", "Students", "users"],
    ["postings", "Postings", "briefcase"], ["early", "Early warning", "bell"], ["pipeline", "Pipeline desk", "flow"], ["insights", "ML insights", "chart"],
    ["health", "Database health", "database"], ["assistant", "Ask the data", "chat"]],
  RECRUITER: [["home", "Home", "home"], ["shortlist", "Shortlists", "target"], ["postings", "Postings", "briefcase"], ["pipeline", "Pipeline desk", "flow"]],
  STUDENT: [["home", "Home", "home"], ["matches", "My matches", "target"], ["coach", "Skill coach", "spark"], ["applications", "Applications", "flow"], ["profile", "Profile", "user"]],
};
const ROLE_LABEL = { ADMIN: "TnP officer", RECRUITER: "Recruiter", STUDENT: "Student" };
const els = {};
let routes = {};
let current = null;

export function initShell(routeTable) {
  routes = routeTable;
  ["frame", "topbar", "rail", "view", "badge"].forEach((id) => { els[id] = document.getElementById(id); });
  if (localStorage.getItem("tnp.theme") === "dark") document.body.classList.add("dark");
  window.addEventListener("hashchange", route);
  window.addEventListener("tnp:signed-out", () => { signOut(false); toast("Your session ended. Sign in again.", "bad"); });
}

export const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

function toggleTheme() {
  const dark = document.body.classList.toggle("dark");
  localStorage.setItem("tnp.theme", dark ? "dark" : "light");
  drawRail();
}

export function signOut(navigate = true) {
  session.clear(); app.user = null; app.meta = null;
  els.topbar.hidden = els.rail.hidden = els.badge.hidden = true;
  if (navigate) toast("Signed out.");
  go("#/login");
}

function accountModal() {
  const old = h("input", { type: "password", autocomplete: "current-password", required: true });
  const nw = h("input", { type: "password", autocomplete: "new-password", minlength: 8, required: true });
  const err = h("div", { class: "err" });
  const form = h("form", { class: "grid", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    try { await api("/api/auth/change-password", { method: "POST", body: { old_password: old.value, new_password: nw.value } }); toast("Password changed.", "ok"); close(); }
    catch (x) { err.textContent = x.message; }
  } },
  h("p", { class: "muted" }, `Signed in as ${app.user.username} (${ROLE_LABEL[app.user.role]}).`),
  h("label", { class: "field" }, "Current password", old), h("label", { class: "field" }, "New password (8+ characters)", nw), err,
  h("div", { class: "row" }, h("button", { class: "btn", type: "submit" }, "Change password"), h("button", { class: "btn ghost", type: "button", onclick: () => close() }, "Cancel")));
  const close = modal("Your account", form);
}

// ------------------------------------------------------------------ chrome
export function showChrome() {
  els.topbar.hidden = els.rail.hidden = false;
  drawRail();
}

function drawRail() {
  const items = NAV[app.user.role];
  const hash = location.hash.replace(/^#\//, "").split("?")[0];
  const active = hash.startsWith("student/") ? "students" : hash;
  els.rail.replaceChildren(
    h("div", { class: "rail-group nav" }, items.map(([key, label, ic]) =>
      h("button", { class: "rail-btn", "aria-label": label, "aria-current": active === key ? "page" : undefined, onclick: () => go(`#/${key}`) }, icon(ic, 21), h("span", { class: "tip" }, label)))),
    h("div", { class: "rail-group tools" },
      h("button", { class: "rail-btn", "aria-label": "Account", onclick: accountModal }, h("span", { class: "avatar sm" }, (app.user.display_name || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("")), h("span", { class: "tip" }, "Account")),
      h("button", { class: "rail-btn", "aria-label": "Toggle night mode", onclick: toggleTheme }, icon(document.body.classList.contains("dark") ? "sun" : "moon", 20), h("span", { class: "tip" }, "Day / night"))));
}

// Page-facing top bar API
export const topbar = {
  set({ title, sub, filters = [] }) {
    const f = filters.length ? h("div", { class: "pill filters" }, filters.map(slot)) : null;
    const left = h("div", { class: "pill left" }, h("div", {}, h("div", { class: "pill-label" }, title), sub ? h("div", { class: "pill-sub" }, sub) : null),
      h("button", { class: "pill-btn", "aria-label": "Go to start page", onclick: () => go("#/home") }, icon("up", 18)));
    const right = h("div", { class: "pill right" }, h("div", {}, h("div", { class: "pill-label" }, app.user.display_name), h("div", { class: "pill-sub" }, app.user.role === "STUDENT" ? "Student" : app.user.username)),
      h("button", { class: "pill-btn", "aria-label": "Sign out", onclick: () => signOut() }, icon("logout", 19)));
    els.topbar.classList.toggle("has-filters", !!f);
    els.topbar.replaceChildren(left, ...(f ? [f] : []), right);
  },
};

function slot(f) {
  const opts = f.options;
  const cur = opts.find((o) => String(o.value) === String(f.value)) || opts[0];
  const val = h("b", {}, cur ? cur.label : "-");
  const sel = h("select", { "aria-label": f.label, onchange: (e) => { const o = opts.find((x) => String(x.value) === e.target.value); val.textContent = o.label; f.onChange(o.value); } },
    opts.map((o) => h("option", { value: o.value, selected: String(o.value) === String(f.value) }, o.label)));
  return h("div", { class: "slot" }, h("span", { class: "ico" }, icon(f.icon || "pin", 18)), h("span", { class: "meta" }, h("small", {}, f.label), val), h("span", { class: "chev" }, icon("chevron", 16)), sel);
}

// ------------------------------------------------------------------ pages
export function sheet(ctx, title, subtitle, actions) {
  const body = h("div", {});
  const root = h("section", { class: "sheet" },
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, title), subtitle ? h("p", {}, subtitle) : null), actions ? h("div", { class: "actions" }, actions) : null), body);
  ctx.view.replaceChildren(root);
  return { root, body };
}

export async function route() {
  const raw = location.hash.replace(/^#\/?/, "") || "home";
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/");
  const key = parts[0];
  const user = app.user || (session.get() && (app.user = session.get().user));
  if (!user && key !== "login") return go("#/login");
  if (user && key === "login") return go("#/home");
  const def = routes[key];
  if (!def) return go("#/home");
  if (def.roles && !def.roles.includes(app.user?.role)) return go("#/home");
  if (user) {
    if (!app.meta) { try { app.meta = await api("/api/meta/filters"); } catch { return signOut(false); } }
    showChrome();
  }
  const token = (current = Symbol());
  const full = !!def.full;
  els.frame.classList.toggle("sheet-mode", !full);
  els.view.classList.toggle("full", key === "login");
  els.badge.hidden = !(user && full && key === "home");
  els.view.replaceChildren();
  const ctx = { view: els.view, params: new URLSearchParams(query), sub: parts.slice(1), app, topbar, go, isCurrent: () => current === token };
  try {
    const mod = await def.load();
    if (current !== token) return;
    await mod.default(ctx);
  } catch (e) {
    if (current !== token) return;
    els.view.replaceChildren(h("section", { class: "sheet" }, h("div", { class: "empty" }, h("b", {}, "This page could not load"), e.message)));
  }
  els.view.focus({ preventScroll: true });
}

// cycle / posting helpers shared by pages
export const cycleOptions = (withAll = false) => [...(withAll ? [{ value: "", label: "All cycles" }] : []), ...app.meta.cycles.map((c) => ({ value: c, label: `Batch ${c}` }))];
export const postingOptions = (cycle) => app.meta.postings.filter((p) => !cycle || p.cycle_year === +cycle)
  .map((p) => ({ value: p.posting_id, label: `${p.company} - ${p.role_title}` }));
