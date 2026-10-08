import { api } from "../api.js";
import { sheet } from "../shell.js";
import { h, icon, fmt, chip, statusChip, table, skeleton, barChart, hbars, linePlot, legend, toast, busy, PALETTE } from "../ui.js";

export default async function insights(ctx) {
  ctx.topbar.set({ title: "ML insights", sub: "Models, metrics, jobs" });
  const { body } = sheet(ctx, "ML insights", "How well the two models work, what they learned, and the controls that refresh them.");
  let tab = "match", d;
  const panel = h("div", { style: { marginTop: "16px" } });
  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Insight sections" }, [["match", "Match model"], ["placement", "Placement model"], ["jobs", "Runs and jobs"]].map(([k, l]) =>
    h("button", { "aria-pressed": k === tab, onclick: (e) => { tab = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === e.currentTarget)); draw(); } }, l)));
  body.replaceChildren(tabs, panel);
  const load = async () => { panel.replaceChildren(skeleton(6)); try { d = await api("/api/insights"); draw(); } catch (e) { panel.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load insights"), e.message)); } };

  const draw = () => {
    if (tab === "match") {
      const rows = d.match_models;
      if (!rows.length) return panel.replaceChildren(h("div", { class: "empty" }, h("b", {}, "No evaluation report yet"), "Open Runs and jobs and regenerate the report."));
      const names = { cgpa: "CGPA only", cosine: "Cosine (PDF baseline)", coverage: "Weighted coverage", "learned (held-out batch)": "Learned model" };
      panel.replaceChildren(h("div", { class: "grid g2" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Ranking quality inside a posting"), h("span", { class: "sub" }, "mean AUC, higher is better")),
          barChart(rows.map((r) => ({ label: (names[r.scorer] || r.scorer).split(" ")[0], value: +r.mean_per_posting_auc.toFixed(3) })), { height: 220, format: (v) => v.toFixed(3), colors: [PALETTE[3], PALETTE[2], PALETTE[0], PALETTE[1]] }),
          h("p", { class: "muted", style: { fontSize: "13px", marginTop: "8px" } }, "Question asked: among applicants to one posting, does the score rank the selected ones above the rejected ones? 0.5 is a coin flip.")),
        h("div", { class: "card" }, h("h3", { style: { marginBottom: "10px" } }, "Scorer comparison"),
          table({ rows, columns: [{ label: "Scorer", render: (r) => names[r.scorer] || r.scorer }, { label: "AUC (all)", render: (r) => r.auc_all_applications.toFixed(3), align: "right" },
            { label: "Per posting", render: (r) => r.mean_per_posting_auc.toFixed(3), align: "right" }, { label: "Avg precision", render: (r) => r.avg_precision.toFixed(3), align: "right" }] }),
          h("p", { class: "muted", style: { fontSize: "13px", marginTop: "10px" } }, "Weighted coverage is the default: it equals the SQL procedure exactly, so the shortlist is explainable and reproducible without Python. The learned model is scored only on the batch it was not trained on."))));
    } else if (tab === "placement") {
      const pm = d.placement_models;
      const byset = {};
      pm.forEach((r) => (byset[r.feature_set] ||= []).push(r.auc));
      const avg = Object.entries(byset).map(([k, v]) => ({ label: k, value: v.reduce((a, b) => a + b, 0) / v.length }));
      const lift = d.lift;
      panel.replaceChildren(h("div", { class: "grid g2" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Honest model vs leaky model"), h("span", { class: "sub" }, "cross-batch AUC")),
          barChart(avg.map((a) => ({ label: a.label, value: +a.value.toFixed(3) })), { height: 210, format: (v) => v.toFixed(3), colors: [PALETTE[1], PALETTE[3]] }),
          h("p", { class: "muted", style: { fontSize: "13px", marginTop: "8px" } }, "'inseason' adds the interview pass rate, which is computed from the rounds that decide the label. It looks better because it reads the answer, and it cannot warn early. The default is 'preseason'.")),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Are the probabilities honest?"), h("span", { class: "sub" }, "predicted vs observed")),
          lift.length ? linePlot([{ points: lift.map((r) => [r.mean_prob, r.placed_rate]), color: PALETTE[0] }], { diagonal: true, xLabel: "predicted probability", yLabel: "observed placement rate" }) : null,
          h("p", { class: "muted", style: { fontSize: "13px" } }, "Each dot is a tenth of the students. Dots on the dashed line mean a 30% prediction really placed about 30%.")),
        h("div", { class: "card", style: { gridColumn: "1 / -1" } }, h("div", { class: "card-head" }, h("h3", {}, "What the model uses"), h("span", { class: "sub" }, "standardised logistic coefficients")),
          hbars(d.importance.slice(0, 8).map((r) => ({ label: `${r.std_coef >= 0 ? "+" : "-"} ${r.feature.replaceAll("_", " ")}`, value: Math.abs(r.std_coef) })), { format: (v) => v.toFixed(2) }),
          h("p", { class: "muted", style: { fontSize: "13px", marginTop: "8px" } }, "Several features move together (CGPA, proficiency, match score), so read this as what the model leans on, not as cause and effect."))));
    } else {
      const act = (title, text, ctl, run, label) => h("div", { class: "card" }, h("h3", {}, title), h("p", {}, text), ctl, h("button", { class: "btn sm", onclick: (e) => busy(e.currentTarget, async () => { try { const r = await run(); toast(r, "ok"); await load(); } catch (x) { toast(x.message, "bad"); } }) }, icon("refresh", 15), label));
      const method = h("select", { class: "input", "aria-label": "Match method" }, [["coverage", "Weighted coverage"], ["cosine", "Cosine"], ["learned", "Learned model"]].map(([v, l]) => h("option", { value: v }, l)));
      const fset = h("select", { class: "input", "aria-label": "Feature set" }, [["preseason", "Pre-season (honest)"], ["inseason", "In-season (leaky)"]].map(([v, l]) => h("option", { value: v }, l)));
      const pending = (d.queue.find((q) => q.status === "PENDING") || {}).n || 0;
      panel.replaceChildren(h("div", { class: "ml-actions" },
        act("Re-score matches", "Rewrites Match_Scores in one transaction as the least-privilege ML account. A failure rolls back and keeps the old scores.", method,
          async () => { const r = await api("/api/ml/match", { method: "POST", body: { method: method.value } }); return `Match scores rewritten (run #${r.run_id}).`; }, "Run scoring"),
        act("Retrain placement model", "Trains on past outcomes, writes out-of-fold probabilities to Placement_Probability. Re-run after changing the match method.", fset,
          async () => { const r = await api("/api/ml/train", { method: "POST", body: { feature_set: fset.value } }); return `Probabilities rewritten with ${r.model.replaceAll("_", " ")} (run #${r.run_id}).`; }, "Retrain"),
        act("Process refresh queue", `${pending} student or posting entries are waiting. Triggers queue them when skills or requirements change; this re-scores only those.`, h("span", {}),
          async () => { const r = await api("/api/ml/worker", { method: "POST" }); return `${r.processed} queue entries processed, ${fmt.n(r.rows)} scores updated.`; }, "Process queue"),
        act("Regenerate report", "Rebuilds the evaluation report, charts and CSVs shown on the other tabs from the live database.", h("span", {}),
          async () => { await api("/api/ml/report", { method: "POST" }); return "Evaluation report regenerated."; }, "Regenerate")),
        h("div", { class: "card", style: { marginTop: "16px" } }, h("h3", { style: { marginBottom: "10px" } }, "Model lineage (Model_Runs)"),
          table({ rows: d.runs, columns: [{ label: "Run", render: (r) => `#${r.run_id}` }, { label: "Kind", render: (r) => chip(r.run_kind.toLowerCase(), "mute") }, { label: "Model", key: "model_name" },
            { label: "Rows written", render: (r) => fmt.n(r.rows_written), align: "right" }, { label: "Status", render: (r) => statusChip(r.status) }, { label: "Started", render: (r) => String(r.started_at).slice(0, 16).replace("T", " ") }] })));
    }
  };
  await load();
}
