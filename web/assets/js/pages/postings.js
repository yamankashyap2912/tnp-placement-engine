import { api, qs } from "../api.js";
import { app, sheet, cycleOptions } from "../shell.js";
import { h, fmt, chip, statusChip, scoreBar, table, skeleton, debounce, downloadCsv, icon } from "../ui.js";
import { openPosting } from "./common.js";

export default async function postings(ctx) {
  const isAdmin = app.user.role === "ADMIN";
  let cycle = "", status = "", q = "", view = "postings";
  const cycles = [...new Set(app.meta.postings.map((p) => p.cycle_year))].sort();
  const setBar = () => ctx.topbar.set({ title: "Postings", sub: isAdmin ? "All companies" : "Your company", filters: [
    { icon: "calendar", label: "Placement batch", value: cycle, options: [{ value: "", label: "All batches" }, ...cycles.map((c) => ({ value: c, label: `Batch ${c}` }))], onChange: (v) => { cycle = v; load(); } },
    { icon: "tag", label: "Applications", value: status, options: [{ value: "", label: "Any" }, { value: "OPEN", label: "Open" }, { value: "CLOSED", label: "Closed" }], onChange: (v) => { status = v; load(); } }] });
  const { body } = sheet(ctx, "Postings", "Eligibility, applicants, selections and match quality for every role.", [
    h("button", { class: "btn ghost sm", onclick: () => rows && downloadCsv("postings.csv", cols, rows) }, icon("download", 16), "Export CSV")]);
  const search = h("input", { class: "input search", placeholder: "Search company or role", "aria-label": "Search postings", oninput: debounce((e) => { q = e.target.value.trim(); load(); }) });
  const tabs = isAdmin ? h("div", { class: "tabs", role: "group", "aria-label": "View" }, [["postings", "Postings"], ["companies", "Companies"]].map(([k, l]) =>
    h("button", { "aria-pressed": k === view, onclick: (e) => { view = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === e.currentTarget)); load(); } }, l))) : null;
  const holder = h("div", {});
  body.replaceChildren(h("div", { class: "toolbar" }, tabs, search), holder);
  let rows = [];
  const cols = [{ label: "Company", key: "company" }, { label: "Role", key: "role_title" }, { label: "CTC", key: "ctc" }, { label: "Min CGPA", key: "min_cgpa" }, { label: "Batch", key: "cycle_year" },
    { label: "Eligible", key: "eligible_students" }, { label: "Applicants", key: "applicants" }, { label: "Selected", key: "selected" }, { label: "Status", key: "status" }];
  const load = async () => {
    setBar();
    holder.replaceChildren(skeleton(8));
    try {
      if (view === "companies") {
        rows = await api("/api/companies");
        const f = rows.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()));
        holder.replaceChildren(table({ rows: f, columns: [{ label: "Company", render: (r) => h("b", { style: { fontWeight: 500 } }, r.name) }, { label: "Sector", key: "sector" }, { label: "Tier", render: (r) => chip(r.tier, "mute") },
          { label: "Postings", key: "postings", align: "right" }, { label: "Avg CTC", render: (r) => fmt.ctc(r.avg_posting_ctc), align: "right" }, { label: "Applications", render: (r) => fmt.n(r.applications), align: "right" },
          { label: "Offers", render: (r) => fmt.n(r.offers), align: "right" }, { label: "Offer rate", render: (r) => (r.offer_rate_pct === null ? "-" : `${r.offer_rate_pct}%`), align: "right" }] }));
        return;
      }
      rows = await api(`/api/postings${qs({ cycle, status, q })}`);
      if (!ctx.isCurrent()) return;
      holder.replaceChildren(table({ rows, empty: "No postings match these filters", onRow: (r) => openPosting(r.posting_id, { onChange: load }),
        columns: [{ label: "Company", render: (r) => h("span", {}, h("b", { style: { fontWeight: 500 } }, r.company), h("span", { class: "sub" }, r.tier)) }, { label: "Role", key: "role_title" },
          { label: "CTC", render: (r) => fmt.ctc(r.ctc) }, { label: "Min CGPA", render: (r) => fmt.n(r.min_cgpa, 1) }, { label: "Batch", key: "cycle_year" },
          { label: "Eligible", render: (r) => fmt.n(r.eligible_students), align: "right" }, { label: "Applicants", render: (r) => fmt.n(r.applicants), align: "right" },
          { label: "Selected", render: (r) => fmt.n(r.selected), align: "right" }, { label: "Avg match", render: (r) => (r.avg_applicant_match === null ? "-" : scoreBar(r.avg_applicant_match)) },
          { label: "Status", render: (r) => statusChip(r.status) }] }));
    } catch (e) { holder.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Could not load postings"), e.message)); }
  };
  await load();
}
