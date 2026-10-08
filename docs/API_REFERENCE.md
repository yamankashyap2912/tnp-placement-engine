# API reference

_Generated from the running app by `python run.py api-reference`. Interactive docs: `/docs` while the server runs._

Authenticate with `POST /api/auth/login` and send `Authorization: Bearer <token>`. Every endpoint is a thin wrapper over a stored procedure, view or ML function; business rules are enforced by the database and surface as HTTP 409 with the rule's message.

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/api/applications` | admin, student | Apply a student to a posting (sp_apply_to_posting; eligibility trigger decides) |
| GET | `/api/applications/{application_id}/rounds` | any signed-in user | Interview rounds of one application |
| POST | `/api/applications/{application_id}/rounds` | admin, recruiter | Record the next interview round (sp_record_round; triggers move the status and create the offer) |
| POST | `/api/applications/{application_id}/withdraw` | admin, student | Withdraw a running application (sp_withdraw_application) |
| POST | `/api/assistant/ask` | admin | Plain-language question answered with read-only SQL (readonly account) |
| GET | `/api/assistant/examples` | admin | Example questions for the assistant |
| POST | `/api/assistant/sql` | admin | Guarded SELECT-only SQL console (readonly account, 500 rows, 8 s) |
| GET | `/api/audit/status-log` | admin | Recent application status changes (written by trigger T7) |
| POST | `/api/auth/change-password` | any signed-in user | Change own password |
| GET | `/api/auth/demo-accounts` | public | One-click demo sign-in shortcuts (disable with TNP_DEMO_MODE=0) |
| POST | `/api/auth/login` | public | Sign in, returns a signed session token |
| GET | `/api/auth/me` | any signed-in user | Who am I |
| GET | `/api/companies` | admin | Company summary view |
| GET | `/api/early-warning` | admin | Unplaced students below a probability threshold (sp_early_warning) |
| GET | `/api/health/catalog` | admin | Tables, views, routines, triggers, indexes, row counts, index benchmark |
| GET | `/api/health/explain/{posting_id}` | admin | EXPLAIN plan of the shortlist query |
| GET | `/api/health/integrity` | admin | The 20 data-quality rules (v_integrity_checks) |
| GET | `/api/insights` | admin | Model comparison, calibration, importance, run history, refresh queue |
| GET | `/api/me/overview` | student, recruiter | Home data for a student or recruiter |
| GET | `/api/meta/filters` | any signed-in user | Cycles, branches, skills and the postings visible to the caller |
| POST | `/api/ml/match` | admin | Re-score Match_Scores (coverage | cosine | learned) as the ML account |
| POST | `/api/ml/report` | admin | Regenerate the evaluation report and charts |
| POST | `/api/ml/train` | admin | Retrain the placement model and rewrite Placement_Probability |
| POST | `/api/ml/worker` | admin | Process Match_Refresh_Queue (incremental re-scoring) |
| GET | `/api/overview` | admin | KPIs and chart data for a batch (sp_dashboard_kpis, views) |
| GET | `/api/postings` | any signed-in user | Posting statistics (v_posting_stats), filterable |
| GET | `/api/postings/{posting_id}` | any signed-in user | One posting: requirements, funnel, statistics |
| GET | `/api/postings/{posting_id}/pipeline` | admin, recruiter | Everyone who applied to a posting (sp_posting_pipeline) |
| GET | `/api/postings/{posting_id}/shortlist` | admin, recruiter | Ranked shortlist (sp_shortlist_for_posting / sp_shortlist_eligible_not_applied) |
| POST | `/api/postings/{posting_id}/status` | admin, recruiter | Open or close applications (sp_open_posting / sp_close_posting) |
| GET | `/api/students` | admin | Student directory with filters and paging |
| GET | `/api/students/{student_id}` | any signed-in user | Profile, applications, skills of one student (sp_student_application_summary) |
| GET | `/api/students/{student_id}/matches` | any signed-in user | A student's ranked postings (sp_student_matches) |
| GET | `/api/students/{student_id}/skill-gap/{posting_id}` | any signed-in user | Skill-gap coach for a student and posting (sp_skill_gap) |
