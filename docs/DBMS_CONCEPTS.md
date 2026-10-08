# DBMS concepts used in this project (viva reference)

Everything below is implemented in `sql/` and verified by `tests/` and `python run.py demo`.

## 1. Conceptual / logical design

Entities (17 tables): the 10 from the project PDF, plus 7 that production use needs:
`Model_Runs` (ML lineage), `Application_Status_Log` (audit), `Match_Refresh_Queue`
(incremental ML refresh), `Student_Academic_Profile` (optional 1:1 extension from the dataset) and, for
the web application, `App_Users` and `Login_Audit` (section 11).
`Applications.status` and `Job_Postings.status` were added because the workflow needs them.

| Relationship | Cardinality | Implemented by |
|---|---|---|
| Students - Skills | M:N | `Student_Skills` (PK `student_id, skill_id`, attributes `proficiency_level`, `evidence_source`) |
| Job_Postings - Skills | M:N | `Posting_Requirements` (PK `posting_id, skill_id`, `required_level`, `weight`) |
| Students - Job_Postings | M:N | `Applications` (UNIQUE `student_id, posting_id`) |
| Applications - Interview_Rounds | 1:N | `Interview_Rounds` (UNIQUE `application_id, round_no`) |
| Companies - Job_Postings | 1:N | FK `Job_Postings.company_id` |
| Students - Placement_Outcomes | 1:1 | UNIQUE FK `Placement_Outcomes.student_id` |
| Students x Job_Postings (derived) | M:N | `Match_Scores` (ML output, UNIQUE pair) |
| Students - Placement_Probability | 1:N by cycle | PK `student_id, cycle_year` |

ER diagram: `docs/er_diagram.png` (generated from the live foreign keys by `python run.py er-diagram`).

## 2. Normalization (1NF -> 3NF)

* **1NF** - a flat `Students(name, skills, ...)` table would store a *list* of skills in one cell.
  `Student_Skills` gives one atomic fact per row. Same for requirements.
* **2NF** - in `Student_Skills`, `proficiency_level` and `evidence_source` depend on the *whole* key
  `(student_id, skill_id)`; skill name/category live in `Skills` (they depend on `skill_id` alone).
  Same for `Posting_Requirements`.
* **3NF** - no transitive dependencies: company name/tier are in `Companies`, not repeated per posting;
  a student's branch/CGPA are not repeated per application.
* **Deliberate, documented denormalisation** (each with a reason):
  * `Match_Scores`, `Placement_Probability` - *derived* data, precomputed so the ranked query is an
    indexed read instead of an ML run per request; `Model_Runs` records which run produced them.
  * `Placement_Outcomes.offer_ctc` - a historical fact: it must not change if the posting is edited later.
    (A check in `v_integrity_checks` proves it equals the posting CTC at load time.)
  * `Application_Status_Log.old_status/new_status` as VARCHAR - an immutable log must survive a later
    change of the ENUM.

## 3. Constraints (declarative integrity)

PK on every table; surrogate `AUTO_INCREMENT` keys for entities, composite natural keys for junctions.
UNIQUE: email, skill name, company name, one application per (student, posting), one outcome per student,
one Match_Scores row per pair, round numbers unique per application.
CHECK (enforced from MySQL 8.0.16): CGPA 0-10, proficiency/required level 1-5, weight in (0,1], CTC > 0,
score/probability in [0,1], marks 0-100, `chk_po_consistency` (PLACED <=> posting and CTC present).
FK actions chosen per relationship: `CASCADE` for owned child rows (a deleted student takes skills,
applications, rounds with it), `RESTRICT` where history must not vanish (a company with postings, a skill
still required by a posting, a posting with outcomes), `SET NULL` for ML lineage.
Full per-column list: `docs/DATA_DICTIONARY.md`.

## 4. Triggers (13) - business rules inside the database

| # | Trigger | Event | Purpose |
|---|---|---|---|
| T1 | `trg_round_after_insert` | AFTER INSERT Interview_Rounds | REJECT -> application REJECTED, SELECT -> SELECTED, otherwise IN_PROGRESS (PDF requirement) |
| T2 | `trg_round_after_update` | AFTER UPDATE Interview_Rounds | same when a PENDING result is later decided |
| T3 | `trg_round_before_insert_rules` | BEFORE INSERT Interview_Rounds | no rounds on finished applications, sequential `round_no`, dates not before application / previous round |
| T4 | `trg_app_before_insert_eligibility` | BEFORE INSERT Applications | posting OPEN, CGPA >= min_cgpa, same placement cycle, date >= posting date. **Never bypassed.** |
| T5 | `trg_app_before_update_status_guard` | BEFORE UPDATE Applications | (student, posting) immutable; finished applications cannot be re-opened |
| T6 | `trg_app_after_update_placement` | AFTER UPDATE Applications | final SELECT creates the `Placement_Outcomes` row (PDF requirement); a better later offer upgrades it |
| T7 | `trg_app_after_update_audit` | AFTER UPDATE Applications (`FOLLOWS` T6) | row in `Application_Status_Log` with `USER()` |
| T8-T13 | `trg_ss_*`, `trg_pr_*` | AFTER INSERT/UPDATE/DELETE on Student_Skills, Posting_Requirements | enqueue the student / posting in `Match_Refresh_Queue` (collapsing repeated edits via the PK) |

`@tnp_bulk_load = 1` is a *session* switch used by the CSV loader to skip workflow triggers (T3, T5,
T8-T13) for speed. Constraints, FKs and T4 still run. `python run.py load-data --via-triggers` loads
applications as `APPLIED` and lets T1/T3/T6/T7 derive every status and 3,032 PLACED outcomes - the result is
compared with the CSV ground truth (0 differences, 54,976 audit rows).

## 5. Stored routines (23)

Functions: `fn_cycle_year`, `fn_is_eligible`, `fn_match_band`. Four more procedures serve the web app (section 11).

| Procedure | Kind | What it shows |
|---|---|---|
| `sp_shortlist_for_posting(posting, n)` | read | PDF requirement; `RANK() OVER`, ties, cohort filter, served by `idx_ms_posting_score` |
| `sp_shortlist_eligible_not_applied` | read | `NOT EXISTS` anti-join: whom to nudge |
| `sp_student_application_summary(student)` | read | PDF requirement; 3 result sets, correlated subqueries |
| `sp_skill_gap(student, posting)` | read | skill-gap coach in pure SQL (`potential_gain`) |
| `sp_early_warning(cycle, threshold, max_apps, exclude_placed)` | read | PDF's "probability below threshold and fewer than N applications" |
| `sp_placement_report(cycle)` | read | 3 aggregate result sets (branch, tier, top recruiters) |
| `sp_apply_to_posting` | write | transaction, `SELECT ... FOR UPDATE` on the student, duplicate-key handler (1062), `RESIGNAL` |
| `sp_record_round` | write | locks the application row so two officers cannot create the same `round_no` |
| `sp_withdraw_application`, `sp_close_posting` | write | controlled write paths |
| `sp_refresh_match_scores_baseline / _for_student / _for_posting` | ML maintenance | SQL implementation of the coverage model, `INSERT ... ON DUPLICATE KEY UPDATE` |
| `sp_process_refresh_queue_baseline` | ML maintenance | cursor + optimistic concurrency (a queue entry is marked DONE only if its microsecond `queued_at` is unchanged, i.e. not re-queued meanwhile) |
| `sp_apply_round_result` | internal | shared by T1/T2 |

## 6. Views (12)

*Feature layer for ML* (PDF Section 4: "feature engineering lives in SQL"): `Student_Features`,
`Posting_Features`, `ML_Placement_Dataset`.
*Reporting:* `v_posting_stats`, `v_company_summary`, `v_branch_placement_summary`, `v_application_funnel`,
`v_student_status`, `v_early_warning`.
*Governance:* `v_integrity_checks` - 20 business rules as queries (15 ERROR rules must be 0).
*Catalogue:* `v_catalog_objects`, `v_catalog_indexes` (metadata for the Database health page).

## 7. Indexes - and the evidence

Measured with `python run.py benchmark` (MySQL 8 `INVISIBLE` indexes: same table, optimizer ignores the
index; times are the best of 7 runs on the dev machine (they vary a little run to run), 7,225 students / 289,913 match scores):

| Index | Query | without | with | speed-up |
|---|---|---|---|---|
| `idx_ms_posting_score (posting_id, match_score DESC)` | top 20 for a posting | 49.8 ms | 1.1 ms | ~45x |
| `idx_ir_type_result` | rejects per round type | 15.1 ms | 1.9 ms | ~8x |
| `idx_app_date` | applications in a month | 10.1 ms | 1.5 ms | ~6.7x |
| `idx_students_cohort (batch_year, branch, cgpa)` | cohort filter | 2.1 ms | 0.3 ms | ~6.6x |
| `idx_pp_cycle_prob` | early-warning scan | 1.8 ms | 0.6 ms | ~3.2x |
| `idx_po_status_ctc` | placed with CTC >= 20 | 2.9 ms | 1.8 ms | ~1.6x |

Two indexes that were first designed (`Job_Postings(status, posted_date)`, `Match_Scores(student_id,
match_score)`) showed **no** gain and were removed: the first table has 80 rows, and the second is already
covered by the unique key `(student_id, posting_id)`. Every index costs storage and write time, so
"measure, then keep" is the policy. Exact timings differ per machine; the ordering does not.
Why `Match_Scores` is a table and not a computed column: the ML model can get arbitrarily expensive, the
read path must not (PDF Section 7). Precompute once, read through the index, track lineage in `Model_Runs`.

## 8. Transactions, concurrency, ACID

InnoDB (default isolation `REPEATABLE READ`). Multi-statement writes are wrapped in explicit transactions
with an `EXIT HANDLER FOR SQLEXCEPTION` that rolls back and re-raises. Pessimistic row locks
(`FOR UPDATE`) protect the two places where concurrent officers could collide (apply, record round).
The ML write-back is atomic: `DELETE` + bulk `INSERT` run in one transaction, so a failing model run rolls
back and the previous scores stay live; readers never see a half-written table (isolation).
The refresh queue uses optimistic concurrency (see above). Durability = InnoDB redo log + `scripts/backup.sh`
(`mysqldump --single-transaction`, consistent snapshot without blocking writers).

## 9. Security (least privilege, `sql/08_security.sql`)

| Role / user | Can | Cannot |
|---|---|---|
| `tnp_admin` | everything | - |
| `tnp_officer` (`tnp_officer_user`) | read all, `EXECUTE` procedures, insert/update Applications and Interview_Rounds | edit postings directly (only via `sp_close_posting`), delete anything, touch outcomes |
| `ml_service` (`tnp_ml_user`) | read all; write `Match_Scores`, `Placement_Probability`, `Model_Runs`, `Match_Refresh_Queue` | modify students, postings, applications; delete lineage |
| `readonly_analyst` (`tnp_readonly_user`) | read non-sensitive columns and views | read `email`, `resume_url`, academic profile; write; call procedures |

`readonly_analyst` is the account the NL2SQL assistant of project Phase 5 should use. Passwords come from
`.env`; no secret is committed. All four privilege profiles are covered by `tests/test_security.py`.

## 9b. Data loading and quality

`load_dataset()` loads parents before children (FK order), checks row counts per table against the dataset
specification, and runs the whole eligibility trigger on all 31,520 applications. Afterwards
`v_integrity_checks` must show 0 failing ERROR rules. The dataset's own `match_scores.csv` is **not**
loaded: Match_Scores is produced by this project's model (the dataset file equals the coverage formula
exactly - verified, max difference 0.0).

## 10. Advanced SQL used

Window functions (`RANK`, `ROW_NUMBER`, running `SUM ... OVER`), CTEs, correlated subqueries, `NOT EXISTS`
anti-join and relational division (`sql/demo_queries.sql` #11), `INSERT ... ON DUPLICATE KEY UPDATE`
(upsert), conditional aggregation, cursors, `SIGNAL/RESIGNAL`, JSON columns (`Model_Runs.params`, `metrics`),
`ENUM`, roles, invisible indexes, `EXPLAIN`.

## 11. The application layer (`sql/09_app_layer.sql`)

The website adds no business logic outside the database. What it needs is itself SQL:

| Object | Purpose |
|---|---|
| `App_Users` | accounts for ADMIN / RECRUITER / STUDENT. A CHECK constraint ties the role to the right link: a student account must point at a student, a recruiter at a company, an admin at neither. Deleting a student or company cascades to its account. Passwords are stored as salted scrypt hashes. |
| `Login_Audit` | every login attempt, successful or not |
| `sp_open_posting` | counterpart of `sp_close_posting` |
| `sp_dashboard_kpis(cycle)` | one-row KPI summary for the dashboard |
| `sp_student_matches(student, only_eligible, n)` | a student's own ranked postings with eligibility and application state |
| `sp_posting_pipeline(posting)` | everyone who applied to a posting with round progress |
| `v_catalog_objects`, `v_catalog_indexes`, `sp_catalog_triggers` | read-only catalogue; the trigger list is a definer-rights procedure because `information_schema.triggers` is hidden from accounts without the TRIGGER privilege |

Privilege design: the API connects as `tnp_officer` (procedures plus the few writes it needs). The ML account
is limited to an explicit list of tables, so it **cannot read `App_Users`**; `readonly_analyst` has no grant on
it either. `setup-db` also revokes stale grants first, because MySQL keeps privileges of a dropped database
name and a rebuilt database would otherwise inherit them from an older security script
(`tests/test_security.py::test_ml_and_readonly_cannot_read_password_hashes` caught exactly this).
