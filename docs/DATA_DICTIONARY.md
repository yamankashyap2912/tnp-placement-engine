# Data dictionary

_Generated from the live database by `python run.py data-dictionary`._

## App_Users

Web-application accounts; the role decides what the API lets a user see and do

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| user_id | `int unsigned` | NO | PK |  | auto_increment |
| username | `varchar(120)` | NO | UNIQUE |  |  |
| password_hash | `varchar(255)` | NO |  |  | scrypt$salt$hash - see src/tnp/api/security.py |
| role | `enum('ADMIN','RECRUITER','STUDENT')` | NO |  |  |  |
| display_name | `varchar(100)` | NO |  |  |  |
| student_id | `int unsigned` | YES | UNIQUE |  | FK -> Students.student_id (ON DELETE CASCADE) |
| company_id | `int unsigned` | YES | index |  | FK -> Companies.company_id (ON DELETE CASCADE) |
| is_active | `tinyint(1)` | NO |  | 1 |  |
| created_at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |
| last_login_at | `timestamp` | YES |  |  |  |

**CHECK constraints**

- `chk_user_role_link`: `(((`role` = _utf8mb4\'ADMIN\') and (`student_id` is null) and (`company_id` is null)) or ((`role` = _utf8mb4\'STUDENT\') and (`student_id` is not null) and (`company_id` is null)) or ((`role` = _utf8mb4\'RECRUITER\') and (`company_id` is not null) and (`student_id` is null)))`

**Indexes**

- `idx_user_company` (non-unique): company_id
- `PRIMARY` (unique): user_id
- `uq_user_student` (unique): student_id
- `uq_user_username` (unique): username

## Application_Status_Log

Audit trail written by trigger on every status change

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| log_id | `bigint unsigned` | NO | PK |  | auto_increment |
| application_id | `int unsigned` | NO | index |  | FK -> Applications.application_id (ON DELETE CASCADE) |
| old_status | `varchar(15)` | NO |  |  |  |
| new_status | `varchar(15)` | NO |  |  |  |
| changed_at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |
| changed_by | `varchar(100)` | NO |  |  |  |

**Indexes**

- `idx_log_app` (non-unique): application_id
- `PRIMARY` (unique): log_id

## Applications

M:N Students-Postings: one application per pair

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| application_id | `int unsigned` | NO | PK |  | auto_increment |
| student_id | `int unsigned` | NO | index |  | FK -> Students.student_id (ON DELETE CASCADE) |
| posting_id | `int unsigned` | NO | index |  | FK -> Job_Postings.posting_id (ON DELETE RESTRICT) |
| applied_date | `date` | NO | index |  |  |
| status | `enum('APPLIED','IN_PROGRESS','SELECTED','REJECTED','WITHDRAWN')` | NO |  | APPLIED |  |

**Indexes**

- `idx_app_date` (non-unique): applied_date
- `idx_app_posting_status` (non-unique): posting_id,status
- `PRIMARY` (unique): application_id
- `uq_app_student_posting` (unique): student_id,posting_id

## Companies

Recruiting companies

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| company_id | `int unsigned` | NO | PK |  | auto_increment |
| name | `varchar(100)` | NO | UNIQUE |  |  |
| sector | `varchar(60)` | NO |  |  |  |
| hq_city | `varchar(60)` | NO |  |  |  |
| tier | `enum('Tier 1','Tier 2','Tier 3')` | NO |  |  |  |

**Indexes**

- `PRIMARY` (unique): company_id
- `uq_companies_name` (unique): name

## Interview_Rounds

Ordered interview rounds of one application

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| round_id | `int unsigned` | NO | PK |  | auto_increment |
| application_id | `int unsigned` | NO | index |  | FK -> Applications.application_id (ON DELETE CASCADE) |
| round_no | `tinyint unsigned` | NO |  |  |  |
| round_type | `enum('APTITUDE','TECHNICAL','GD','HR')` | NO | index |  |  |
| round_date | `date` | NO |  |  |  |
| result | `enum('PENDING','PASS','REJECT','SELECT')` | NO |  | PENDING |  |

**CHECK constraints**

- `chk_ir_roundno`: `(`round_no` >= 1)`

**Indexes**

- `idx_ir_type_result` (non-unique): round_type,result
- `PRIMARY` (unique): round_id
- `uq_round_app_no` (unique): application_id,round_no

## Job_Postings

A role offered by a company in one placement cycle

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| posting_id | `int unsigned` | NO | PK |  | auto_increment |
| company_id | `int unsigned` | NO | index |  | FK -> Companies.company_id (ON DELETE RESTRICT) |
| role_title | `varchar(100)` | NO |  |  |  |
| ctc | `decimal(5,2)` | NO |  |  | CTC in LPA |
| min_cgpa | `decimal(4,2)` | NO |  | 0.00 |  |
| posted_date | `date` | NO |  |  |  |
| status | `enum('OPEN','CLOSED')` | NO |  | OPEN |  |

**CHECK constraints**

- `chk_jp_ctc`: `(`ctc` > 0)`
- `chk_jp_mincgpa`: `(`min_cgpa` between 0 and 10)`

**Indexes**

- `idx_jp_company` (non-unique): company_id
- `PRIMARY` (unique): posting_id

## Login_Audit

Login attempts, successful or not

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| log_id | `bigint unsigned` | NO | PK |  | auto_increment |
| username | `varchar(120)` | NO | index |  |  |
| success | `tinyint(1)` | NO |  |  |  |
| client_ip | `varchar(64)` | YES |  |  |  |
| at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |

**Indexes**

- `idx_login_user_time` (non-unique): username,at
- `PRIMARY` (unique): log_id

## Match_Refresh_Queue

Triggers enqueue students/postings whose skills changed; a worker re-scores them

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| entity_type | `enum('STUDENT','POSTING')` | NO | PK |  |  |
| entity_id | `int unsigned` | NO | PK |  |  |
| status | `enum('PENDING','DONE')` | NO | index | PENDING |  |
| queued_at | `timestamp(6)` | NO |  | CURRENT_TIMESTAMP(6) | microsecond precision: lets the worker detect a re-queue while it was processing |
| processed_at | `timestamp(6)` | YES |  |  |  |

**Indexes**

- `idx_mrq_status` (non-unique): status,queued_at
- `PRIMARY` (unique): entity_type,entity_id

## Match_Scores

ML output: one row per (student, posting); the ORDER BY of the shortlist

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| score_id | `int unsigned` | NO | PK |  | auto_increment |
| student_id | `int unsigned` | NO | index |  | FK -> Students.student_id (ON DELETE CASCADE) |
| posting_id | `int unsigned` | NO | index |  | FK -> Job_Postings.posting_id (ON DELETE CASCADE) |
| match_score | `decimal(5,4)` | NO |  |  |  |
| computed_at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |
| model_run_id | `int unsigned` | YES | index |  | which ML run produced this row (NULL = SQL baseline); FK -> Model_Runs.run_id (ON DELETE SET NULL) |

**CHECK constraints**

- `chk_ms_score`: `(`match_score` between 0 and 1)`

**Indexes**

- `fk_ms_run` (non-unique): model_run_id
- `idx_ms_posting_score` (non-unique): posting_id,match_score
- `PRIMARY` (unique): score_id
- `uq_ms_pair` (unique): student_id,posting_id

## Model_Runs

Lineage of every ML run that wrote into the database

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| run_id | `int unsigned` | NO | PK |  | auto_increment |
| run_kind | `enum('MATCH','PLACEMENT')` | NO | index |  |  |
| model_name | `varchar(60)` | NO |  |  |  |
| params | `json` | YES |  |  |  |
| metrics | `json` | YES |  |  |  |
| rows_written | `int unsigned` | NO |  | 0 |  |
| status | `enum('RUNNING','SUCCESS','FAILED')` | NO |  | RUNNING |  |
| started_at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |
| finished_at | `timestamp` | YES |  |  |  |
| notes | `varchar(255)` | YES |  |  |  |

**Indexes**

- `idx_mr_kind_started` (non-unique): run_kind,started_at
- `PRIMARY` (unique): run_id

## Placement_Outcomes

Historical label table: one final outcome per student

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| outcome_id | `int unsigned` | NO | PK |  | auto_increment |
| student_id | `int unsigned` | NO | UNIQUE |  | FK -> Students.student_id (ON DELETE CASCADE) |
| posting_id | `int unsigned` | YES | index |  | FK -> Job_Postings.posting_id (ON DELETE RESTRICT) |
| final_status | `enum('PLACED','NOT_PLACED')` | NO | index |  |  |
| offer_ctc | `decimal(5,2)` | YES |  |  |  |
| offer_date | `date` | YES |  |  |  |

**CHECK constraints**

- `chk_po_consistency`: `(((`final_status` = _utf8mb4\'PLACED\') and (`posting_id` is not null) and (`offer_ctc` is not null)) or ((`final_status` = _utf8mb4\'NOT_PLACED\') and (`posting_id` is null) and (`offer_ctc` is null)))`

**Indexes**

- `idx_po_posting` (non-unique): posting_id
- `idx_po_status_ctc` (non-unique): final_status,offer_ctc
- `PRIMARY` (unique): outcome_id
- `uq_outcome_student` (unique): student_id

## Placement_Probability

ML output: predicted placement probability per student and cycle

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| student_id | `int unsigned` | NO | PK |  | FK -> Students.student_id (ON DELETE CASCADE) |
| cycle_year | `smallint` | NO | PK |  |  |
| probability | `decimal(5,4)` | NO |  |  |  |
| computed_at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |
| model_run_id | `int unsigned` | YES | index |  | FK -> Model_Runs.run_id (ON DELETE SET NULL) |

**CHECK constraints**

- `chk_pp_prob`: `(`probability` between 0 and 1)`

**Indexes**

- `fk_pp_run` (non-unique): model_run_id
- `idx_pp_cycle_prob` (non-unique): cycle_year,probability
- `PRIMARY` (unique): student_id,cycle_year

## Posting_Requirements

M:N Postings-Skills with required level and weight

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| posting_id | `int unsigned` | NO | PK |  | FK -> Job_Postings.posting_id (ON DELETE CASCADE) |
| skill_id | `int unsigned` | NO | PK |  | FK -> Skills.skill_id (ON DELETE RESTRICT) |
| required_level | `tinyint unsigned` | NO |  |  |  |
| weight | `decimal(3,2)` | NO |  |  | importance; weights of one posting sum to 1.00 |

**CHECK constraints**

- `chk_pr_level`: `(`required_level` between 1 and 5)`
- `chk_pr_weight`: `((`weight` > 0) and (`weight` <= 1))`

**Indexes**

- `idx_pr_skill` (non-unique): skill_id
- `PRIMARY` (unique): posting_id,skill_id

## Skills

Skill taxonomy shared by students and postings

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| skill_id | `int unsigned` | NO | PK |  | auto_increment |
| skill_name | `varchar(60)` | NO | UNIQUE |  |  |
| category | `enum('Programming','Framework','Data & AI','Tools & DevOps','Core CS','Soft Skill','Testing')` | NO |  |  |  |

**Indexes**

- `PRIMARY` (unique): skill_id
- `uq_skills_name` (unique): skill_name

## Student_Academic_Profile

Optional 1:1 academic/extra-curricular profile used as extra ML features

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| student_id | `int unsigned` | NO | PK |  | FK -> Students.student_id (ON DELETE CASCADE) |
| internships | `tinyint unsigned` | NO |  |  |  |
| projects | `tinyint unsigned` | NO |  |  |  |
| workshops_certifications | `tinyint unsigned` | NO |  |  |  |
| aptitude_test_score | `smallint unsigned` | NO |  |  |  |
| soft_skills_rating | `decimal(2,1)` | NO |  |  |  |
| extracurricular_activities | `enum('Yes','No')` | NO |  |  |  |
| placement_training | `enum('Yes','No')` | NO |  |  |  |
| ssc_marks | `smallint unsigned` | NO |  |  |  |
| hsc_marks | `smallint unsigned` | NO |  |  |  |

**CHECK constraints**

- `chk_sap_apt`: `(`aptitude_test_score` between 0 and 100)`
- `chk_sap_marks`: `((`ssc_marks` between 0 and 100) and (`hsc_marks` between 0 and 100))`
- `chk_sap_soft`: `(`soft_skills_rating` between 0 and 5)`

**Indexes**

- `PRIMARY` (unique): student_id

## Student_Skills

M:N Students-Skills with proficiency and evidence

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| student_id | `int unsigned` | NO | PK |  | FK -> Students.student_id (ON DELETE CASCADE) |
| skill_id | `int unsigned` | NO | PK |  | FK -> Skills.skill_id (ON DELETE RESTRICT) |
| proficiency_level | `tinyint unsigned` | NO |  |  | 1 (beginner) .. 5 (expert) |
| evidence_source | `enum('Course','Project','Certification','Internship','Self-Declared')` | NO |  | Self-Declared |  |

**CHECK constraints**

- `chk_ss_level`: `(`proficiency_level` between 1 and 5)`

**Indexes**

- `idx_ss_skill` (non-unique): skill_id
- `PRIMARY` (unique): student_id,skill_id

## Students

One row per student of the placement-eligible batches

| column | type | null | key | default | notes |
|---|---|---|---|---|---|
| student_id | `int unsigned` | NO | PK |  | auto_increment |
| name | `varchar(100)` | NO |  |  |  |
| email | `varchar(120)` | NO | UNIQUE |  |  |
| branch | `varchar(20)` | NO |  |  |  |
| cgpa | `decimal(4,2)` | NO |  |  |  |
| batch_year | `smallint` | NO | index |  | graduation / placement-cycle year |
| resume_url | `varchar(255)` | YES |  |  |  |
| created_at | `timestamp` | NO |  | CURRENT_TIMESTAMP |  |

**CHECK constraints**

- `chk_students_batch`: `(`batch_year` between 2000 and 2100)`
- `chk_students_branch`: `(`branch` in (_utf8mb4\'CSE\',_utf8mb4\'CSE-AI\',_utf8mb4\'IT\',_utf8mb4\'ECE\'))`
- `chk_students_cgpa`: `(`cgpa` between 0 and 10)`
- `chk_students_email`: `(`email` like _utf8mb4\'%_@_%\')`

**Indexes**

- `idx_students_cohort` (non-unique): batch_year,branch,cgpa
- `PRIMARY` (unique): student_id
- `uq_students_email` (unique): email
