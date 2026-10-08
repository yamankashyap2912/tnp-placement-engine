import { api } from "../api.js";
import { sheet } from "../shell.js";
import { h, icon, table, skeleton, chip, busy, toast } from "../ui.js";

const asRows = (r) => r.rows.map((row) => Object.fromEntries(r.columns.map((c, i) => [c, row[i]])));
const cell = (v) => (typeof v === "number" ? (Number.isInteger(v) ? v : +v.toFixed(3)) : v === null ? "-" : String(v).slice(0, 80));

function result(r) {
  const rows = asRows(r);
  return h("div", { class: "card", style: { marginTop: "16px" } },
    h("div", { class: "card-head" }, h("h3", {}, r.title || "Result"), chip(`${rows.length}${r.truncated ? "+" : ""} rows`, "mute")),
    table({ rows, empty: "The query ran but returned no rows", columns: r.columns.map((c) => ({ label: c.replaceAll("_", " "), render: (x) => cell(x[c]) })) }),
    h("details", { style: { marginTop: "12px" } }, h("summary", { class: "muted", style: { cursor: "pointer" } }, "Show the SQL that ran"), h("pre", { class: "sql-box", style: { marginTop: "8px" } }, r.sql)));
}

export default async function assistant(ctx) {
  ctx.topbar.set({ title: "Ask the data", sub: "Read-only questions" });
  const { body } = sheet(ctx, "Ask the data", "Questions in plain words turn into read-only SQL. Everything runs under an account that cannot write or read contact details.");
  let tab = "ask";
  const panel = h("div", { style: { marginTop: "16px" } });
  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Mode" }, [["ask", "Ask in words"], ["sql", "SQL console"]].map(([k, l]) =>
    h("button", { "aria-pressed": k === tab, onclick: (e) => { tab = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === e.currentTarget)); draw(); } }, l)));
  body.replaceChildren(tabs, panel);

  const draw = async () => {
    const out = h("div", {});
    if (tab === "ask") {
      const examples = await api("/api/assistant/examples");
      const input = h("input", { class: "input search", style: { flex: 1, minWidth: "260px" }, placeholder: "e.g. Top 10 students for posting 73", "aria-label": "Your question" });
      const run = async (btn) => { if (!input.value.trim()) return; await busy(btn, async () => { try { out.replaceChildren(result(await api("/api/assistant/ask", { method: "POST", body: { question: input.value } }))); } catch (e) { out.replaceChildren(h("div", { class: "card flat", style: { marginTop: "16px" } }, h("b", {}, "I could not answer that. "), e.message)); } }); };
      const go = h("button", { class: "btn", onclick: (e) => run(e.currentTarget) }, icon("spark", 16), "Ask");
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(go); });
      panel.replaceChildren(h("div", { class: "toolbar" }, input, go),
        h("div", { class: "row", style: { gap: "8px" } }, examples.map((x) => h("button", { class: "chip", style: { border: 0, cursor: "pointer" }, onclick: () => { input.value = x; run(go); } }, x))), out);
    } else {
      const ta = h("textarea", { rows: 6, "aria-label": "SQL", spellcheck: "false", style: { width: "100%" } }, "SELECT branch, COUNT(*) AS students, ROUND(AVG(cgpa), 2) AS avg_cgpa\nFROM Students\nGROUP BY branch\nORDER BY students DESC");
      const go = h("button", { class: "btn", onclick: (e) => busy(e.currentTarget, async () => { try { out.replaceChildren(result({ ...(await api("/api/assistant/sql", { method: "POST", body: { sql: ta.value } })), title: "Query result" })); } catch (e2) { out.replaceChildren(h("div", { class: "card flat", style: { marginTop: "16px" } }, h("b", {}, "Not run. "), e2.message)); } }) }, icon("play", 15), "Run query");
      panel.replaceChildren(h("div", { class: "card" }, h("label", { class: "field" }, "One SELECT statement. At most 500 rows, 8 seconds, no comments.", ta), h("div", { class: "row", style: { marginTop: "12px" } }, go,
        h("span", { class: "muted", style: { fontSize: "13px" } }, "Email and resume columns are blocked for this account."))), out);
    }
  };
  await draw();
}
