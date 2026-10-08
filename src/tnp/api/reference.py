"""Generate docs/API_REFERENCE.md from the running FastAPI app (so it can never go stale)."""
from __future__ import annotations

from ..config import DOCS_DIR
from .routes_core import router as core_router
from .routes_ops import router as ops_router


WHAT = {
    "apply": "Apply a student to a posting (sp_apply_to_posting; eligibility trigger decides)",
    "rounds": "Interview rounds of one application",
    "record_round": "Record the next interview round (sp_record_round; triggers move the status and create the offer)",
    "withdraw": "Withdraw a running application (sp_withdraw_application)",
    "ask": "Plain-language question answered with read-only SQL (readonly account)",
    "examples": "Example questions for the assistant",
    "sql_console": "Guarded SELECT-only SQL console (readonly account, 500 rows, 8 s)",
    "status_log": "Recent application status changes (written by trigger T7)",
    "change_password": "Change own password",
    "demo_accounts": "One-click demo sign-in shortcuts (disable with TNP_DEMO_MODE=0)",
    "login": "Sign in, returns a signed session token",
    "me": "Who am I",
    "companies": "Company summary view",
    "early_warning": "Unplaced students below a probability threshold (sp_early_warning)",
    "catalog": "Tables, views, routines, triggers, indexes, row counts, index benchmark",
    "explain": "EXPLAIN plan of the shortlist query",
    "integrity": "The 20 data-quality rules (v_integrity_checks)",
    "insights": "Model comparison, calibration, importance, run history, refresh queue",
    "my_overview": "Home data for a student or recruiter",
    "filters": "Cycles, branches, skills and the postings visible to the caller",
    "ml_match": "Re-score Match_Scores (coverage | cosine | learned) as the ML account",
    "ml_report": "Regenerate the evaluation report and charts",
    "ml_train": "Retrain the placement model and rewrite Placement_Probability",
    "ml_worker": "Process Match_Refresh_Queue (incremental re-scoring)",
    "overview": "KPIs and chart data for a batch (sp_dashboard_kpis, views)",
    "postings": "Posting statistics (v_posting_stats), filterable",
    "posting_detail": "One posting: requirements, funnel, statistics",
    "pipeline": "Everyone who applied to a posting (sp_posting_pipeline)",
    "shortlist": "Ranked shortlist (sp_shortlist_for_posting / sp_shortlist_eligible_not_applied)",
    "posting_status": "Open or close applications (sp_open_posting / sp_close_posting)",
    "students": "Student directory with filters and paging",
    "student_360": "Profile, applications, skills of one student (sp_student_application_summary)",
    "student_matches": "A student's ranked postings (sp_student_matches)",
    "skill_gap": "Skill-gap coach for a student and posting (sp_skill_gap)",
}


def _access(route) -> str:
    roles = None
    authed = False
    for dep in route.dependant.dependencies:
        call = dep.call
        if getattr(call, "roles", None):
            roles = call.roles
        elif getattr(call, "__name__", "") == "current_user":
            authed = True
    if roles:
        return ", ".join(r.lower() for r in roles)
    return "any signed-in user" if authed else "public"


def generate() -> None:
    rows = []
    for r in [*core_router.routes, *ops_router.routes]:
        if not getattr(r, "path", "").startswith("/api") or not hasattr(r, "methods"):
            continue
        doc = WHAT.get(r.endpoint.__name__, "")
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append((r.path, m, _access(r), doc or r.name.replace("_", " ")))
    rows.sort()
    lines = ["# API reference", "",
             "_Generated from the running app by `python run.py api-reference`. Interactive docs: `/docs` while the server runs._", "",
             "Authenticate with `POST /api/auth/login` and send `Authorization: Bearer <token>`. "
             "Every endpoint is a thin wrapper over a stored procedure, view or ML function; "
             "business rules are enforced by the database and surface as HTTP 409 with the rule's message.", "",
             "| Method | Path | Who | What |", "|---|---|---|---|"]
    lines += [f"| {m} | `{p}` | {a} | {d} |" for p, m, a, d in rows]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "API_REFERENCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote docs/API_REFERENCE.md ({len(rows)} endpoints)")
