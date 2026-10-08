import { initShell, route } from "./shell.js";

const R = (load, extra = {}) => ({ load, ...extra });
initShell({
  login: R(() => import("./pages/login.js"), { full: true }),
  home: R(() => import("./pages/home.js"), { full: true }),
  dashboard: R(() => import("./pages/dashboard.js"), { roles: ["ADMIN"] }),
  shortlist: R(() => import("./pages/shortlist.js"), { roles: ["ADMIN", "RECRUITER"] }),
  students: R(() => import("./pages/students.js"), { roles: ["ADMIN"] }),
  student: R(() => import("./pages/student.js"), { roles: ["ADMIN"] }),
  postings: R(() => import("./pages/postings.js"), { roles: ["ADMIN", "RECRUITER"] }),
  early: R(() => import("./pages/early.js"), { roles: ["ADMIN"] }),
  pipeline: R(() => import("./pages/pipeline.js"), { roles: ["ADMIN", "RECRUITER"] }),
  insights: R(() => import("./pages/insights.js"), { roles: ["ADMIN"] }),
  health: R(() => import("./pages/health.js"), { roles: ["ADMIN"] }),
  assistant: R(() => import("./pages/assistant.js"), { roles: ["ADMIN"] }),
  matches: R(() => import("./pages/mine.js").then((m) => ({ default: m.matchesPage })), { roles: ["STUDENT"] }),
  coach: R(() => import("./pages/mine.js").then((m) => ({ default: m.coachPage })), { roles: ["STUDENT"] }),
  applications: R(() => import("./pages/mine.js").then((m) => ({ default: m.applicationsPage })), { roles: ["STUDENT"] }),
  profile: R(() => import("./pages/mine.js").then((m) => ({ default: m.profilePage })), { roles: ["STUDENT"] }),
});
route();
