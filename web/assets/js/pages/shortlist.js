import { api, qs } from "../api.js";
import { app, go, sheet } from "../shell.js";
import { h, icon, fmt, chip, statusChip, bandChip, scoreBar, table, skeleton, downloadCsv } from "../ui.js";
import { requirementList, funnelBars, openPosting } from "./common.js";

export default async function shortlist(ctx) {
  const isAdmin = app.user.role === "ADMIN";
  const posts = app.meta.postings;
  const cycles = [...new Set(posts.map((p) => p.cycle_year))].sort();
  let cycle = +ctx.params.get("cycle") || (posts.find((p) => p.posting_id === +ctx.params.get("posting"))?.cycle_year) || (cycles.includes(app.cycle) ? app.cycle : cycles[cycles.length - 1]);
  let posting = +ctx.params.get("posting") || app.posting;
  if (!posts.some((p) => p.posting_id === posting && p.cycle_year === cycle)) posting = posts.find((p) => p.cycle_year === cycle)?.posting_id;
  let top = 20, mode = "ranked", rows = [];
  const opts = () => posts.filter((p) => p.cycle_year === cycle).map((p) => ({ value: p.posting_id, label: `${p.company} - ${p.role_title}` }));
  const setBar = () => ctx.topbar.set({ title: "Shortlists", sub: "Ranked by match score", filters: [
    { icon: "calendar", label: "Placement batch", value: cycle, options: cycles.map((c) => ({ value: c, label: `Batch ${c}` })), onChange: (v) => { cycle = +v; posting = opts()[0]?.value; app.posting = posting; setBar(); load(); } },
    { icon: "briefcase", label: "Posting", value: posting, options: opts(), onChange: (v) => { posting = +v; app.posting = posting; load(); } },
    { icon: "list", label: "Show top", value: top, options: [10, 20, 50, 100].map((n) => ({ value: n, label: `${n} students` })), onChange: (v) => { top = +v; load(); } }] });
  const { body } = sheet(ctx, "Shortlist", "The ranking below is a plain ORDER BY match_score on the table the model fills.",
    [h("button", { class: "btn ghost sm", id: "csv", onclick: () => downloadCsv(`shortlist_posting_${posting}.csv`, cols, rows) }, icon("download", 16), "Export CSV")]);
  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Shortlist type" },
    [["ranked", "Ranked cohort"], ["fresh", "Eligible, not applied yet"]].map(([k, l]) => h("button", { "aria-pressed": k === mode, onclick: (e) => { mode = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === e.currentTarget)); load(); } }, l)));
  const side = h("div", {}), list = h("div", {});
  body.replaceChildren(h("div", { class: "toolbar" }, tabs), h("div", { class: "split" }, list, side));
  const cols = [{ label: "Rank", key: "rank_no" }, { label: "Student", key: "name" }, { label: "Student ID", key: "student_id" }, { label: "Branch", key: "branch" },
    { label: "CGPA", key: "cgpa" }, { label: "Match score", key: "match_score" }, { label: "Fit", key: "band" }];
  const load = async () => {
    list.replaceChildren(skeleton(8));
    try {
      const [r, d] = await Promise.all([api(`/api/postings/${posting}/shortlist${qs({ top, not_applied: mode === "fresh" })}`), api(`/api/postings/${posting}`)]);
      if (!ctx.isCurrent()) return;
      rows = r;
      list.replaceChildren(table({ rows, empty: "No students to show", sub: "Try the other tab, or run the matching job.",
        onRow: isAdmin ? (x) => go(`#/student/${x.student_id}`) : undefined,
        columns: [{ label: "#", render: (x) => x.rank_no },
          { label: "Student", render: (x) => h("span", {}, h("b", { style: { fontWeight: 500 } }, x.name), h("span", { class: "sub" }, `ID ${x.student_id}`)) },
          { label: "Branch", key: "branch" }, { label: "CGPA", render: (x) => fmt.n(x.cgpa, 2) },
          { label: "Match", render: (x) => scoreBar(x.match_score) }, { label: "Fit", render: (x) => bandChip(x.band) },
          mode === "ranked" ? { label: "Applied", render: (x) => (x.already_applied === "YES" ? statusChip(x.application_status) : chip("Not yet", "mute")) } : { label: "Contact", render: (x) => x.email || "-" }] }));
      const p = d.posting;
      side.replaceChildren(h("div", { class: "card" },
        h("div", { class: "card-head" }, h("div", {}, h("h3", {}, p.role_title), h("div", { class: "sub" }, `${p.company} · ${fmt.ctc(p.ctc)} · CGPA ${fmt.n(p.min_cgpa, 1)}+`)), statusChip(p.status)),
        h("div", { class: "muted", style: { fontSize: "12px", margin: "4px 0" } }, "What the role asks for"), requirementList(d.requirements),
        h("div", { class: "muted", style: { fontSize: "12px", margin: "16px 0 4px" } }, "Hiring funnel"), funnelBars(d.funnel),
        h("div", { style: { marginTop: "14px" } }, h("button", { class: "btn ghost sm", onclick: () => openPosting(posting) }, "Full posting details"))));
    } catch (e) { list.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load the shortlist"), e.message)); }
  };
  setBar();
  await load();
}
