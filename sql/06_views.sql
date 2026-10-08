-- =============================================================================
-- 06_views.sql  --  Feature engineering and reporting live in SQL, not in Python
--
-- ML feature views : Student_Features, Posting_Features, ML_Placement_Dataset
-- Reporting views  : v_posting_stats, v_company_summary, v_branch_placement_summary,
--                    v_application_funnel, v_student_status, v_early_warning
--
-- Student_Features column groups (important for leakage control in the ML layer):
--   PROFILE   cgpa, skill_*, *_match_score, eligible_posting_count, academic-profile cols
--             -> known BEFORE the placement season starts
--   ACTIVITY  applications_count, rounds_attended, interview_pass_rate
--             -> produced DURING the season; interview_pass_rate is derived from the very
--                rounds that decide the label (a SELECT round counts as a pass), so it
--                leaks the target if used for a start-of-cycle prediction.
-- =============================================================================

CREATE OR REPLACE VIEW Student_Features AS
SELECT st.student_id,
       st.batch_year,
       st.branch,
       st.cgpa,
       -- PROFILE: skills
       COALESCE(sk.skill_count, 0)           AS skill_count,
       sk.avg_proficiency,
       sk.max_proficiency,
       COALESCE(sk.strong_skill_count, 0)    AS strong_skill_count,
       COALESCE(sk.verified_skill_count, 0)  AS verified_skill_count,
       -- PROFILE: match scores against postings of the student's OWN cycle
       mt.avg_match_score,
       mt.max_match_score,
       mt.top3_match_score,
       COALESCE(el.eligible_posting_count, 0) AS eligible_posting_count,
       -- ACTIVITY
       COALESCE(act.applications_count, 0)    AS applications_count,
       COALESCE(act.rounds_attended, 0)       AS rounds_attended,
       act.interview_pass_rate,
       -- PROFILE: optional academic profile (NULL when the table is not loaded)
       sap.internships,
       sap.projects,
       sap.workshops_certifications,
       sap.aptitude_test_score,
       sap.soft_skills_rating,
       (sap.extracurricular_activities = 'Yes') AS extracurricular,
       (sap.placement_training = 'Yes')         AS placement_training,
       sap.ssc_marks,
       sap.hsc_marks
  FROM Students st
  LEFT JOIN (SELECT student_id,
                    COUNT(*)                        AS skill_count,
                    AVG(proficiency_level)          AS avg_proficiency,
                    MAX(proficiency_level)          AS max_proficiency,
                    SUM(proficiency_level >= 4)     AS strong_skill_count,
                    SUM(evidence_source <> 'Self-Declared') AS verified_skill_count
               FROM Student_Skills
              GROUP BY student_id) sk
         ON sk.student_id = st.student_id
  LEFT JOIN (SELECT t.student_id,
                    AVG(t.match_score)                                   AS avg_match_score,
                    MAX(t.match_score)                                   AS max_match_score,
                    AVG(CASE WHEN t.rn <= 3 THEN t.match_score END)      AS top3_match_score
               FROM (SELECT ms.student_id, ms.match_score,
                            ROW_NUMBER() OVER (PARTITION BY ms.student_id
                                               ORDER BY ms.match_score DESC) AS rn
                       FROM Match_Scores ms
                       JOIN Students     s2 ON s2.student_id = ms.student_id
                       JOIN Job_Postings jp ON jp.posting_id = ms.posting_id
                      WHERE fn_cycle_year(jp.posted_date) = s2.batch_year) t
              GROUP BY t.student_id) mt
         ON mt.student_id = st.student_id
  LEFT JOIN (SELECT s3.student_id, COUNT(*) AS eligible_posting_count
               FROM Students s3
               JOIN Job_Postings jp3
                 ON jp3.min_cgpa <= s3.cgpa
                AND fn_cycle_year(jp3.posted_date) = s3.batch_year
              GROUP BY s3.student_id) el
         ON el.student_id = st.student_id
  LEFT JOIN (SELECT a.student_id,
                    COUNT(DISTINCT a.application_id)                AS applications_count,
                    SUM(ir.result <> 'PENDING')                     AS rounds_attended,
                    SUM(ir.result IN ('PASS', 'SELECT'))
                      / NULLIF(SUM(ir.result <> 'PENDING'), 0)      AS interview_pass_rate
               FROM Applications a
               LEFT JOIN Interview_Rounds ir ON ir.application_id = a.application_id
              GROUP BY a.student_id) act
         ON act.student_id = st.student_id
  LEFT JOIN Student_Academic_Profile sap
         ON sap.student_id = st.student_id;

-- Posting-side features
CREATE OR REPLACE VIEW Posting_Features AS
SELECT jp.posting_id,
       jp.role_title,
       jp.ctc,
       jp.min_cgpa,
       fn_cycle_year(jp.posted_date)                           AS cycle_year,
       (SELECT COUNT(*) FROM Posting_Requirements pr
         WHERE pr.posting_id = jp.posting_id)                  AS requirement_count,
       (SELECT AVG(pr.required_level) FROM Posting_Requirements pr
         WHERE pr.posting_id = jp.posting_id)                  AS avg_required_level,
       (SELECT MAX(pr.weight) FROM Posting_Requirements pr
         WHERE pr.posting_id = jp.posting_id)                  AS max_skill_weight,
       (SELECT COUNT(*) FROM Applications a
         WHERE a.posting_id = jp.posting_id)                   AS applicant_count,
       (SELECT COUNT(*) FROM Applications a
         WHERE a.posting_id = jp.posting_id
           AND a.status = 'SELECTED')                          AS selected_count,
       (SELECT AVG(ms.match_score)
          FROM Match_Scores ms
          JOIN Students s ON s.student_id = ms.student_id
         WHERE ms.posting_id = jp.posting_id
           AND s.batch_year  = fn_cycle_year(jp.posted_date))  AS avg_match_score
  FROM Job_Postings jp;

-- Training table for the placement-probability model: features + label.
CREATE OR REPLACE VIEW ML_Placement_Dataset AS
SELECT sf.*,
       (po.final_status = 'PLACED') AS is_placed,
       po.offer_ctc
  FROM Student_Features sf
  JOIN Placement_Outcomes po ON po.student_id = sf.student_id;

-- ------------------------------------------------------------------ reporting

CREATE OR REPLACE VIEW v_posting_stats AS
SELECT jp.posting_id,
       c.name                                         AS company,
       c.tier,
       jp.role_title,
       jp.ctc,
       jp.min_cgpa,
       jp.status,
       fn_cycle_year(jp.posted_date)                  AS cycle_year,
       (SELECT COUNT(*) FROM Students s
         WHERE s.batch_year = fn_cycle_year(jp.posted_date)
           AND s.cgpa >= jp.min_cgpa)                 AS eligible_students,
       COALESCE(ap.applicants, 0)                     AS applicants,
       COALESCE(ap.selected, 0)                       AS selected,
       ROUND(100 * COALESCE(ap.selected, 0) / NULLIF(ap.applicants, 0), 1) AS selection_rate_pct,
       ROUND(ap.avg_applicant_match, 4)               AS avg_applicant_match,
       ROUND(ap.avg_selected_match, 4)                AS avg_selected_match
  FROM Job_Postings jp
  JOIN Companies c ON c.company_id = jp.company_id
  LEFT JOIN (SELECT a.posting_id,
                    COUNT(*)                                      AS applicants,
                    SUM(a.status = 'SELECTED')                    AS selected,
                    AVG(ms.match_score)                           AS avg_applicant_match,
                    AVG(CASE WHEN a.status = 'SELECTED' THEN ms.match_score END) AS avg_selected_match
               FROM Applications a
               LEFT JOIN Match_Scores ms
                      ON ms.student_id = a.student_id AND ms.posting_id = a.posting_id
              GROUP BY a.posting_id) ap
         ON ap.posting_id = jp.posting_id;

CREATE OR REPLACE VIEW v_company_summary AS
SELECT c.company_id,
       c.name,
       c.sector,
       c.tier,
       COUNT(DISTINCT jp.posting_id)                 AS postings,
       ROUND(AVG(jp.ctc), 2)                         AS avg_posting_ctc,
       COALESCE(SUM(ps.applicants), 0)               AS applications,
       COALESCE(SUM(ps.selected), 0)                 AS offers,
       ROUND(100 * COALESCE(SUM(ps.selected), 0) / NULLIF(SUM(ps.applicants), 0), 1) AS offer_rate_pct
  FROM Companies c
  LEFT JOIN Job_Postings jp ON jp.company_id = c.company_id
  LEFT JOIN v_posting_stats ps ON ps.posting_id = jp.posting_id
 GROUP BY c.company_id, c.name, c.sector, c.tier;

CREATE OR REPLACE VIEW v_branch_placement_summary AS
SELECT s.batch_year,
       s.branch,
       COUNT(*)                                              AS students,
       COALESCE(SUM(po.final_status = 'PLACED'), 0)          AS placed,
       ROUND(100 * COALESCE(SUM(po.final_status = 'PLACED'), 0) / COUNT(*), 1) AS placement_pct,
       ROUND(AVG(po.offer_ctc), 2)                           AS avg_ctc_lpa,
       MAX(po.offer_ctc)                                     AS max_ctc_lpa,
       ROUND(AVG(s.cgpa), 2)                                 AS avg_cgpa
  FROM Students s
  LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
 GROUP BY s.batch_year, s.branch;

CREATE OR REPLACE VIEW v_application_funnel AS
SELECT jp.posting_id,
       c.name                                   AS company,
       jp.role_title,
       COUNT(*)                                 AS applications,
       SUM(COALESCE(rc.rounds, 0) = 0)          AS stopped_at_resume,
       SUM(COALESCE(rc.rounds, 0) >= 1)         AS reached_round_1,
       SUM(COALESCE(rc.rounds, 0) >= 2)         AS reached_round_2,
       SUM(COALESCE(rc.rounds, 0) >= 3)         AS reached_round_3,
       SUM(a.status = 'SELECTED')               AS selected
  FROM Applications a
  JOIN Job_Postings jp ON jp.posting_id = a.posting_id
  JOIN Companies    c  ON c.company_id  = jp.company_id
  LEFT JOIN (SELECT application_id, COUNT(*) AS rounds
               FROM Interview_Rounds GROUP BY application_id) rc
         ON rc.application_id = a.application_id
 GROUP BY jp.posting_id, c.name, jp.role_title;

CREATE OR REPLACE VIEW v_student_status AS
SELECT s.student_id,
       s.name,
       s.branch,
       s.batch_year,
       s.cgpa,
       COALESCE(po.final_status, 'IN_PROCESS')  AS placement_status,
       po.offer_ctc,
       c.name                                   AS placed_company,
       (SELECT COUNT(*) FROM Applications a
         WHERE a.student_id = s.student_id)     AS applications_count,
       pp.probability                           AS predicted_probability
  FROM Students s
  LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
  LEFT JOIN Job_Postings jp ON jp.posting_id = po.posting_id
  LEFT JOIN Companies c ON c.company_id = jp.company_id
  LEFT JOIN Placement_Probability pp
         ON pp.student_id = s.student_id AND pp.cycle_year = s.batch_year;

-- Unplaced students with a low predicted probability, risk-banded.
CREATE OR REPLACE VIEW v_early_warning AS
SELECT s.student_id,
       s.name,
       s.branch,
       s.batch_year,
       s.cgpa,
       pp.probability,
       CASE WHEN pp.probability < 0.15 THEN 'CRITICAL'
            WHEN pp.probability < 0.30 THEN 'HIGH'
            ELSE 'MODERATE' END                   AS risk_band,
       (SELECT COUNT(*) FROM Applications a
         WHERE a.student_id = s.student_id)       AS applications_count,
       COALESCE(po.final_status, 'IN_PROCESS')    AS placement_status
  FROM Placement_Probability pp
  JOIN Students s ON s.student_id = pp.student_id AND s.batch_year = pp.cycle_year
  LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
 WHERE pp.probability < 0.50
   AND COALESCE(po.final_status, 'IN_PROCESS') <> 'PLACED';
