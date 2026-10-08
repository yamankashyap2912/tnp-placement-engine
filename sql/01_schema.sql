-- =============================================================================
-- 01_schema.sql  --  Tables, keys, constraints
-- Placement Probability & Company-Student Matching Engine (IIIT Bhopal TnP)
--
-- Run order: 01_schema -> 02_indexes -> 03_functions -> 04_triggers
--            -> 05_procedures -> 06_views -> 07_integrity_checks -> 08_security
-- (scripts/setup_db.py runs them all; the database itself is created by the
--  script, so there is no USE statement here.)
--
-- 3NF design. Deliberate, documented denormalisation (see docs/NORMALIZATION.md):
--   * Match_Scores          : precomputed ML output (a materialised derived table)
--   * Placement_Probability : precomputed ML output
--   * Placement_Outcomes.offer_ctc : historical fact, kept even if posting CTC changes
-- =============================================================================

-- ---------- reference / master data ------------------------------------------

CREATE TABLE Students (
    student_id  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    name        VARCHAR(100)  NOT NULL,
    email       VARCHAR(120)  NOT NULL,
    branch      VARCHAR(20)   NOT NULL,
    cgpa        DECIMAL(4,2)  NOT NULL,
    batch_year  SMALLINT      NOT NULL COMMENT 'graduation / placement-cycle year',
    resume_url  VARCHAR(255)  NULL,
    created_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id),
    UNIQUE KEY uq_students_email (email),
    CONSTRAINT chk_students_cgpa   CHECK (cgpa BETWEEN 0 AND 10),
    CONSTRAINT chk_students_batch  CHECK (batch_year BETWEEN 2000 AND 2100),
    CONSTRAINT chk_students_branch CHECK (branch IN ('CSE','CSE-AI','IT','ECE')),
    CONSTRAINT chk_students_email  CHECK (email LIKE '%_@_%')
) ENGINE=InnoDB COMMENT='One row per student of the placement-eligible batches';

CREATE TABLE Skills (
    skill_id    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    skill_name  VARCHAR(60)   NOT NULL,
    category    ENUM('Programming','Framework','Data & AI','Tools & DevOps',
                     'Core CS','Soft Skill','Testing') NOT NULL,
    PRIMARY KEY (skill_id),
    UNIQUE KEY uq_skills_name (skill_name)
) ENGINE=InnoDB COMMENT='Skill taxonomy shared by students and postings';

CREATE TABLE Companies (
    company_id  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    name        VARCHAR(100)  NOT NULL,
    sector      VARCHAR(60)   NOT NULL,
    hq_city     VARCHAR(60)   NOT NULL,
    tier        ENUM('Tier 1','Tier 2','Tier 3') NOT NULL,
    PRIMARY KEY (company_id),
    UNIQUE KEY uq_companies_name (name)
) ENGINE=InnoDB COMMENT='Recruiting companies';

CREATE TABLE Job_Postings (
    posting_id   INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    company_id   INT UNSIGNED  NOT NULL,
    role_title   VARCHAR(100)  NOT NULL,
    ctc          DECIMAL(5,2)  NOT NULL COMMENT 'CTC in LPA',
    min_cgpa     DECIMAL(4,2)  NOT NULL DEFAULT 0,
    posted_date  DATE          NOT NULL,
    status       ENUM('OPEN','CLOSED') NOT NULL DEFAULT 'OPEN',
    PRIMARY KEY (posting_id),
    KEY idx_jp_company (company_id),
    CONSTRAINT fk_jp_company FOREIGN KEY (company_id)
        REFERENCES Companies (company_id) ON DELETE RESTRICT,
    CONSTRAINT chk_jp_ctc     CHECK (ctc > 0),
    CONSTRAINT chk_jp_mincgpa CHECK (min_cgpa BETWEEN 0 AND 10)
) ENGINE=InnoDB COMMENT='A role offered by a company in one placement cycle';

-- ---------- junction tables (resolve the two M:N relationships) --------------

CREATE TABLE Student_Skills (
    student_id         INT UNSIGNED     NOT NULL,
    skill_id           INT UNSIGNED     NOT NULL,
    proficiency_level  TINYINT UNSIGNED NOT NULL COMMENT '1 (beginner) .. 5 (expert)',
    evidence_source    ENUM('Course','Project','Certification','Internship',
                            'Self-Declared') NOT NULL DEFAULT 'Self-Declared',
    PRIMARY KEY (student_id, skill_id),
    KEY idx_ss_skill (skill_id),
    CONSTRAINT fk_ss_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT fk_ss_skill FOREIGN KEY (skill_id)
        REFERENCES Skills (skill_id) ON DELETE RESTRICT,
    CONSTRAINT chk_ss_level CHECK (proficiency_level BETWEEN 1 AND 5)
) ENGINE=InnoDB COMMENT='M:N Students-Skills with proficiency and evidence';

CREATE TABLE Posting_Requirements (
    posting_id      INT UNSIGNED     NOT NULL,
    skill_id        INT UNSIGNED     NOT NULL,
    required_level  TINYINT UNSIGNED NOT NULL,
    weight          DECIMAL(3,2)     NOT NULL COMMENT 'importance; weights of one posting sum to 1.00',
    PRIMARY KEY (posting_id, skill_id),
    KEY idx_pr_skill (skill_id),
    CONSTRAINT fk_pr_posting FOREIGN KEY (posting_id)
        REFERENCES Job_Postings (posting_id) ON DELETE CASCADE,
    CONSTRAINT fk_pr_skill FOREIGN KEY (skill_id)
        REFERENCES Skills (skill_id) ON DELETE RESTRICT,
    CONSTRAINT chk_pr_level  CHECK (required_level BETWEEN 1 AND 5),
    CONSTRAINT chk_pr_weight CHECK (weight > 0 AND weight <= 1)
) ENGINE=InnoDB COMMENT='M:N Postings-Skills with required level and weight';

-- ---------- application pipeline ---------------------------------------------

CREATE TABLE Applications (
    application_id  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    student_id      INT UNSIGNED  NOT NULL,
    posting_id      INT UNSIGNED  NOT NULL,
    applied_date    DATE          NOT NULL,
    status          ENUM('APPLIED','IN_PROGRESS','SELECTED','REJECTED',
                         'WITHDRAWN') NOT NULL DEFAULT 'APPLIED',
    PRIMARY KEY (application_id),
    UNIQUE KEY uq_app_student_posting (student_id, posting_id),
    KEY idx_app_posting_status (posting_id, status),
    CONSTRAINT fk_app_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT fk_app_posting FOREIGN KEY (posting_id)
        REFERENCES Job_Postings (posting_id) ON DELETE RESTRICT
) ENGINE=InnoDB COMMENT='M:N Students-Postings: one application per pair';

CREATE TABLE Interview_Rounds (
    round_id        INT UNSIGNED     NOT NULL AUTO_INCREMENT,
    application_id  INT UNSIGNED     NOT NULL,
    round_no        TINYINT UNSIGNED NOT NULL,
    round_type      ENUM('APTITUDE','TECHNICAL','GD','HR') NOT NULL,
    round_date      DATE             NOT NULL,
    result          ENUM('PENDING','PASS','REJECT','SELECT')
                    NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (round_id),
    UNIQUE KEY uq_round_app_no (application_id, round_no),
    CONSTRAINT fk_ir_application FOREIGN KEY (application_id)
        REFERENCES Applications (application_id) ON DELETE CASCADE,
    CONSTRAINT chk_ir_roundno CHECK (round_no >= 1)
) ENGINE=InnoDB COMMENT='Ordered interview rounds of one application';

CREATE TABLE Placement_Outcomes (
    outcome_id    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    student_id    INT UNSIGNED  NOT NULL,
    posting_id    INT UNSIGNED  NULL,
    final_status  ENUM('PLACED','NOT_PLACED') NOT NULL,
    offer_ctc     DECIMAL(5,2)  NULL,
    offer_date    DATE          NULL,
    PRIMARY KEY (outcome_id),
    UNIQUE KEY uq_outcome_student (student_id),
    KEY idx_po_posting (posting_id),
    CONSTRAINT fk_po_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT fk_po_posting FOREIGN KEY (posting_id)
        REFERENCES Job_Postings (posting_id) ON DELETE RESTRICT,
    CONSTRAINT chk_po_consistency CHECK (
        (final_status = 'PLACED' AND posting_id IS NOT NULL
                                 AND offer_ctc IS NOT NULL)
     OR (final_status = 'NOT_PLACED' AND posting_id IS NULL
                                 AND offer_ctc IS NULL))
) ENGINE=InnoDB COMMENT='Historical label table: one final outcome per student';

-- ---------- ML governance + ML write-back tables -----------------------------

CREATE TABLE Model_Runs (
    run_id         INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    run_kind       ENUM('MATCH','PLACEMENT') NOT NULL,
    model_name     VARCHAR(60)   NOT NULL,
    params         JSON          NULL,
    metrics        JSON          NULL,
    rows_written   INT UNSIGNED  NOT NULL DEFAULT 0,
    status         ENUM('RUNNING','SUCCESS','FAILED') NOT NULL DEFAULT 'RUNNING',
    started_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at    TIMESTAMP     NULL,
    notes          VARCHAR(255)  NULL,
    PRIMARY KEY (run_id),
    KEY idx_mr_kind_started (run_kind, started_at)
) ENGINE=InnoDB COMMENT='Lineage of every ML run that wrote into the database';

CREATE TABLE Match_Scores (
    score_id      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    student_id    INT UNSIGNED  NOT NULL,
    posting_id    INT UNSIGNED  NOT NULL,
    match_score   DECIMAL(5,4)  NOT NULL,
    computed_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    model_run_id  INT UNSIGNED  NULL COMMENT 'which ML run produced this row (NULL = SQL baseline)',
    PRIMARY KEY (score_id),
    UNIQUE KEY uq_ms_pair (student_id, posting_id),
    KEY idx_ms_posting_score (posting_id, match_score DESC),
    CONSTRAINT fk_ms_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT fk_ms_posting FOREIGN KEY (posting_id)
        REFERENCES Job_Postings (posting_id) ON DELETE CASCADE,
    CONSTRAINT fk_ms_run FOREIGN KEY (model_run_id)
        REFERENCES Model_Runs (run_id) ON DELETE SET NULL,
    CONSTRAINT chk_ms_score CHECK (match_score BETWEEN 0 AND 1)
) ENGINE=InnoDB COMMENT='ML output: one row per (student, posting); the ORDER BY of the shortlist';

CREATE TABLE Placement_Probability (
    student_id    INT UNSIGNED  NOT NULL,
    cycle_year    SMALLINT      NOT NULL,
    probability   DECIMAL(5,4)  NOT NULL,
    computed_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    model_run_id  INT UNSIGNED  NULL,
    PRIMARY KEY (student_id, cycle_year),
    CONSTRAINT fk_pp_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT fk_pp_run FOREIGN KEY (model_run_id)
        REFERENCES Model_Runs (run_id) ON DELETE SET NULL,
    CONSTRAINT chk_pp_prob CHECK (probability BETWEEN 0 AND 1)
) ENGINE=InnoDB COMMENT='ML output: predicted placement probability per student and cycle';

-- ---------- operational support tables ---------------------------------------

CREATE TABLE Application_Status_Log (
    log_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    application_id  INT UNSIGNED    NOT NULL,
    old_status      VARCHAR(15)     NOT NULL,
    new_status      VARCHAR(15)     NOT NULL,
    changed_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by      VARCHAR(100)    NOT NULL,
    PRIMARY KEY (log_id),
    KEY idx_log_app (application_id),
    CONSTRAINT fk_log_app FOREIGN KEY (application_id)
        REFERENCES Applications (application_id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='Audit trail written by trigger on every status change';

CREATE TABLE Match_Refresh_Queue (
    entity_type   ENUM('STUDENT','POSTING') NOT NULL,
    entity_id     INT UNSIGNED  NOT NULL,
    status        ENUM('PENDING','DONE') NOT NULL DEFAULT 'PENDING',
    queued_at     TIMESTAMP(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                  COMMENT 'microsecond precision: lets the worker detect a re-queue while it was processing',
    processed_at  TIMESTAMP(6)  NULL,
    PRIMARY KEY (entity_type, entity_id),
    KEY idx_mrq_status (status, queued_at)
) ENGINE=InnoDB COMMENT='Triggers enqueue students/postings whose skills changed; a worker re-scores them';

-- ---------- optional extension (1:1 with Students) ---------------------------

CREATE TABLE Student_Academic_Profile (
    student_id                 INT UNSIGNED      NOT NULL,
    internships                TINYINT UNSIGNED  NOT NULL,
    projects                   TINYINT UNSIGNED  NOT NULL,
    workshops_certifications   TINYINT UNSIGNED  NOT NULL,
    aptitude_test_score        SMALLINT UNSIGNED NOT NULL,
    soft_skills_rating         DECIMAL(2,1)      NOT NULL,
    extracurricular_activities ENUM('Yes','No')  NOT NULL,
    placement_training         ENUM('Yes','No')  NOT NULL,
    ssc_marks                  SMALLINT UNSIGNED NOT NULL,
    hsc_marks                  SMALLINT UNSIGNED NOT NULL,
    PRIMARY KEY (student_id),
    CONSTRAINT fk_sap_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT chk_sap_marks CHECK (ssc_marks BETWEEN 0 AND 100 AND hsc_marks BETWEEN 0 AND 100),
    CONSTRAINT chk_sap_apt   CHECK (aptitude_test_score BETWEEN 0 AND 100),
    CONSTRAINT chk_sap_soft  CHECK (soft_skills_rating BETWEEN 0 AND 5)
) ENGINE=InnoDB COMMENT='Optional 1:1 academic/extra-curricular profile used as extra ML features';
