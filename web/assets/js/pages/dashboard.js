import { api } from "../api.js";
import { app, sheet, cycleOptions } from "../shell.js";
import { h, fmt, barChart, hbars, table, skeleton, legend, PALETTE, chip } from "../ui.js";

export default async function dashboard(ctx) {
  const setBar = () => ctx.topbar.set({ title: "Dashboard", sub: "Placement analytics", filters: [
    { icon: "calendar", label: "Placement batch", value: app.cycleAll ? "" : app.cycle, options: cycleOptions(true), onChange: (v) => { app.cycleAll = v === ""; if (v) app.cycle = +v; draw(); } }] });
  const { body } = sheet(ctx, "Dashboard", "How the placement cycle is going, straight from the database views.");
  const draw = async () => {
    body.replaceChildren(skeleton(6));
    const cyc = app.cycleAll ? "" : `?cycle=${app.cycle}`;
    const o = await api(`/api/overview${cyc}`);
    if (!ctx.isCurrent()) return;
    const k = o.kpis;
    const kpi = (v, l, d) => h("div", { class: "card kpi" }, h("div", { class: "v num" }, v), h("div", { class: "l" }, l), d ? h("div", { class: "d" }, d) : null);
    const byBranch = {};
    o.branch.forEach((r) => { (byBranch[r.branch] ||= []).push(r); });
    const branchData = Object.entries(byBranch).map(([b, rows]) => ({ label: b, value: Math.round(rows.reduce((a, r) => a + r.placed, 0) * 100 / rows.reduce((a, r) => a + r.students, 0)) }));
    body.replaceChildren(
      h("div", { class: "grid g4" },
        kpi(fmt.n(k.students), "Students", `${fmt.n(k.companies)} companies · ${fmt.n(k.postings)} postings`),
        kpi(`${fmt.n(k.placement_pct, 1)}%`, "Placed", `${fmt.n(k.placed)} students`),
        kpi(fmt.n(k.avg_ctc_lpa, 1), "Average CTC (LPA)", `Highest ${fmt.ctc(k.max_ctc_lpa)}`),
        kpi(fmt.n(k.at_risk), "Flagged at risk", "predicted below 30%, not placed")),
      h("div", { class: "grid g2", style: { marginTop: "16px" } },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Placement rate by branch"), h("span", { class: "sub" }, "percent of students")), barChart(branchData, { format: (v) => v + "%", aria: "Placement rate by branch" })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Offers by CTC band"), h("span", { class: "sub" }, "LPA")),
          barChart(o.ctc_hist.map((r) => ({ label: `${r.bucket}-${r.bucket + 5}`, value: r.n })), { color: PALETTE[1], aria: "Offers by CTC band" }))),
      h("div", { class: "grid g2", style: { marginTop: "16px" } },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Predicted placement probability"), h("span", { class: "sub" }, "students per 10% band")),
          barChart(o.prob_hist.map((r) => ({ label: `${r.bucket * 10}%`, value: r.n })), { color: PALETTE[2], aria: "Probability distribution" })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Offers by company tier")),
          table({ columns: [{ label: "Tier", key: "tier" }, { label: "Offers", key: "offers", align: "right" }, { label: "Avg CTC", render: (r) => fmt.ctc(r.avg_ctc_lpa), align: "right" }, { label: "Max", render: (r) => fmt.ctc(r.max_ctc_lpa), align: "right" }], rows: o.tiers }))),
      h("div", { class: "card", style: { marginTop: "16px" } }, h("div", { class: "card-head" }, h("h3", {}, "Top recruiters by offers"), h("span", { class: "sub" }, "batch " + (o.top_recruiters.length ? app.cycle : ""))),
        hbars(o.top_companies.map((c) => ({ label: c.name, value: c.offers })))));
    setBar();
  };
  setBar();
  await draw();
}
