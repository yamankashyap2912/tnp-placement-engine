-- =============================================================================
-- 08_security.sql  --  Role-based access control (MySQL 8 roles, least privilege)
--
-- Placeholders {{DB_NAME}}, {{OFFICER_PASSWORD}}, {{ML_PASSWORD}} and
-- {{READONLY_PASSWORD}} are filled in by scripts/setup_db.py from .env, so no
-- secret is stored in this file. If you run the file by hand, replace them.
--
--   tnp_admin        everything on the database
--   tnp_officer      reads all, runs the procedures, records applications / rounds, serves the web API;
--                    may change posting status only through sp_close_posting
--   ml_service       reads all, writes ONLY the ML output + lineage + queue tables
--   readonly_analyst reads views + non-sensitive columns only (for the NL2SQL
--                    assistant of Phase 5): no email, no resume_url, no writes
--
-- Stored procedures and triggers run with DEFINER rights, so an officer can call
-- sp_close_posting without holding UPDATE on Job_Postings -- a standard way to
-- expose a controlled write path.
-- =============================================================================

CREATE ROLE IF NOT EXISTS 'tnp_admin', 'tnp_officer', 'ml_service', 'readonly_analyst';

-- ---- tnp_admin
GRANT ALL PRIVILEGES ON `{{DB_NAME}}`.* TO 'tnp_admin';

-- ---- tnp_officer
GRANT SELECT  ON `{{DB_NAME}}`.* TO 'tnp_officer';
GRANT EXECUTE ON `{{DB_NAME}}`.* TO 'tnp_officer';
GRANT INSERT, UPDATE ON `{{DB_NAME}}`.Applications      TO 'tnp_officer';
GRANT INSERT, UPDATE ON `{{DB_NAME}}`.Interview_Rounds  TO 'tnp_officer';
-- the web API connects as the officer: it reads accounts to log users in and updates their
-- password / last-login; hashes are never returned to the browser.
GRANT INSERT, UPDATE ON `{{DB_NAME}}`.App_Users         TO 'tnp_officer';
GRANT INSERT         ON `{{DB_NAME}}`.Login_Audit       TO 'tnp_officer';

-- ---- ml_service (explicit SELECT list: it must NOT be able to read App_Users / Login_Audit)
GRANT SELECT ON `{{DB_NAME}}`.Students                 TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Skills                   TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Companies                TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Job_Postings             TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Student_Skills           TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Posting_Requirements     TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Applications             TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Interview_Rounds         TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Placement_Outcomes       TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Student_Academic_Profile TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Match_Scores             TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Placement_Probability    TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Model_Runs               TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Match_Refresh_Queue      TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Application_Status_Log   TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Student_Features         TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.ML_Placement_Dataset     TO 'ml_service';
GRANT SELECT ON `{{DB_NAME}}`.Posting_Features         TO 'ml_service';
GRANT INSERT, UPDATE, DELETE ON `{{DB_NAME}}`.Match_Scores          TO 'ml_service';
GRANT INSERT, UPDATE, DELETE ON `{{DB_NAME}}`.Placement_Probability TO 'ml_service';
GRANT INSERT, UPDATE         ON `{{DB_NAME}}`.Model_Runs            TO 'ml_service';
GRANT INSERT, UPDATE, DELETE ON `{{DB_NAME}}`.Match_Refresh_Queue   TO 'ml_service';

-- ---- readonly_analyst (column-level + views only)
GRANT SELECT (student_id, name, branch, cgpa, batch_year) ON `{{DB_NAME}}`.Students TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Skills                  TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Companies               TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Job_Postings            TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Posting_Requirements    TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Student_Skills          TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Applications            TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Interview_Rounds        TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Placement_Outcomes      TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Match_Scores            TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.Placement_Probability   TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.v_posting_stats             TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.v_company_summary           TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.v_branch_placement_summary  TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.v_application_funnel        TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.v_student_status            TO 'readonly_analyst';
GRANT SELECT ON `{{DB_NAME}}`.v_early_warning             TO 'readonly_analyst';

-- ---- functions are not covered by table privileges: grant EXECUTE explicitly
GRANT EXECUTE ON FUNCTION `{{DB_NAME}}`.fn_cycle_year TO 'ml_service', 'readonly_analyst';
GRANT EXECUTE ON FUNCTION `{{DB_NAME}}`.fn_is_eligible TO 'ml_service', 'readonly_analyst';
GRANT EXECUTE ON FUNCTION `{{DB_NAME}}`.fn_match_band TO 'ml_service', 'readonly_analyst';

-- ---- accounts (host 'localhost'; change it for remote / Docker deployments)
CREATE USER IF NOT EXISTS 'tnp_officer_user'@'localhost'  IDENTIFIED BY '{{OFFICER_PASSWORD}}';
CREATE USER IF NOT EXISTS 'tnp_ml_user'@'localhost'       IDENTIFIED BY '{{ML_PASSWORD}}';
CREATE USER IF NOT EXISTS 'tnp_readonly_user'@'localhost' IDENTIFIED BY '{{READONLY_PASSWORD}}';
ALTER USER 'tnp_officer_user'@'localhost'  IDENTIFIED BY '{{OFFICER_PASSWORD}}';
ALTER USER 'tnp_ml_user'@'localhost'       IDENTIFIED BY '{{ML_PASSWORD}}';
ALTER USER 'tnp_readonly_user'@'localhost' IDENTIFIED BY '{{READONLY_PASSWORD}}';

GRANT 'tnp_officer'       TO 'tnp_officer_user'@'localhost';
GRANT 'ml_service'        TO 'tnp_ml_user'@'localhost';
GRANT 'readonly_analyst'  TO 'tnp_readonly_user'@'localhost';
SET DEFAULT ROLE 'tnp_officer'      TO 'tnp_officer_user'@'localhost';
SET DEFAULT ROLE 'ml_service'       TO 'tnp_ml_user'@'localhost';
SET DEFAULT ROLE 'readonly_analyst' TO 'tnp_readonly_user'@'localhost';
