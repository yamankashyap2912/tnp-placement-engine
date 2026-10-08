import { api } from "../api.js";
import { sheet } from "../shell.js";
import { h, icon, fmt, chip, table, skeleton, hbars, modal } from "../ui.js";

export default async function health(ctx) {
  ctx.topbar.set({ title: "Database health", sub: "Rules, objects, plans" });
  const { body } = sheet(ctx, "Database health", "The rules the database enforces on its own, and proof that the data obeys them.");
  body.replaceChildren(skeleton(8));
  let integrity, cat;
  try { [integrity, cat] = await Promise.all([api("/api/health/integrity"), api("/api/health/catalog")]); }
  catch (e) { body.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load"), e.message)); return; }
  if (!ctx.isCurrent()) return;
  let tab = "tables";
  const panel = h("div", { style: { marginTop: "16px" } });
  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Catalogue" }, [["tables", "Tables"], ["triggers", "Triggers"], ["routines", "Procedures"], ["indexes", "Indexes"], ["plan", "Query plan"], ["er", "ER diagram"]].map(([k, l]) =>
    h("button", { "aria-pressed": k === tab, onclick: (e) => { tab = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === e.currentTarget)); draw(); } }, l)));
  const sm = cat.summary, errors = integrity.filter((c) => c.severity === "ERROR"), failing = errors.filter((c) => c.status === "FAIL").length;
  const k = (v, l) => h("div", { class: "card kpi" }, h("div", { class: "v num" }, fmt.n(v || 0)), h("div", { class: "l" }, l));

  const draw = async () => {
    if (tab === "tables") panel.replaceChildren(h("div", { class: "card" }, hbars(cat.tables.sort((a, b) => b.rows - a.rows).map((t) => ({ label: t.table, value: Math.max(t.rows, 0) })), { format: (v) => fmt.n(v) })));
    else if (tab === "triggers") panel.replaceChildren(h("div", { class: "card" }, table({ rows: cat.triggers, columns: [{ label: "Trigger", render: (r) => h("code", {}, r.trigger_name) }, { label: "Table", key: "table_name" }, { label: "When", render: (r) => chip(`${r.timing.toLowerCase()} ${r.event.toLowerCase()}`, "mute") }] })));
    else if (tab === "routines") panel.replaceChildren(h("div", { class: "card" }, table({ rows: cat.routines, columns: [{ label: "Name", render: (r) => h("code", {}, r.object_name) }, { label: "Type", render: (r) => chip(r.object_type.toLowerCase(), r.object_type === "FUNCTION" ? "" : "mute") }, { label: "Created", render: (r) => r.detail.replace("created ", "") }] })));
    else if (tab === "indexes") {
      const b = cat.benchmark;
      panel.replaceChildren(h("div", { class: "grid g2" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "What each index is worth"), h("span", { class: "sub" }, "speed-up, measured")), b.length ? hbars(b.map((r) => ({ label: r.index.replace("idx_", ""), value: r.speedup_x })), { format: (v) => `${v}x` }) : h("p", { class: "muted" }, "Run python run.py benchmark to measure."),
          b.length ? h("p", { class: "muted", style: { fontSize: "13px", marginTop: "8px" } }, "Measured by making each index invisible to the optimizer and timing the same query with and without it. Indexes that did not help were removed.") : null),
        h("div", { class: "card" }, h("h3", { style: { marginBottom: "10px" } }, "All indexes"), table({ rows: cat.indexes, columns: [{ label: "Table", key: "table_name" }, { label: "Index", render: (r) => h("code", {}, r.index_name) }, { label: "Columns", key: "index_columns" }, { label: "", render: (r) => chip(r.uniqueness, "mute") }] }))));
    } else if (tab === "plan") {
      const sel = h("select", { class: "input", "aria-label": "Posting", style: { maxWidth: "380px" } }, (await api("/api/meta/filters")).postings.slice(0, 80).map((p) => h("option", { value: p.posting_id }, `${p.posting_id} - ${p.company} ${p.role_title}`)));
      const out = h("div", {});
      const run = async () => {
        const r = await api(`/api/health/explain/${sel.value}`);
        out.replaceChildren(h("pre", { class: "sql-box" }, r.sql), h("div", { style: { height: "12px" } }), table({ rows: r.plan, columns: ["table", "type", "key", "rows", "Extra"].map((c) => ({ label: c, render: (x) => x[c] ?? "-" })) }),
          h("p", { class: "muted", style: { fontSize: "13px", marginTop: "10px" } }, "The shortlist reads the index in order, so the database stops after the first rows instead of sorting every score for the posting."));
      };
      sel.onchange = run;
      panel.replaceChildren(h("div", { class: "card" }, h("div", { class: "toolbar" }, sel, h("button", { class: "btn sm", onclick: run }, icon("play", 15), "Explain")), out));
      run();
    } else panel.replaceChildren(h("div", { class: "card", style: { textAlign: "center" } },
      h("img", { src: "/docs-files/er_diagram.svg", alt: "Entity-relationship diagram of all tables", style: { maxWidth: "100%", cursor: "zoom-in", borderRadius: "14px", background: "#fff" },
        onclick: () => modal("ER diagram", h("img", { src: "/docs-files/er_diagram.svg", alt: "Entity-relationship diagram", style: { width: "100%", background: "#fff", borderRadius: "14px" } }), { wide: true }) }),
      h("p", { class: "muted", style: { fontSize: "13px", marginTop: "8px" } }, "Generated from the live foreign keys. Green tables are written only by the ML account.")));
  };

  body.replaceChildren(
    h("div", { class: "grid g4" }, k(sm.TABLE, "Tables"), k(sm.VIEW, "Views"), k((sm.PROCEDURE || 0) + (sm.FUNCTION || 0), "Procedures and functions"), k(sm.TRIGGER, "Triggers")),
    h("div", { class: "card", style: { marginTop: "16px" } }, h("div", { class: "card-head" }, h("h3", {}, "Integrity checks"),
      failing ? chip(`${failing} rules broken`, "bad") : chip("All business rules hold", "ok")),
      integrity.map((c) => h("div", { class: "check-row" }, h("span", { class: `dot ${c.status === "FAIL" ? "bad" : c.status === "WARN" ? "warn" : ""}` }), h("span", {}, c.check_name),
        chip(c.severity.toLowerCase(), c.severity === "ERROR" ? "mute" : "warn"), h("b", { class: "num", style: { fontWeight: 500, minWidth: "28px", textAlign: "right" } }, fmt.n(c.violations))))),
    h("div", { style: { marginTop: "16px" } }, tabs), panel);
  await draw();
}
