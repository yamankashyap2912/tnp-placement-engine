# Viva guide

## 10-minute live demo script
Prerequisite: `python run.py all` has been run once.

| Min | Do | Say |
|---|---|---|
| 0-1 | Show `docs/er_diagram.png` | 15 tables; the two M:N relationships are resolved by `Student_Skills` and `Posting_Requirements`; green tables are written only by the ML layer |
| 1-3 | `CALL sp_shortlist_for_posting(73, 10);` then `EXPLAIN` of the ORDER BY (`sql/demo_queries.sql` 1-2) | the shortlist is a plain `ORDER BY match_score DESC` on a column only the model fills; the index makes it ~45x faster |
| 3-6 | `python run.py demo` (steps 2-4) | **the live moment**: a student upskills -> trigger queues him -> worker re-scores 41 pairs -> he jumps from rank 38 to rank 1; then triggers refuse a closed posting, a wrong cycle, a finished application; then apply -> rounds -> SELECT creates the outcome and the audit trail; everything is restored |
| 6-7 | `CALL sp_early_warning(2026, 0.3, 3, 1);` | second model: unplaced students with low probability and few applications |
| 7-8 | `SELECT * FROM v_integrity_checks;` | 20 business rules as queries, 0 violations |
| 8-9 | `python run.py benchmark` output / `reports/index_benchmark.csv` | indexes are justified by measurement; two were removed because they did not pay off |
| 9-10 | `reports/evaluation_report.md` | cosine < coverage < learned; leakage finding |

## Website demo (3 minutes, after `python run.py serve`)
1. Sign in as the TnP officer (one click). Home shows the featured posting; change the posting in the top bar.
2. Shortlists: the ranked table; switch to "Eligible, not applied yet" (the outreach list).
3. Pipeline desk: Reopen the posting, apply student 4740, record two rounds, watch the status change and the audit
   trail appear (triggers at work). Pipeline desk also shows the closed-posting rule when you try before reopening.
4. Early warning: drag the threshold, filter a branch, export CSV, open a student.
5. Ask the data: click the example "Students matched above 0.8 for the Amazon SDE posting who haven't applied".
6. Database health: integrity checks, trigger list, index benchmark, EXPLAIN, ER diagram.
7. Sign out, sign in as the demo student: My matches, Apply, Skill coach.

## Questions you should be ready for

**Why two models instead of one?** Matching is a per-(student, posting) similarity/ranking problem, placement
probability a per-student classification problem. One model would blur both evaluations.

**Why is Match_Scores a table and not a computed column / view?** ML cost is unbounded, read cost must not be.
Precomputed rows + index on `(posting_id, match_score DESC)` = an indexed read; `Model_Runs` gives lineage;
`Match_Refresh_Queue` keeps it fresh incrementally.

**Is the schema normalised? Where did you denormalise?** 3NF. Denormalised on purpose: derived ML tables and
`Placement_Outcomes.offer_ctc` (historical fact). See `DBMS_CONCEPTS.md` section 2.

**How do you guarantee two officers don't create the same interview round?** `UNIQUE(application_id, round_no)`
plus `sp_record_round` locks the application row with `SELECT ... FOR UPDATE` inside a transaction.

**What happens if the ML job crashes halfway?** Write-back is one transaction (delete + insert): it rolls back,
the old scores remain, `Model_Runs` shows a `FAILED` row.

**Why do triggers AND constraints AND procedures?** Constraints = declarative single-row rules; triggers =
cross-table rules nobody can bypass (even raw SQL); procedures = transactional workflows and the stable API
for the future backend.

**How does the loader stay fast but safe?** Session flag `@tnp_bulk_load` skips workflow triggers only;
constraints, FKs and the eligibility trigger always run. `--via-triggers` proves the triggers reproduce the
dataset's statuses and outcomes with 0 differences.

**Why did you not use interview_pass_rate?** It is computed from the rounds that decide the label: AUC 0.98 by
leakage, and it cannot be known early. Honest model: 0.908.

**Is 0.91 AUC real-world accuracy?** No - the dataset is synthetic with labels generated from skills/CGPA.
It validates the pipeline.

**How would you scale it?** Partition `Applications`/`Interview_Rounds` by cycle year, move the nightly
refresh to the incremental queue (already built), add read replicas for dashboards, keep `Match_Scores` own-cycle only.

**Security?** Four roles (`tnp_admin`, `tnp_officer`, `ml_service`, `readonly_analyst`), column-level grants,
no PII for the analyst role; tested in `tests/test_security.py`.

**What isolation level and why does it matter here?** InnoDB default `REPEATABLE READ`; the shortlist reads a
consistent snapshot even while the worker updates scores.

**How does the website relate to the database?** It is a thin layer. Each page calls an endpoint that calls a stored
procedure or view; rules (eligibility, round order, offer creation, audit) stay in triggers, so the website
cannot bypass them. The browser never talks to MySQL, the API never sees more than the officer account's
privileges, and the assistant runs on a read-only account without PII columns.

**How is access controlled?** Three layers: the API checks the role of the signed token on every call, ownership
checks stop a student opening another student or a recruiter another company's posting, and the database
accounts themselves are least-privilege. Tests in `tests/test_api.py` and `tests/test_security.py` cover each layer.

**What is not done?** Production hardening (HTTPS, a reverse proxy, a real secret, per-user password reset email)
and a trained-on-real-data model. See the README "Going to production" list.
