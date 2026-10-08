# TnP Dataset (guide-compatible edition)

A synthetic placement dataset for the **Phase 1 guide's schema**: 7,225 students, 80 postings, 31,520 applications.
It loads into the guide's tables **without changing a single table, column or constraint**
(`schema_only.sql` is built from the same code as `phase1_complete.sql`).

All values are synthetic. Company names are real recruiters used only for realism; CTCs, requirements,
dates and outcomes are generated. This dataset was derived from the earlier `Data.zip` (which followed the
original project PDF) and converted to match the guide.

## Quick start (about 2 minutes)

1. Unzip this folder anywhere.
2. In MySQL Workbench: File > Open SQL Script > `schema_only.sql` > click the lightning bolt.
   This creates a **new, empty** database `placement_full`. Your `placement_db` is not touched.
3. Open a Command Prompt in this folder and run:
   ```
   pip install pandas pymysql
   python load_dataset.py --user root --password YOUR_PASSWORD
   ```
   (Linux/Mac with a socket: add `--socket /path/to/mysqld.sock`. Other options: `python load_dataset.py --help`.)
4. In Workbench open `verify_dataset.sql` and run it. **All 20 rows must say PASS.**

Do not load these CSVs into `placement_db`: its IDs 1-12 belong to the guide's sample data and would collide.

## Folder contents

| File | What it is |
|---|---|
| `schema_only.sql` | The guide's complete schema (12 tables, 5 triggers, 4 procedures, 2 views), no data |
| `load_dataset.py` | Loader (parents before children, row-count check on every table) |
| `verify_dataset.sql` | 20 integrity checks, all PASS after a correct load |
| `data/*.csv` | The 10 data tables, one CSV per table |
| `optional/` | Extra material that is **not** part of the guide's 12 tables (see the end) |

Empty cells in the CSVs mean NULL (only `placement_outcomes.posting_id`, `offer_ctc`, `offer_date` for NOT_PLACED students).

## The 10 data files

| CSV | Table | Rows | Notes |
|---|---|---|---|
| `companies.csv` | Companies | 22 | 6 Tier 1, 8 Tier 2, 8 Tier 3 |
| `skills.csv` | Skills | 49 | categories mapped to the guide's 7 values |
| `students.csv` | Students | 7,225 | batch 2025: 3,156, batch 2026: 4,069; branches CSE, CSE-AI, IT, ECE; CGPA 6.5 to 9.1 |
| `job_postings.csv` | Job_Postings | 80 | two cycles (Aug to Jan); CTC 3.5 to 44.5 LPA |
| `posting_requirements.csv` | Posting_Requirements | 738 | 7 to 11 skills per posting, weights sum to exactly 1.00 |
| `student_skills.csv` | Student_Skills | 62,432 | levels 1 to 5 |
| `applications.csv` | Applications | 31,520 | 3,032 SELECTED, 28,488 REJECTED |
| `interview_rounds.csv` | Interview_Rounds | 80,076 | PASS 51,495, REJECT 25,549, SELECT 3,032 |
| `placement_outcomes.csv` | Placement_Outcomes | 7,225 | 3,032 PLACED (42%), 4,193 NOT_PLACED |
| `match_scores.csv` | Match_Scores | 578,000 | every student x every posting (7,225 x 80) |

`Application_Status_Log` and `Placement_Probability` have no CSV: the first is filled by a trigger, the second by the Phase 4 model.

## What was changed to fit the guide

| Area | Earlier dataset | Now |
|---|---|---|
| `students.email` | missing (guide: NOT NULL UNIQUE) | added: `firstname.lastname.<id>@example.edu` (unique) |
| `skills.category` | 10 categories | mapped to the guide's 7: Programming, Framework (web), Data & AI (ML + databases), Tools & DevOps, Core CS (CS fundamentals, security, embedded), Soft Skill, Testing. The original category of every skill is kept in `optional/skills_original_category.csv` |
| `student_skills.evidence_source` | 7 values | Coursework and Placement Training became Course; Extracurricular became Project |
| `interview_rounds.round_type` | includes CODING, GROUP_DISCUSSION | CODING became TECHNICAL, GROUP_DISCUSSION became GD |
| `interview_rounds.result` | PASS / FAIL | FAIL became REJECT; the last round of every SELECTED application became SELECT (the guide's meanings) |
| `interview_rounds.round_no` | missing (guide: required) | added (1, 2, 3, ... in date order per application) |
| `posting_requirements.weight` | 3 decimals (guide: DECIMAL(3,2)) | rounded to 2 decimals so every posting still sums to exactly 1.00 |
| `placement_outcomes.offer_date` | not tied to the rounds | set to the date of the SELECT round, which is exactly what the guide's Trigger 3 records |
| `job_postings.status` | missing | added; loaded as OPEN, then the loader closes all postings after the applications are in (Trigger 5 blocks applications to closed postings, as in guide Part 6.5) |
| `match_scores` | 289,913 same-year pairs, cosine formula | 578,000 rows produced by the guide's own `sp_refresh_match_scores_baseline()` |
| `student_academic_profile` | in the main set | moved to `optional/` (the guide has no such table) |

Everything else (IDs, names, CGPAs, dates, applications, statuses, outcomes, requirements) is unchanged.

## Why match_scores has 578,000 rows

The guide defines Match_Scores as one row per (student, posting) pair, produced by the baseline procedure.
The file now equals what that procedure produces, so re-running `CALL sp_refresh_match_scores_baseline();`
changes nothing (tested: identical checksum before and after; the run takes about 35 seconds).
Note that the shortlist ranks all 7,225 students, including other batch years. To restrict it to the posting's own
placement year, join `Students` and filter `batch_year` (a posting's cycle year is `YEAR(posted_date)`, plus 1 if the month is 8 or later).
The scores carry real signal for the ML phases: selected applications average 0.54 versus 0.43 for rejected ones.

## Two ways to load

* **Direct (default).** Applications arrive with their final statuses and the outcomes come from the CSV.
  This is the fast path the guide describes in Part 13. The audit log stays empty.
* **Through the triggers:** `python load_dataset.py --via-triggers`.
  Applications arrive as APPLIED, the interview rounds fire the guide's triggers, and the triggers set every status,
  create all 3,032 PLACED outcomes and write the audit trail (54,976 rows in `Application_Status_Log`).
  Tested: the result is identical to the direct load (0 differences in statuses and outcomes). It takes about a minute longer.
  The only difference is that `outcome_id` values are assigned by the database.

## What was tested

On a clean MySQL 8.0 server using the unmodified guide schema: both load modes finished with every row count
matching; `verify_dataset.sql` returned 20 of 20 PASS in both modes; `sp_shortlist_for_posting`,
`sp_student_application_summary`, `Student_Features` (7,225 rows, about 1 second) and `Posting_Features` all work.

## Good to know

* The guide's sample outputs (Parts 5 to 11) describe the 12-student sample database. On this dataset the numbers differ.
  Use `placement_db` for the guide walkthrough and the viva demo, and `placement_full` for Phases 2 to 8.
* After a large load or refresh, MySQL does housekeeping in the background. In my test environment a view query was slow
  for a short while right after a bulk write and then ran in about a second. If a query seems stuck, wait a minute and retry.
* The script that generated the original data is not included.

## optional/

* `student_academic_profile.csv`: internships, projects, certifications, aptitude score, soft-skills rating, SSC/HSC marks, etc.
  (7,225 rows). Useful as extra ML features. Load it with `python load_dataset.py --with-academic-profile`
  (creates a 13th table, `Student_Academic_Profile`).
* `skills_original_category.csv`: each skill with its original category and the guide category it was mapped to.
