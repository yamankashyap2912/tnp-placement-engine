# Mapping to the project PDF (what was built, what changed, and why)

All eight phases are implemented. Phases 1-4 (database, data, both models) came first; Phases 5-8 (backend, TnP
dashboard, student portal with skill-gap coach, full website with role-based access) followed once the
database was approved. Instead of Streamlit, the dashboard, portal and website are **one web application**
(FastAPI + a no-build front end) with three role views, which is what Phase 8 asks for.

| PDF item | Status | Where |
|---|---|---|
| 10 entities with the listed attributes, PK/FK | done (+5 support tables) | `sql/01_schema.sql` |
| CHECK on cgpa, min_cgpa, proficiency_level; composite PKs on junctions | done (+ many more) | `01_schema.sql` |
| Trigger: Interview_Rounds REJECT/SELECT -> Applications.status | done (T1, T2) | `04_triggers.sql` |
| Trigger: final SELECT -> Placement_Outcomes row | done (T6) | `04_triggers.sql` |
| 3rd trigger | done: 13 triggers (validation, audit, ML refresh queue) | `04_triggers.sql` |
| `sp_shortlist_for_posting(posting_id, top_n)` | done | `05_procedures.sql` |
| `sp_student_application_summary(student_id)` | done | `05_procedures.sql` |
| ER diagram, normalised schema, sample queries | done | `docs/er_diagram.png`, `docs/DBMS_CONCEPTS.md`, `sql/demo_queries.sql` |
| Phase 2 data (real structure + synthetic generator) | replaced by the supplied `TnP_Dataset` (loaded and verified) | `data/`, `src/tnp/loader.py` |
| `Student_Features` view (+ `Posting_Features`) | done, extended | `06_views.sql` |
| Skill vectors + cosine -> Match_Scores | done: cosine, coverage (default), learned | `src/tnp/match.py` |
| Two-tower learned model (optional) | simplified to a gradient-boosted pair classifier (no deep-learning dependency, better held-out AUC than cosine) | `match.py` |
| Placement classifier: logistic regression baseline then small ANN | logistic regression + gradient boosting; ANN not needed (no gain on 19 tabular features) | `placement.py` |
| `Placement_Probability (student_id, probability, computed_at, cycle_year)` | done | `01_schema.sql` |
| Early-warning query | done | `sp_early_warning`, `v_early_warning` |
| Skill-gap coach by ablation (Phase 7 logic) | done in SQL and Python (the UI is not built) | `sp_skill_gap`, `match.skill_gap_ablation` |
| Phase 5 FastAPI: `/postings/{id}/shortlist`, `/students/{id}/matches`, `/students/{id}/probability`, `/companies/{id}/postings` | done: 34 endpoints (`docs/API_REFERENCE.md`); probability is returned inside `/api/students/{id}` and `/api/me/overview`; company postings via `/api/postings?company_id=` | `src/tnp/api/` |
| NL2SQL assistant on a restricted read-only DB user | done: rule-based question-to-SQL plus a guarded SELECT console, both on `tnp_readonly_user`; the PDF's own example question works | `src/tnp/api/assistant.py` |
| Phase 6 TnP dashboard: shortlist, early-warning panel filterable by branch/batch, company-side fill rate and match quality | done | `web/`, pages Dashboard, Shortlists, Early warning, Postings |
| Phase 7 student portal: own matches, missing skills that raise the score most | done | pages My matches, Skill coach, Applications, Profile |
| Phase 8 full website with role-based auth (TnP admin, recruiter, student) | done; the same API serves all three roles and every endpoint checks the role | `web/`, `src/tnp/api/security.py` |

## Deliberate deviations
1. **`interview_pass_rate` excluded from the default model** - it leaks the label (AUC 0.98); see `ML_DESIGN.md`.
   It is still computed in `Student_Features` (as PDF Section 4 shows) and usable via `--feature-set inseason`.
2. **Result vocabulary.** `Interview_Rounds.result` = `PENDING/PASS/REJECT/SELECT` and
   `Applications.status` = `APPLIED/IN_PROGRESS/SELECTED/REJECTED/WITHDRAWN`, as in the supplied dataset.
3. **One outcome per student** (`UNIQUE(student_id)`): the PDF calls it 1:1. If a student holds several
   offers, T6 keeps the highest CTC.
4. **Match_Scores stores own-cycle pairs only** (289,913 rows). The supplied `match_scores.csv`
   (all 578,000 pairs) is not loaded; our model regenerates the same values for the pairs that matter.
5. **Extra tables**: `Model_Runs`, `Application_Status_Log`, `Match_Refresh_Queue`,
   `Student_Academic_Profile` (supplied as optional data, used as extra ML features).
6. **Two indexes dropped** after measurement (see `DBMS_CONCEPTS.md` section 7).
