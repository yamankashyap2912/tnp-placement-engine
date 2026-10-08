// Pieces reused by several pages (posting details, requirement lists, funnel, student quick view).
import { api } from "../api.js";
import { app, go } from "../shell.js";
import { h, icon, fmt, chip, statusChip, dots, hbars, modal, toast, skeleton } from "../ui.js";

export function requirementList(reqs, mine = null) {
  // mine: optional map skill_id -> student level, shows what the student already has
  return h("div", {}, reqs.map((r) => h("div", { class: "req-row" },
    h("span", {}, r.skill_name, h("span", { class: "muted" }, ` · ${Math.round(r.weight * 100)}%`)),
    dots(mine ? mine[r.skill_id] || 0 : r.required_level, r.required_level))));
}

export function funnelBars(f) {
  if (!f) return null;
  return hbars([
    { label: "Applied", value: f.applications }, { label: "Round 1", value: f.reached_round_1 }, { label: "Round 2", value: f.reached_round_2 },
    { label: "Round 3", value: f.reached_round_3 }, { label: "Selected", value: f.selected }], { max: f.applications || 1 });
}

export function topSkills(reqs, n = 3) { return reqs.slice(0, n).map((r) => r.skill_name).join(", "); }

export async function openPosting(id, { onChange } = {}) {
  const body = h("div", {}, skeleton(5));
  const close = modal("Posting", body, { wide: true });
  try {
    const d = await api(`/api/postings/${id}`);
    const p = d.posting, role = app.user.role;
    const canManage = role === "ADMIN" || role === "RECRUITER";
    const toggle = h("button", { class: "btn ghost sm", onclick: async (e) => {
      const next = p.status === "OPEN" ? "CLOSED" : "OPEN";
      try { await api(`/api/postings/${id}/status`, { method: "POST", body: { status: next } }); toast(`Posting ${next === "OPEN" ? "reopened" : "closed"}.`, "ok"); app.meta = await api("/api/meta/filters"); close(); onChange?.(); }
      catch (x) { toast(x.message, "bad"); }
    } }, p.status === "OPEN" ? "Close applications" : "Reopen applications");
    body.replaceChildren(
      h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "14px" } },
        h("div", {}, h("div", { class: "muted" }, `${p.company} · ${p.sector} · ${p.hq_city}`), h("h3", { style: { fontSize: "22px", fontWeight: 500 } }, p.role_title)),
        h("div", { class: "row" }, statusChip(p.status), chip(p.tier, "mute"), chip(`Batch ${p.cycle_year}`, "mute"))),
      h("div", { class: "grid g4", style: { marginBottom: "16px" } },
        ...[["CTC", fmt.ctc(p.ctc)], ["Minimum CGPA", fmt.n(p.min_cgpa, 1)], ["Eligible students", fmt.n(p.eligible_students)], ["Applicants", fmt.n(p.applicants)]]
          .map(([l, v]) => h("div", { class: "card flat kpi" }, h("div", { class: "v", style: { fontSize: "26px" } }, v), h("div", { class: "l" }, l)))),
      h("div", { class: "grid g2" },
        h("div", { class: "card flat" }, h("div", { class: "card-head" }, h("h3", {}, "Skills this role asks for"), h("span", { class: "sub" }, "ring = level needed")), requirementList(d.requirements)),
        h("div", { class: "card flat" }, h("div", { class: "card-head" }, h("h3", {}, "Hiring funnel"), h("span", { class: "sub" }, `${fmt.n(p.selected)} selected`)), funnelBars(d.funnel),
          h("p", { class: "muted", style: { marginTop: "10px", fontSize: "13px" } }, `Average match of applicants: ${fmt.score(p.avg_applicant_match)} · of selected: ${fmt.score(p.avg_selected_match)}`))),
      canManage ? h("div", { class: "row", style: { marginTop: "18px" } },
        h("button", { class: "btn", onclick: () => { close(); go(`#/shortlist?posting=${id}`); } }, "Open shortlist", icon("right", 16)),
        h("button", { class: "btn ghost", onclick: () => { close(); go(`#/pipeline?posting=${id}`); } }, "Open pipeline desk"), toggle) : null);
  } catch (e) { body.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load this posting"), e.message)); }
}

export const avatar = (name, cls = "") => h("span", { class: `avatar ${cls}` }, fmt.initials(name));

export function shareLink(hash) {
  const url = `${location.origin}${location.pathname}${hash}`;
  navigator.clipboard?.writeText(url).then(() => toast("Link copied.", "ok"), () => toast(url));
}
