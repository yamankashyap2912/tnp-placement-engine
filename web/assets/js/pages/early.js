import { api, qs } from "../api.js";
import { app, go, sheet, cycleOptions } from "../shell.js";
import { h, icon, fmt, chip, riskChip, scoreBar, table, skeleton, hbars, downloadCsv } from "../ui.js";

export default async function early(ctx) {
  let cycle = +ctx.params.get("cycle") || app.cycle, branch = "", threshold = 0.3, maxApps = "", rows = [];
  const setBar = () => ctx.topbar.set({ title: "Early warning", sub: "Who needs help first", filters: [
    { icon: "calendar", label: "Placement batch", value: cycle, options: cycleOptions(), onChange: (v) => { cycle = +v; app.cycle = cycle; load(); } },
    { icon: "users", label: "Branch", value: branch, options: [{ value: "", label: "All branches" }, ...app.meta.branches.map((b) => ({ value: b, label: b }))], onChange: (v) => { branch = v; load(); } },
    { icon: "flow", label: "Applications so far", value: maxApps, options: [{ value: "", label: "Any number" }, ...[0, 1, 2, 3, 5].map((n) => ({ value: n, label: `${n} or fewer` }))], onChange: (v) => { maxApps = v; load(); } }] });
  const cols = [{ label: "Student ID", key: "student_id" }, { label: "Name", key: "name" }, { label: "Branch", key: "branch" }, { label: "CGPA", key: "cgpa" }, { label: "Probability", key: "probability" }, { label: "Applications", key: "applications_count" }];
  const { body } = sheet(ctx, "Early warning", "Unplaced students whose predicted placement probability is low. Schedule mock interviews and skill workshops for them first.",
    [h("button", { class: "btn ghost sm", onclick: () => downloadCsv(`early_warning_${cycle}.csv`, cols, rows) }, icon("download", 16), "Export CSV")]);
  const slider = h("input", { type: "range", min: 0.1, max: 0.6, step: 0.05, value: threshold, "aria-label": "Probability threshold", style: { width: "180px" }, oninput: (e) => { lbl.textContent = `below ${Math.round(e.target.value * 100)}%`; }, onchange: (e) => { threshold = +e.target.value; load(); } });
  const lbl = h("b", { style: { fontWeight: 500 } }, `below ${Math.round(threshold * 100)}%`);
  const kpis = h("div", { class: "grid g4" }), holder = h("div", {});
  body.replaceChildren(h("div", { class: "toolbar" }, h("label", { class: "row muted" }, "Probability", slider, lbl)), kpis, h("div", { style: { marginTop: "16px" } }, holder));
  const load = async () => {
    setBar(); holder.replaceChildren(skeleton(7));
    try {
      const d = await api(`/api/early-warning${qs({ cycle, threshold, branch, max_apps: maxApps })}`);
      if (!ctx.isCurrent()) return;
      rows = d.rows;
      const k = (v, l, kind) => h("div", { class: "card kpi" }, h("div", { class: "v num" }, fmt.n(v)), h("div", { class: "l" }, l));
      kpis.replaceChildren(k(d.count, "Students flagged"), k(d.bands.CRITICAL, "Critical (under 15%)"), k(d.bands.HIGH, "High (15 to 30%)"), k(d.bands.MODERATE, "Moderate (30%+)"));
      holder.replaceChildren(h("div", { class: "grid g-main" },
        h("div", { class: "card" }, table({ rows: d.rows.slice(0, 200), empty: "Nobody is below this threshold", onRow: (r) => go(`#/student/${r.student_id}`),
          columns: [{ label: "Student", render: (r) => h("span", {}, h("b", { style: { fontWeight: 500 } }, r.name), h("span", { class: "sub" }, `ID ${r.student_id}`)) }, { label: "Branch", key: "branch" },
            { label: "CGPA", render: (r) => fmt.n(r.cgpa, 2) }, { label: "Probability", render: (r) => scoreBar(r.probability, { asPct: true }) },
            { label: "Risk", render: (r) => riskChip(r.probability < 0.15 ? "CRITICAL" : r.probability < 0.3 ? "HIGH" : "MODERATE") }, { label: "Applications", key: "applications_count", align: "right" }] })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Flagged by branch")), hbars(Object.entries(d.by_branch).map(([label, value]) => ({ label, value }))),
          h("p", { class: "muted", style: { fontSize: "13px", marginTop: "12px" } }, "Probabilities are estimated before the season from CGPA, skills and profile, so they work as an early warning rather than a result."))));
    } catch (e) { holder.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load the list"), e.message)); }
  };
  await load();
}
