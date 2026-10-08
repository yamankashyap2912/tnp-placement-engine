import { api } from "../api.js";
import { app, go, sheet } from "../shell.js";
import { h, icon, fmt, chip, statusChip, scoreBar, table, skeleton, toast, modal, busy } from "../ui.js";

export default async function pipeline(ctx) {
  const isAdmin = app.user.role === "ADMIN";
  const posts = app.meta.postings;
  const cycles = [...new Set(posts.map((p) => p.cycle_year))].sort();
  let cycle = posts.find((p) => p.posting_id === +ctx.params.get("posting"))?.cycle_year || (cycles.includes(app.cycle) ? app.cycle : cycles[cycles.length - 1]);
  let posting = +ctx.params.get("posting") || posts.find((p) => p.cycle_year === cycle)?.posting_id;
  const opts = () => posts.filter((p) => p.cycle_year === cycle).map((p) => ({ value: p.posting_id, label: `${p.company} - ${p.role_title}` }));
  const setBar = () => ctx.topbar.set({ title: "Pipeline desk", sub: "Applications and rounds", filters: [
    { icon: "calendar", label: "Placement batch", value: cycle, options: cycles.map((c) => ({ value: c, label: `Batch ${c}` })), onChange: (v) => { cycle = +v; posting = opts()[0]?.value; setBar(); load(); } },
    { icon: "briefcase", label: "Posting", value: posting, options: opts(), onChange: (v) => { posting = +v; load(); } }] });
  const { body } = sheet(ctx, "Pipeline desk", "Record interview rounds. Triggers in the database move the application, create the offer and write the audit trail.");
  const banner = h("div", {}), holder = h("div", {}), side = h("div", {});
  body.replaceChildren(banner, h("div", { class: isAdmin ? "split" : "" }, holder, isAdmin ? side : null));

  const roundModal = (a) => {
    const type = h("select", {}, ["APTITUDE", "TECHNICAL", "GD", "HR"].map((t) => h("option", { value: t }, t.toLowerCase())));
    const result = h("select", {}, [["PASS", "Pass (continues)"], ["SELECT", "Select (offer)"], ["REJECT", "Reject"], ["PENDING", "Pending"]].map(([v, l]) => h("option", { value: v }, l)));
    const date = h("input", { type: "date", value: new Date().toISOString().slice(0, 10) });
    const form = h("form", { class: "grid", onsubmit: async (e) => {
      e.preventDefault();
      await busy(e.submitter, async () => {
        try { const r = await api(`/api/applications/${a.application_id}/rounds`, { method: "POST", body: { round_type: type.value, result: result.value, round_date: date.value } });
          toast(`Round ${r.round_no} saved. Application is now ${r.new_status.toLowerCase().replace("_", " ")}.`, "ok"); close(); load(); }
        catch (x) { toast(x.message, "bad"); }
      });
    } }, h("p", { class: "muted" }, `${a.name} · currently ${a.status.toLowerCase().replace("_", " ")} · ${a.rounds_held} rounds so far`),
    h("label", { class: "field" }, "Round type", type), h("label", { class: "field" }, "Result", result), h("label", { class: "field" }, "Date", date),
    h("div", { class: "row" }, h("button", { class: "btn", type: "submit" }, "Save round"), h("button", { class: "btn ghost", type: "button", onclick: () => close() }, "Cancel")));
    const close = modal("Record interview round", form);
  };

  const load = async () => {
    setBar(); holder.replaceChildren(skeleton(7));
    try {
      const [rows, det] = await Promise.all([api(`/api/postings/${posting}/pipeline`), api(`/api/postings/${posting}`)]);
      if (!ctx.isCurrent()) return;
      const p = det.posting;
      banner.replaceChildren(p.status === "CLOSED" ? h("div", { class: "card flat", style: { marginBottom: "14px", display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" } }, icon("lock", 20),
        h("span", { class: "muted", style: { flex: 1 } }, "This posting is closed to new applications (its cycle is finished). Rounds can still be recorded for existing applications."),
        h("button", { class: "btn ghost sm", onclick: async () => { try { await api(`/api/postings/${posting}/status`, { method: "POST", body: { status: "OPEN" } }); toast("Posting reopened.", "ok"); await refreshMeta(); load(); } catch (x) { toast(x.message, "bad"); } } }, "Reopen")) : null);
      holder.replaceChildren(table({ rows, empty: "No applications yet", sub: "Applications appear here as students apply.",
        columns: [{ label: "Student", render: (r) => h("span", {}, h("b", { style: { fontWeight: 500 } }, r.name), h("span", { class: "sub" }, `ID ${r.student_id} · ${r.branch} · CGPA ${fmt.n(r.cgpa, 2)}`)) },
          { label: "Applied", render: (r) => fmt.date(r.applied_date) }, { label: "Match", render: (r) => (r.match_score === null ? "-" : scoreBar(r.match_score)) },
          { label: "Rounds", render: (r) => `${r.rounds_cleared}/${r.rounds_held}${r.last_round_type ? " · " + r.last_round_type.toLowerCase() : ""}` }, { label: "Status", render: (r) => statusChip(r.status) },
          { label: "", align: "right", render: (r) => (["APPLIED", "IN_PROGRESS"].includes(r.status) ? h("button", { class: "btn sm", onclick: () => roundModal(r) }, "Record round") : h("span", { class: "muted" }, "Finished")) }] }));
      if (isAdmin) await drawSide(p);
    } catch (e) { holder.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load the pipeline"), e.message)); }
  };

  const refreshMeta = async () => { app.meta = await api("/api/meta/filters"); };

  const drawSide = async (p) => {
    const sid = h("input", { class: "input", type: "number", min: 1, placeholder: "Student ID", "aria-label": "Student ID" });
    const apply = h("form", { class: "card", onsubmit: async (e) => {
      e.preventDefault();
      await busy(e.submitter, async () => {
        try { await api("/api/applications", { method: "POST", body: { student_id: +sid.value, posting_id: posting } }); toast("Application created.", "ok"); sid.value = ""; load(); }
        catch (x) { toast(x.message, "bad"); }
      });
    } }, h("h3", {}, "Apply a student"), h("p", { class: "muted", style: { fontSize: "13px", margin: "4px 0 12px" } }, "The eligibility trigger checks CGPA, cycle and posting status."), h("div", { class: "row" }, sid, h("button", { class: "btn sm", type: "submit" }, "Apply")));
    const log = h("div", { class: "card" }, h("h3", {}, "Recent status changes"), h("div", { class: "timeline", style: { marginTop: "12px" } }, skeleton(3)));
    side.replaceChildren(apply, h("div", { style: { height: "16px" } }), log);
    try {
      const rows = await api("/api/audit/status-log?limit=8");
      log.lastChild.replaceChildren(...(rows.length ? rows.map((r) => h("div", { class: "tl-item" }, h("span", { class: `tl-dot ${r.new_status === "SELECTED" ? "ok" : r.new_status === "REJECTED" ? "bad" : ""}` }, ""),
        h("div", {}, h("b", {}, `${r.student}: ${r.old_status.toLowerCase().replace("_", " ")} to ${r.new_status.toLowerCase().replace("_", " ")}`), h("div", { class: "sub" }, `${r.company} · ${r.role_title} · ${String(r.changed_at).slice(0, 16).replace("T", " ")}`)))) :
        [h("div", { class: "sub" }, "No changes recorded in this session yet. Record a round to see the audit trail grow.")]));
    } catch { log.lastChild.replaceChildren(); }
  };
  await load();
}
