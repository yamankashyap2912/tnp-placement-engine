import { api } from "../api.js";
import { app, go, cycleOptions, postingOptions } from "../shell.js";
import { h, icon, fmt, ring, chip, skeleton } from "../ui.js";
import { avatar, requirementList, topSkills, shareLink } from "./common.js";

const HERO = {
  ADMIN: ["New Way Of Hiring", "Every student scored against every posting, ranked inside the database. Pick a posting and see who fits before the first interview."],
  RECRUITER: ["Meet Your Match", "See the candidates whose skills cover your requirements best, and move them through your rounds."],
  STUDENT: ["Find Your Fit", "See how closely your skills match every posting in your batch, and which skill would lift a match the most."],
};

export default async function home(ctx) {
  const role = app.user.role;
  ctx.topbar.set({ title: "Home", sub: role === "ADMIN" ? "TnP officer desk" : role === "RECRUITER" ? "Recruiter desk" : "Student desk" });
  const root = h("div", { class: "home" }, h("h1", { class: "display" }, HERO[role][0]), h("p", { class: "lede" }, HERO[role][1]));
  ctx.view.replaceChildren(root);
  try {
    if (role === "ADMIN") await adminHome(ctx, root);
    else if (role === "RECRUITER") await recruiterHome(ctx, root);
    else await studentHome(ctx, root);
  } catch (e) { root.append(h("div", { class: "hero-card feature" }, h("b", {}, "Could not load the start page"), h("p", { class: "desc" }, e.message))); }
}

function findCard({ title, text, big, caption, people = [], to }) {
  return h("div", { class: "hero-card find" }, h("h3", {}, title), h("p", {}, text),
    h("div", { class: "stat-row" }, h("div", {}, h("div", { class: "big num" }, big), h("small", {}, caption)),
      h("div", { class: "avatars" }, people.slice(0, 3).map((n) => avatar(n))),
      h("button", { class: "round-btn", "aria-label": "Open", onclick: () => go(to) }, icon("up", 20))));
}

function featureCard({ post, reqs, actions, extra }) {
  return h("div", { class: "hero-card feature" },
    h("div", { class: "head" }, h("div", {}, h("h3", {}, post.role_title), h("div", { class: "where" }, icon("building", 15), `${post.company}${post.hq_city ? ", " + post.hq_city : ""}`)),
      h("button", { class: "round-btn", "aria-label": "Open details", onclick: actions[0].run }, icon("up", 20))),
    h("p", { class: "desc" }, reqs.length ? `Weighted most: ${topSkills(reqs, 4)}. ${extra || ""}` : extra || ""),
    h("div", { class: "meta-row" }, h("span", {}, icon("coin", 16), fmt.ctc(post.ctc)), h("span", {}, icon("target", 16), `CGPA ${fmt.n(post.min_cgpa, 1)}+`),
      post.applicants !== undefined ? h("span", {}, icon("users", 16), `${fmt.n(post.applicants)} applied`) : null),
    h("div", { class: "actions" }, actions.map((a) => h("button", { class: "act", onclick: a.run }, icon(a.icon, 20), a.label))));
}

async function adminHome(ctx, root) {
  const draw = async () => {
    root.querySelectorAll(".hero-card").forEach((n) => n.remove());
    root.append(h("div", { class: "hero-card find" }, skeleton(3)));
    const ov = await api(`/api/overview?cycle=${app.cycle}`);
    const pid = app.posting && app.meta.postings.some((p) => p.posting_id === +app.posting && p.cycle_year === +app.cycle) ? +app.posting : ov.featured_posting_id;
    app.posting = pid;
    const [d, top] = await Promise.all([api(`/api/postings/${pid}`), api(`/api/postings/${pid}/shortlist?top=3`)]);
    if (!ctx.isCurrent()) return;
    root.querySelectorAll(".hero-card").forEach((n) => n.remove());
    root.append(
      findCard({ title: "Find The Perfect Match", text: "Rank eligible students for any posting with one query on the match table.", big: fmt.short(ov.kpis.students),
        caption: "Students", people: top.map((t) => t.name), to: `#/shortlist?posting=${pid}` }),
      featureCard({ post: d.posting, reqs: d.requirements, extra: `${fmt.n(ov.kpis.at_risk)} students in this batch are flagged at risk.`,
        actions: [{ icon: "target", label: "Shortlist", run: () => go(`#/shortlist?posting=${pid}`) }, { icon: "flow", label: "Pipeline", run: () => go(`#/pipeline?posting=${pid}`) },
          { icon: "share", label: "Share", run: () => shareLink(`#/shortlist?posting=${pid}`) }] }));
  };
  const setBar = () => ctx.topbar.set({ title: "Home", sub: "TnP officer desk", filters: [
    { icon: "calendar", label: "Placement batch", value: app.cycle, options: cycleOptions(), onChange: (v) => { app.cycle = +v; app.posting = null; setBar(); draw(); } },
    { icon: "briefcase", label: "Featured posting", value: app.posting, options: postingOptions(app.cycle), onChange: (v) => { app.posting = +v; draw(); } },
    { icon: "tag", label: "Mode", value: "shortlist", options: [{ value: "shortlist", label: "Shortlist" }, { value: "early", label: "Early warning" }, { value: "dashboard", label: "Dashboard" }],
      onChange: (v) => go(`#/${v}`) }] });
  setBar();
  await draw();
}

async function recruiterHome(ctx, root) {
  ctx.topbar.set({ title: "Home", sub: "Recruiter desk" });
  const ov = await api("/api/me/overview");
  const posts = ov.postings;
  const top = posts[0];
  if (!top) { root.append(h("div", { class: "hero-card feature" }, h("b", {}, "No postings yet"))); return; }
  const d = await api(`/api/postings/${top.posting_id}`);
  const c = ov.company;
  root.append(
    findCard({ title: "Find The Perfect Match", text: `${c.name}: ${c.postings} postings across the batches. Open one to see its ranked shortlist.`, big: fmt.n(c.applications), caption: "Applications received", people: [], to: `#/shortlist?posting=${top.posting_id}` }),
    featureCard({ post: { ...d.posting }, reqs: d.requirements, extra: `${fmt.n(c.offers)} offers made so far.`,
      actions: [{ icon: "target", label: "Shortlist", run: () => go(`#/shortlist?posting=${top.posting_id}`) }, { icon: "flow", label: "Pipeline", run: () => go(`#/pipeline?posting=${top.posting_id}`) },
        { icon: "briefcase", label: "All postings", run: () => go("#/postings") }] }));
}

async function studentHome(ctx, root) {
  const ov = await api("/api/me/overview");
  const prof = ov.profile, best = ov.top_matches[0];
  const odds = prof.predicted_probability;
  root.append(
    h("div", { class: "hero-card find" }, h("h3", {}, "Your placement odds"),
      h("p", {}, prof.placement_status === "PLACED" ? `You are placed (${fmt.ctc(prof.offer_ctc)}). Congratulations.` : "Estimated from your CGPA, skills and profile, before the season starts."),
      h("div", { class: "stat-row" }, odds !== null && odds !== undefined ? ring(odds, { size: 96, stroke: 11, label: "" }) : chip("Not scored yet", "mute"),
        h("div", {}, h("div", { class: "big num", style: { fontSize: "30px" } }, `${fmt.n(Object.values(ov.status_counts).reduce((a, b) => a + b, 0))}`), h("small", {}, "applications so far")),
        h("button", { class: "round-btn", "aria-label": "See my matches", onclick: () => go("#/matches") }, icon("up", 20)))),
    best ? featureCard({ post: { role_title: best.role_title, company: best.company, ctc: best.ctc, min_cgpa: best.min_cgpa }, reqs: [],
      extra: `Your best match: ${fmt.score(best.match_score)} (${best.band.toLowerCase()}). ${best.eligible ? "You meet the CGPA cutoff." : "Your CGPA is below the cutoff."}`,
      actions: [{ icon: "spark", label: "Skill coach", run: () => go(`#/coach?posting=${best.posting_id}`) }, { icon: "target", label: "All matches", run: () => go("#/matches") },
        { icon: "flow", label: "Applications", run: () => go("#/applications") }] })
      : h("div", { class: "hero-card feature" }, h("b", {}, "No matches yet"), h("p", { class: "desc" }, "Match scores appear after the ML job has run.")));
}
