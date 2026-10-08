-- =============================================================================
-- demo_queries.sql  --  Queries to run live in the viva (mysql client or Workbench)
--   mysql -u root -p tnp_placement < sql/demo_queries.sql     (or paste block by block)
-- =============================================================================

-- 1. THE core query: ranked shortlist for a posting (ORDER BY the ML output)
CALL sp_shortlist_for_posting(73, 10);

--    the same thing as plain SQL, to show Match_Scores is load-bearing:
SELECT s.name, jp.role_title, ms.match_score
  FROM Match_Scores ms
  JOIN Students s      ON s.student_id  = ms.student_id
  JOIN Job_Postings jp ON jp.posting_id = ms.posting_id
 WHERE ms.posting_id = 73
 ORDER BY ms.match_score DESC
 LIMIT 20;

-- 2. Why it is fast: the ORDER BY is served by an index (no filesort)
EXPLAIN SELECT student_id, match_score FROM Match_Scores
 WHERE posting_id = 73 ORDER BY match_score DESC LIMIT 20;

-- 3. Who should the TnP officer nudge? (eligible, not applied, best match first)
CALL sp_shortlist_eligible_not_applied(73, 10);

-- 4. Early-warning list: unplaced students with low probability and few applications
CALL sp_early_warning(2026, 0.30, 3, 1);
SELECT risk_band, COUNT(*) FROM v_early_warning GROUP BY risk_band;

-- 5. One student 360: profile, applications with rounds, skills
CALL sp_student_application_summary(1234);

-- 6. Skill-gap coach: which missing skill raises the match most?
CALL sp_skill_gap(4740, 73);

-- 7. Cycle report
CALL sp_placement_report(2026);

-- 8. Analytics views
SELECT * FROM v_posting_stats ORDER BY applicants DESC LIMIT 10;
SELECT * FROM v_company_summary ORDER BY offers DESC LIMIT 10;
SELECT * FROM v_branch_placement_summary;
SELECT * FROM v_application_funnel ORDER BY applications DESC LIMIT 5;

-- 9. Window functions: rank of each applicant inside a posting + running selection count
SELECT a.posting_id, a.student_id, ms.match_score,
       RANK() OVER (PARTITION BY a.posting_id ORDER BY ms.match_score DESC) AS rank_in_posting,
       SUM(a.status = 'SELECTED') OVER (PARTITION BY a.posting_id ORDER BY ms.match_score DESC
                                        ROWS UNBOUNDED PRECEDING) AS selected_so_far
  FROM Applications a
  JOIN Match_Scores ms ON ms.student_id = a.student_id AND ms.posting_id = a.posting_id
 WHERE a.posting_id = 73
 ORDER BY rank_in_posting
 LIMIT 15;

-- 10. CTE: do selected students really have higher match scores than rejected ones?
WITH scored AS (
    SELECT a.status, ms.match_score
      FROM Applications a
      JOIN Match_Scores ms ON ms.student_id = a.student_id AND ms.posting_id = a.posting_id
     WHERE a.status IN ('SELECTED','REJECTED')
)
SELECT status, COUNT(*) AS applications, ROUND(AVG(match_score), 3) AS avg_match
  FROM scored GROUP BY status;

-- 11. Relational division: students who hold EVERY skill required by posting 73
SELECT s.student_id, s.name
  FROM Students s
 WHERE NOT EXISTS (
        SELECT 1 FROM Posting_Requirements pr
         WHERE pr.posting_id = 73
           AND NOT EXISTS (SELECT 1 FROM Student_Skills ss
                            WHERE ss.student_id = s.student_id
                              AND ss.skill_id   = pr.skill_id
                              AND ss.proficiency_level >= pr.required_level))
 LIMIT 10;

-- 12. Data-quality dashboard: every business rule as a query
SELECT * FROM v_integrity_checks;

-- 13. ML lineage: which run produced which rows, with which metrics
SELECT run_id, run_kind, model_name, rows_written, status, started_at, finished_at FROM Model_Runs;

-- 14. Audit trail written by the trigger
SELECT * FROM Application_Status_Log ORDER BY log_id DESC LIMIT 10;
