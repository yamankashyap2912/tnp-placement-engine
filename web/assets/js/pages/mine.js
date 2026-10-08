// Student-facing building blocks. The same functions power the student portal (own data) and the
// officer's student page (any student) - written once, reused twice.
import { api, qs } from "../api.js";
import { app, go, sheet } from "../shell.js";
import { h, icon, fmt, chip, statusChip, bandChip, scoreBar, table, skeleton, dots, radar, legend, ring, toast, busy, PALETTE } from "../ui.js";
import { openPosting } from "./common.js";

const err = (e) => h("div", { class: "empty" }, h("b", {}, "Something went wrong"), e.message);

// ------------------------------------------------------------------ matches
export async function renderMatches(box, studentId, { canApply = false, coachTo } = {}) {
  let mode = "all", q = "";
  const holder = h("div", {});
  const search = h("input", { class: "input search", placeholder: "Search company or role", "aria-label": "Search", oninput: (e) => { q = e.target.value.toLowerCase(); draw(); } });
  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Filter matches" },
    [["all", "All"], ["eligible", "Eligible"], ["open", "Open now"], ["todo", "Not applied"]].map(([k, l]) =>
      h("button", { "aria-pressed": k === mode, onclick: (e) => { mode = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === e.currentTarget)); draw(); } }, l)));
  box.replaceChildren(h("div", { class: "toolbar" }, tabs, search), holder);
  let rows = [];
  const load = async () => { holder.replaceChildren(skeleton(6)); try { rows = await api(`/api/students/${studentId}/matches?top=200`); draw(); } catch (e) { holder.replaceChildren(err(e)); } };
  const draw = () => {
    const f = rows.filter((r) => (mode === "eligible" ? r.eligible : mode === "open" ? r.posting_status === "OPEN" : mode === "todo" ? !r.application_id && r.eligible : true)
      && (!q || `${r.company} ${r.role_title}`.toLowerCase().includes(q)));
    holder.replaceChildren(table({ rows: f, empty: "No postings in this view.", onRow: (r) => openPosting(r.posting_id),
      columns: [
        { label: "#", render: (r) => r.rank_no },
        { label: "Company and role", render: (r) => h("span", {}, h("b", { style: { fontWeight: 500 } }, r.role_title), h("span", { class: "sub" }, `${r.company} · ${r.tier}`)) },
        { label: "CTC", render: (r) => fmt.ctc(r.ctc) },
        { label: "Min CGPA", render: (r) => r.eligible ? fmt.n(r.min_cgpa, 1) : chip(`${fmt.n(r.min_cgpa, 1)} needed`, "bad") },
        { label: "Match", render: (r) => scoreBar(r.match_score) },
        { label: "Fit", render: (r) => bandChip(r.band) },
        { label: "Status", render: (r) => r.application_status ? statusChip(r.application_status) : statusChip(r.posting_status) },
        { label: "", align: "right", render: (r) => h("span", { class: "row", style: { justifyContent: "flex-end", flexWrap: "nowrap" } },
          h("button", { class: "btn ghost sm", onclick: (e) => { e.stopPropagation(); coachTo(r.posting_id); } }, icon("spark", 15), "Coach"),
          canApply && !r.application_id && r.eligible && r.posting_status === "OPEN"
            ? h("button", { class: "btn sm", onclick: async (e) => { e.stopPropagation(); await busy(e.currentTarget, async () => {
              try { await api("/api/applications", { method: "POST", body: { student_id: studentId, posting_id: r.posting_id } }); toast(`Applied to ${r.company}.`, "ok"); await load(); }
              catch (x) { toast(x.message, "bad"); } }); } }, "Apply") : null) },
      ] }));
  };
  await load();
}

// ------------------------------------------------------------------ applications
export async function renderApplications(box, studentId, { canWithdraw = false } = {}) {
  box.replaceChildren(skeleton(4));
  let d;
  try { d = await api(`/api/students/${studentId}`); } catch (e) { box.replaceChildren(err(e)); return; }
  if (!d.applications.length) { box.replaceChildren(h("div", { class: "empty" }, h("b", {}, "No applications yet"), "Applications you submit appear here with every interview round.")); return; }
  const list = h("div", { class: "grid g2" });
  d.applications.forEach((a) => {
    const rounds = h("div", { class: "timeline", style: { marginTop: "14px" } });
    const card = h("div", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h3", {}, a.role_title), h("div", { class: "sub" }, `${a.company} · ${fmt.ctc(a.ctc)} · applied ${fmt.date(a.applied_date)}`)), statusChip(a.status)),
      h("div", { class: "row" }, a.match_score !== null ? h("span", { class: "muted" }, "Match ", scoreBar(a.match_score)) : null, h("span", { class: "muted" }, `${a.rounds_cleared}/${a.rounds_held} rounds cleared`)),
      rounds,
      canWithdraw && ["APPLIED", "IN_PROGRESS"].includes(a.status) ? h("div", { style: { marginTop: "12px" } },
        h("button", { class: "btn ghost sm", onclick: async () => { try { await api(`/api/applications/${a.application_id}/withdraw`, { method: "POST" }); toast("Application withdrawn."); renderApplications(box, studentId, { canWithdraw }); } catch (x) { toast(x.message, "bad"); } } }, "Withdraw")) : null);
    list.append(card);
    api(`/api/applications/${a.application_id}/rounds`).then((rs) => {
      rounds.replaceChildren(h("div", { class: "tl-item" }, h("span", { class: "tl-dot mute" }, ""), h("div", {}, h("b", {}, "Resume screen"), h("div", { class: "sub" }, fmt.date(a.applied_date)))),
        ...rs.map((r) => h("div", { class: "tl-item" }, h("span", { class: `tl-dot ${r.result === "REJECT" ? "bad" : r.result === "PENDING" ? "mute" : "ok"}` }, ""),
          h("div", {}, h("b", {}, `Round ${r.round_no} · ${r.round_type.toLowerCase()}`), h("div", { class: "sub" }, `${fmt.date(r.round_date)} · ${r.result.toLowerCase()}`)))));
      if (!rs.length && a.status === "REJECTED") rounds.append(h("div", { class: "sub" }, "Stopped at the resume screen."));
    }).catch(() => {});
  });
  box.replaceChildren(list);
}

// ------------------------------------------------------------------ skill coach
export async function renderCoach(box, studentId, postingId) {
  box.replaceChildren(skeleton(4));
  let matches;
  try { matches = await api(`/api/students/${studentId}/matches?top=200`); } catch (e) { box.replaceChildren(err(e)); return; }
  if (!matches.length) { box.replaceChildren(h("div", { class: "empty" }, h("b", {}, "No match scores yet"), "Run the matching job first.")); return; }
  let pid = postingId && matches.some((m) => m.posting_id === +postingId) ? +postingId : matches[0].posting_id;
  const out = h("div", {});
  const select = h("select", { class: "input", "aria-label": "Posting", style: { maxWidth: "460px" } },
    matches.map((m) => h("option", { value: m.posting_id, selected: m.posting_id === pid }, `${m.company} - ${m.role_title} (${fmt.score(m.match_score)})`)));
  select.onchange = (e) => { pid = +e.target.value; draw(); };
  box.replaceChildren(h("div", { class: "toolbar" }, h("label", { class: "field", style: { flex: 1 } }, "Choose a posting", select)), out);
  const draw = async () => {
    out.replaceChildren(skeleton(4));
    try {
      const g = await api(`/api/students/${studentId}/skill-gap/${pid}`);
      const now = g.summary.stored_match_score ?? 0;
      const need = g.gaps.filter((x) => x.level_gap > 0);
      const labels = g.gaps.map((x) => x.skill_name);
      out.replaceChildren(h("div", { class: "split" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, need.length ? "Where a skill would lift your match" : "You cover every required skill"), h("span", { class: "sub" }, "ranked by gain")),
          need.length ? need.map((x) => h("div", { class: "gap-card" },
            h("div", {}, h("b", { style: { fontWeight: 500 } }, x.skill_name), h("div", { class: "sub" }, `You: level ${x.student_level} · needed: level ${x.required_level} · weight ${Math.round(x.weight * 100)}%`),
              h("div", { style: { marginTop: "4px" } }, dots(x.student_level, x.required_level))),
            h("div", { class: "right" }, h("div", { class: "gain num" }, `+${(x.potential_gain * 100).toFixed(1)}`), h("div", { class: "sub" }, "points")))) : h("p", { class: "muted" }, "Nothing to improve for this role.")),
        h("div", { class: "grid" },
          h("div", { class: "card", style: { textAlign: "center" } }, h("div", { class: "row", style: { justifyContent: "center", gap: "26px" } },
            ring(now, { size: 120, stroke: 12, label: "now" }), icon("right", 22), ring(g.max_possible, { size: 120, stroke: 12, label: "possible", color: "#1b9a69" })),
            h("p", { class: "muted", style: { marginTop: "12px", fontSize: "13px" } }, `Reaching the required level in every missing skill would lift your match from ${now.toFixed(2)} to ${g.max_possible.toFixed(2)}.`),
            h("div", { style: { marginTop: "8px" } }, bandChip(g.summary.band), " ", g.summary.eligible ? chip("CGPA eligible", "ok") : chip("Below CGPA cutoff", "bad"))),
          labels.length >= 3 ? h("div", { class: "card" }, h("h3", { style: { marginBottom: "6px" } }, "You vs the role"),
            radar(labels, [{ values: g.gaps.map((x) => x.required_level), color: PALETTE[2] }, { values: g.gaps.map((x) => x.student_level), color: PALETTE[0] }], { size: 320 }),
            legend([{ color: PALETTE[2], label: "Required" }, { color: PALETTE[0], label: "You" }])) : null)));
    } catch (e) { out.replaceChildren(err(e)); }
  };
  await draw();
}

// ------------------------------------------------------------------ profile
export async function renderProfile(box, studentId) {
  box.replaceChildren(skeleton(4));
  let d;
  try { d = await api(`/api/students/${studentId}`); } catch (e) { box.replaceChildren(err(e)); return; }
  const p = d.profile, ac = d.academic;
  const cats = {};
  d.skills.forEach((s) => (cats[s.category] ||= []).push(s));
  box.replaceChildren(h("div", { class: "grid g-main" },
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Skills"), h("span", { class: "sub" }, `${d.skills.length} skills`)),
      Object.entries(cats).map(([cat, list]) => h("div", { style: { marginBottom: "14px" } }, h("div", { class: "muted", style: { fontSize: "12px", marginBottom: "4px" } }, cat),
        list.map((s) => h("div", { class: "req-row" }, h("span", {}, s.skill_name, " ", chip(s.evidence_source, "mute")), dots(s.proficiency_level)))))),
    h("div", { class: "grid" },
      h("div", { class: "card", style: { textAlign: "center" } }, h("h3", { style: { marginBottom: "10px" } }, "Predicted placement probability"),
        p.predicted_probability !== null ? ring(p.predicted_probability, { size: 140, label: "odds" }) : chip("Not scored yet", "mute"),
        h("p", { class: "muted", style: { fontSize: "13px", marginTop: "10px" } }, "Estimated before the season from CGPA, skills and profile. It is a planning aid, not a verdict.")),
      h("div", { class: "card" }, h("h3", { style: { marginBottom: "8px" } }, "Academic profile"),
        ac ? [["CGPA", fmt.n(p.cgpa, 2)], ["Internships", ac.internships], ["Projects", ac.projects], ["Workshops / certifications", ac.workshops_certifications],
          ["Aptitude score", ac.aptitude_test_score], ["Soft-skills rating", ac.soft_skills_rating], ["Placement training", ac.placement_training]]
          .map(([l, v]) => h("div", { class: "req-row" }, h("span", { class: "muted" }, l), h("b", { style: { fontWeight: 500 } }, v))) : h("p", { class: "muted" }, "No extra profile on file.")))));
}

// ------------------------------------------------------------------ student portal pages
export async function matchesPage(ctx) {
  ctx.topbar.set({ title: "My matches", sub: "Ranked for your batch" });
  const { body } = sheet(ctx, "My matches", "Every posting in your batch, ranked by how closely your skills cover what the role asks for.");
  await renderMatches(body, app.user.student_id, { canApply: true, coachTo: (id) => go(`#/coach?posting=${id}`) });
}
export async function coachPage(ctx) {
  ctx.topbar.set({ title: "Skill coach", sub: "What to learn next" });
  const { body } = sheet(ctx, "Skill coach", "Pick a posting to see which missing skill would raise your match the most.");
  await renderCoach(body, app.user.student_id, ctx.params.get("posting"));
}
export async function applicationsPage(ctx) {
  ctx.topbar.set({ title: "Applications", sub: "Your pipeline" });
  const { body } = sheet(ctx, "My applications", "Every application with its interview rounds, from resume screen to offer.");
  await renderApplications(body, app.user.student_id, { canWithdraw: true });
}
export async function profilePage(ctx) {
  ctx.topbar.set({ title: "Profile", sub: "Skills and profile" });
  const { body } = sheet(ctx, "My profile", "What the matching model sees about you.");
  await renderProfile(body, app.user.student_id);
}
