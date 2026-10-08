import { api, qs } from "../api.js";
import { app, go, sheet } from "../shell.js";
import { h, fmt, chip, statusChip, scoreBar, table, skeleton, debounce } from "../ui.js";

export default async function students(ctx) {
  ctx.topbar.set({ title: "Students", sub: "Directory and 360 view" });
  const f = { q: "", cycle: "", branch: "", status: "", min_cgpa: "", page: 1 };
  const sel = (key, label, opts) => h("select", { class: "input", "aria-label": label, onchange: (e) => { f[key] = e.target.value; f.page = 1; load(); } },
    h("option", { value: "" }, label), opts.map((o) => h("option", { value: o.value ?? o }, o.label ?? o)));
  const search = h("input", { class: "input search", placeholder: "Search name or student ID", "aria-label": "Search students", oninput: debounce((e) => { f.q = e.target.value.trim(); f.page = 1; load(); }) });
  const cgpa = h("input", { class: "input", type: "number", min: 0, max: 10, step: 0.1, placeholder: "Min CGPA", style: { width: "120px" }, "aria-label": "Minimum CGPA", oninput: debounce((e) => { f.min_cgpa = e.target.value; f.page = 1; load(); }) });
  const holder = h("div", {}), pager = h("div", { class: "pager" });
  const { body } = sheet(ctx, "Students", "Search the cohort, then open anyone for their skills, matches, applications and skill gaps.");
  body.replaceChildren(h("div", { class: "toolbar" }, search, sel("cycle", "Any batch", app.meta.cycles.map((c) => ({ value: c, label: `Batch ${c}` }))), sel("branch", "Any branch", app.meta.branches),
    sel("status", "Any status", [{ value: "PLACED", label: "Placed" }, { value: "NOT_PLACED", label: "Not placed" }, { value: "IN_PROCESS", label: "In process" }]), cgpa), holder, pager);
  const load = async () => {
    holder.replaceChildren(skeleton(8));
    try {
      const d = await api(`/api/students${qs({ ...f, size: 20 })}`);
      if (!ctx.isCurrent()) return;
      holder.replaceChildren(table({ rows: d.rows, empty: "No students match these filters", onRow: (r) => go(`#/student/${r.student_id}`),
        columns: [{ label: "ID", key: "student_id" }, { label: "Name", render: (r) => h("b", { style: { fontWeight: 500 } }, r.name) }, { label: "Branch", key: "branch" }, { label: "Batch", key: "batch_year" },
          { label: "CGPA", render: (r) => fmt.n(r.cgpa, 2) }, { label: "Status", render: (r) => statusChip(r.placement_status) }, { label: "Offer", render: (r) => fmt.ctc(r.offer_ctc) },
          { label: "Applications", key: "applications_count", align: "right" }, { label: "Predicted odds", render: (r) => (r.predicted_probability === null ? "-" : scoreBar(r.predicted_probability, { asPct: true })) }] }));
      const pages = Math.max(1, Math.ceil(d.total / d.size));
      pager.replaceChildren(h("span", {}, `${fmt.n(d.total)} students · page ${d.page} of ${pages}`),
        h("button", { class: "btn ghost sm", disabled: d.page <= 1, onclick: () => { f.page--; load(); } }, "Previous"),
        h("button", { class: "btn ghost sm", disabled: d.page >= pages, onclick: () => { f.page++; load(); } }, "Next"));
    } catch (e) { holder.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load students"), e.message)); }
  };
  await load();
}
