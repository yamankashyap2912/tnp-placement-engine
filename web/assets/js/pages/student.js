// Officer view of one student: the same components the student portal uses, in tabs.
import { api } from "../api.js";
import { app, go, sheet } from "../shell.js";
import { h, fmt, chip, statusChip, ring, skeleton } from "../ui.js";
import { avatar } from "./common.js";
import { renderMatches, renderApplications, renderCoach, renderProfile } from "./mine.js";

export default async function student(ctx) {
  const id = +ctx.sub[0];
  ctx.topbar.set({ title: "Student", sub: `ID ${id}` });
  const { body } = sheet(ctx, "Student profile", "Everything the database knows about this student, in one place.");
  body.replaceChildren(skeleton(4));
  let d;
  try { d = await api(`/api/students/${id}`); } catch (e) { body.replaceChildren(h("div", { class: "empty" }, h("b", {}, "Student not found"), e.message)); return; }
  const p = d.profile;
  let tab = ctx.params.get("tab") || "profile";
  const panel = h("div", { style: { marginTop: "18px" } });
  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Student sections" },
    [["profile", "Profile"], ["matches", "Matches"], ["applications", "Applications"], ["coach", "Skill gap"]].map(([k, l]) =>
      h("button", { "aria-pressed": k === tab, onclick: () => { tab = k; tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.textContent === l)); draw(); } }, l)));
  const draw = () => {
    if (tab === "profile") renderProfile(panel, id);
    else if (tab === "matches") renderMatches(panel, id, { coachTo: (pid) => { tab = "coach"; ctx.params.set("posting", pid); tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.textContent === "Skill gap")); draw(); } });
    else if (tab === "applications") renderApplications(panel, id);
    else renderCoach(panel, id, ctx.params.get("posting"));
  };
  body.replaceChildren(
    h("div", { class: "card", style: { display: "flex", gap: "20px", alignItems: "center", flexWrap: "wrap", borderRadius: "30px 30px 30px 10px" } },
      avatar(p.name), h("div", { style: { flex: 1, minWidth: "220px" } }, h("h1", { style: { fontWeight: 300, fontSize: "32px", letterSpacing: "-.02em" } }, p.name),
        h("div", { class: "row", style: { marginTop: "6px" } }, chip(p.branch, "mute"), chip(`Batch ${p.batch_year}`, "mute"), chip(`CGPA ${fmt.n(p.cgpa, 2)}`, ""), statusChip(p.placement_status),
          p.offer_ctc ? chip(fmt.ctc(p.offer_ctc), "ok") : null, h("span", { class: "muted" }, `ID ${p.student_id}`))),
      p.predicted_probability !== null ? ring(p.predicted_probability, { size: 96, stroke: 11, label: "odds" }) : null,
      h("button", { class: "btn ghost sm", onclick: () => go("#/students") }, "Back to students")),
    h("div", { style: { marginTop: "16px" } }, tabs), panel);
  draw();
}
