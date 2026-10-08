-- =============================================================================
-- 09_app_layer.sql  --  Database objects that serve the web application
--
--   App_Users          accounts for the three roles (ADMIN = TnP officer, RECRUITER, STUDENT)
--   Login_Audit        every login attempt (security trail)
--   sp_open_posting    counterpart of sp_close_posting
--   sp_dashboard_kpis  one-row KPI summary for the overview page
--   sp_student_matches a student's own ranked postings (portal "My matches")
--   sp_posting_pipeline  every applicant of one posting with round progress (recruiter view)
--
--   v_catalog_objects / v_catalog_indexes / sp_catalog_triggers  read-only catalogue of the
--                      database (tables, views, routines, triggers, indexes) for the "Database health" page; being views
--                      owned by the admin they expose metadata without granting TRIGGER or
--                      information_schema privileges to the web account
--
-- The password hash column is never exposed by the API; ml_service and
-- readonly_analyst have no grant on App_Users (see 08_security.sql).
-- =============================================================================

CREATE TABLE App_Users (
    user_id        INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    username       VARCHAR(120)  NOT NULL,
    password_hash  VARCHAR(255)  NOT NULL COMMENT 'scrypt$salt$hash - see src/tnp/api/security.py',
    role           ENUM('ADMIN','RECRUITER','STUDENT') NOT NULL,
    display_name   VARCHAR(100)  NOT NULL,
    student_id     INT UNSIGNED  NULL,
    company_id     INT UNSIGNED  NULL,
    is_active      TINYINT(1)    NOT NULL DEFAULT 1,
    created_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at  TIMESTAMP     NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_user_username (username),
    UNIQUE KEY uq_user_student (student_id),
    KEY idx_user_company (company_id),
    CONSTRAINT fk_user_student FOREIGN KEY (student_id)
        REFERENCES Students (student_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_company FOREIGN KEY (company_id)
        REFERENCES Companies (company_id) ON DELETE CASCADE,
    CONSTRAINT chk_user_role_link CHECK (
        (role = 'ADMIN'     AND student_id IS NULL     AND company_id IS NULL)
     OR (role = 'STUDENT'   AND student_id IS NOT NULL AND company_id IS NULL)
     OR (role = 'RECRUITER' AND company_id IS NOT NULL AND student_id IS NULL))
) ENGINE=InnoDB COMMENT='Web-application accounts; the role decides what the API lets a user see and do';

CREATE TABLE Login_Audit (
    log_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username   VARCHAR(120)    NOT NULL,
    success    TINYINT(1)      NOT NULL,
    client_ip  VARCHAR(64)     NULL,
    at         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (log_id),
    KEY idx_login_user_time (username, at)
) ENGINE=InnoDB COMMENT='Login attempts, successful or not';

DELIMITER $$

CREATE PROCEDURE sp_open_posting(IN p_posting_id INT UNSIGNED)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Job_Postings WHERE posting_id = p_posting_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown posting_id';
    END IF;
    UPDATE Job_Postings SET status = 'OPEN' WHERE posting_id = p_posting_id;
    SELECT posting_id, status FROM Job_Postings WHERE posting_id = p_posting_id;
END$$

-- One row of headline numbers for a placement cycle (NULL = all cycles).
CREATE PROCEDURE sp_dashboard_kpis(IN p_cycle_year SMALLINT)
BEGIN
    SELECT (SELECT COUNT(*) FROM Students s
             WHERE p_cycle_year IS NULL OR s.batch_year = p_cycle_year)            AS students,
           (SELECT COUNT(*) FROM Students s JOIN Placement_Outcomes po ON po.student_id = s.student_id
             WHERE po.final_status = 'PLACED'
               AND (p_cycle_year IS NULL OR s.batch_year = p_cycle_year))          AS placed,
           (SELECT ROUND(100 * SUM(po.final_status = 'PLACED') / COUNT(*), 1)
              FROM Students s JOIN Placement_Outcomes po ON po.student_id = s.student_id
             WHERE p_cycle_year IS NULL OR s.batch_year = p_cycle_year)            AS placement_pct,
           (SELECT ROUND(AVG(po.offer_ctc), 2)
              FROM Students s JOIN Placement_Outcomes po ON po.student_id = s.student_id
             WHERE po.final_status = 'PLACED'
               AND (p_cycle_year IS NULL OR s.batch_year = p_cycle_year))          AS avg_ctc_lpa,
           (SELECT MAX(po.offer_ctc)
              FROM Students s JOIN Placement_Outcomes po ON po.student_id = s.student_id
             WHERE po.final_status = 'PLACED'
               AND (p_cycle_year IS NULL OR s.batch_year = p_cycle_year))          AS max_ctc_lpa,
           (SELECT COUNT(*) FROM Job_Postings jp
             WHERE p_cycle_year IS NULL OR fn_cycle_year(jp.posted_date) = p_cycle_year) AS postings,
           (SELECT COUNT(DISTINCT jp.company_id) FROM Job_Postings jp
             WHERE p_cycle_year IS NULL OR fn_cycle_year(jp.posted_date) = p_cycle_year) AS companies,
           (SELECT COUNT(*) FROM Applications a JOIN Students s ON s.student_id = a.student_id
             WHERE p_cycle_year IS NULL OR s.batch_year = p_cycle_year)            AS applications,
           (SELECT COUNT(*) FROM Placement_Probability pp
              JOIN Students s ON s.student_id = pp.student_id
              LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
             WHERE pp.probability < 0.30 AND COALESCE(po.final_status, 'IN_PROCESS') <> 'PLACED'
               AND (p_cycle_year IS NULL OR s.batch_year = p_cycle_year))          AS at_risk;
END$$

-- A student's own ranked postings (own cycle), with eligibility and application state.
CREATE PROCEDURE sp_student_matches(
    IN p_student_id    INT UNSIGNED,
    IN p_only_eligible TINYINT,
    IN p_top_n         INT
)
BEGIN
    DECLARE v_batch SMALLINT;
    SELECT batch_year INTO v_batch FROM Students WHERE student_id = p_student_id;
    IF v_batch IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown student_id';
    END IF;
    IF p_top_n IS NULL OR p_top_n < 1 THEN
        SET p_top_n = 100;
    END IF;

    SELECT RANK() OVER (ORDER BY ms.match_score DESC)  AS rank_no,
           jp.posting_id,
           c.name                                      AS company,
           c.tier,
           c.sector,
           jp.role_title,
           jp.ctc,
           jp.min_cgpa,
           jp.status                                   AS posting_status,
           ms.match_score,
           fn_match_band(ms.match_score)               AS band,
           IF(s.cgpa >= jp.min_cgpa, 1, 0)             AS eligible,
           a.application_id,
           a.status                                    AS application_status
      FROM Match_Scores ms
      JOIN Students     s  ON s.student_id  = ms.student_id
      JOIN Job_Postings jp ON jp.posting_id = ms.posting_id
      JOIN Companies    c  ON c.company_id  = jp.company_id
      LEFT JOIN Applications a ON a.student_id = ms.student_id AND a.posting_id = ms.posting_id
     WHERE ms.student_id = p_student_id
       AND fn_cycle_year(jp.posted_date) = v_batch
       AND (COALESCE(p_only_eligible, 0) = 0 OR s.cgpa >= jp.min_cgpa)
     ORDER BY ms.match_score DESC, jp.ctc DESC
     LIMIT p_top_n;
END$$

-- Everyone who applied to one posting: round progress, match score, outcome.
CREATE PROCEDURE sp_posting_pipeline(IN p_posting_id INT UNSIGNED)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Job_Postings WHERE posting_id = p_posting_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown posting_id';
    END IF;

    SELECT a.application_id,
           s.student_id,
           s.name,
           s.branch,
           s.cgpa,
           a.applied_date,
           a.status,
           COALESCE(r.rounds_held, 0)     AS rounds_held,
           COALESCE(r.rounds_cleared, 0)  AS rounds_cleared,
           r.last_round_type,
           ms.match_score
      FROM Applications a
      JOIN Students s ON s.student_id = a.student_id
      LEFT JOIN (SELECT ir.application_id,
                        COUNT(*)                                       AS rounds_held,
                        SUM(ir.result IN ('PASS', 'SELECT'))           AS rounds_cleared,
                        SUBSTRING_INDEX(GROUP_CONCAT(ir.round_type ORDER BY ir.round_no), ',', -1)
                                                                       AS last_round_type
                   FROM Interview_Rounds ir
                  GROUP BY ir.application_id) r ON r.application_id = a.application_id
      LEFT JOIN Match_Scores ms ON ms.student_id = a.student_id AND ms.posting_id = a.posting_id
     WHERE a.posting_id = p_posting_id
     ORDER BY FIELD(a.status, 'SELECTED', 'IN_PROGRESS', 'APPLIED', 'REJECTED', 'WITHDRAWN'),
              ms.match_score DESC;
END$$

-- Triggers are only visible in information_schema to accounts holding the TRIGGER privilege.
-- A definer-rights procedure lists them for the officer account without granting it.
CREATE PROCEDURE sp_catalog_triggers()
BEGIN
    SELECT g.trigger_name AS trigger_name, g.event_object_table AS table_name,
           g.action_timing AS timing, g.event_manipulation AS event
      FROM information_schema.triggers g
     WHERE g.trigger_schema = DATABASE()
     ORDER BY g.event_object_table, g.trigger_name;
END$$

DELIMITER ;

-- ------------------------------------------------------------------ catalogue views
CREATE OR REPLACE VIEW v_catalog_objects AS
SELECT 'TABLE' AS object_type, t.table_name AS object_name, t.table_comment AS detail
  FROM information_schema.tables t
 WHERE t.table_schema = DATABASE() AND t.table_type = 'BASE TABLE'
UNION ALL
SELECT 'VIEW' AS object_type, v.table_name AS object_name, 'view' AS detail
  FROM information_schema.views v
 WHERE v.table_schema = DATABASE()
UNION ALL
SELECT r.routine_type AS object_type, r.routine_name AS object_name,
       CONCAT('created ', DATE(r.created)) AS detail
  FROM information_schema.routines r
 WHERE r.routine_schema = DATABASE();

CREATE OR REPLACE VIEW v_catalog_indexes AS
SELECT s.table_name AS table_name, s.index_name AS index_name,
       IF(s.non_unique = 0, 'unique', 'non-unique') AS uniqueness,
       GROUP_CONCAT(s.column_name ORDER BY s.seq_in_index) AS index_columns
  FROM information_schema.statistics s
 WHERE s.table_schema = DATABASE()
 GROUP BY s.table_name, s.index_name, s.non_unique;
