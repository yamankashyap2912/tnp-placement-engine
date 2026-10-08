-- =============================================================================
-- 07_integrity_checks.sql  --  Data-quality rules as a queryable view
--
--   SELECT * FROM v_integrity_checks;                    -- everything
--   SELECT * FROM v_integrity_checks WHERE status='FAIL'; -- only broken ERROR rules
--
-- severity ERROR : a business rule that must never be violated (expect 0)
-- severity WARN  : worth attention but legitimate in a live system
-- Constraints and triggers prevent most of these; the view is the safety net that
-- proves it (and catches anything written while triggers were bypassed).
-- =============================================================================

CREATE OR REPLACE VIEW v_integrity_checks AS
SELECT q.check_name,
       q.severity,
       q.violations,
       CASE WHEN q.violations = 0 THEN 'PASS'
            WHEN q.severity = 'ERROR' THEN 'FAIL'
            ELSE 'WARN' END AS status
  FROM (
    SELECT 'application below posting min CGPA' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Applications a
              JOIN Students s ON s.student_id = a.student_id
              JOIN Job_Postings jp ON jp.posting_id = a.posting_id
             WHERE s.cgpa < jp.min_cgpa) AS violations
    UNION ALL
    SELECT 'application to a posting of another placement cycle' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Applications a
              JOIN Students s ON s.student_id = a.student_id
              JOIN Job_Postings jp ON jp.posting_id = a.posting_id
             WHERE s.batch_year <> fn_cycle_year(jp.posted_date)) AS violations
    UNION ALL
    SELECT 'application dated before its posting' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Applications a
              JOIN Job_Postings jp ON jp.posting_id = a.posting_id
             WHERE a.applied_date < jp.posted_date) AS violations
    UNION ALL
    SELECT 'interview round dated before its application' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Interview_Rounds ir
              JOIN Applications a ON a.application_id = ir.application_id
             WHERE ir.round_date < a.applied_date) AS violations
    UNION ALL
    SELECT 'application whose round numbers are not 1..n' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM (SELECT application_id
                                    FROM Interview_Rounds
                                   GROUP BY application_id
                                  HAVING MAX(round_no) <> COUNT(*)) x) AS violations
    UNION ALL
    SELECT 'REJECT/SELECT round that is not the last round' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Interview_Rounds ir
             WHERE ir.result IN ('REJECT', 'SELECT')
               AND ir.round_no < (SELECT MAX(r2.round_no) FROM Interview_Rounds r2
                                   WHERE r2.application_id = ir.application_id)) AS violations
    UNION ALL
    SELECT 'SELECTED application without a SELECT round' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Applications a
             WHERE a.status = 'SELECTED'
               AND NOT EXISTS (SELECT 1 FROM Interview_Rounds ir
                                WHERE ir.application_id = a.application_id
                                  AND ir.result = 'SELECT')) AS violations
    UNION ALL
    SELECT 'REJECTED application with rounds but no REJECT round' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Applications a
             WHERE a.status = 'REJECTED'
               AND EXISTS (SELECT 1 FROM Interview_Rounds ir
                            WHERE ir.application_id = a.application_id)
               AND NOT EXISTS (SELECT 1 FROM Interview_Rounds ir
                                WHERE ir.application_id = a.application_id
                                  AND ir.result = 'REJECT')) AS violations
    UNION ALL
    SELECT 'SELECTED application whose student has no PLACED outcome' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Applications a
             WHERE a.status = 'SELECTED'
               AND NOT EXISTS (SELECT 1 FROM Placement_Outcomes po
                                WHERE po.student_id = a.student_id
                                  AND po.final_status = 'PLACED')) AS violations
    UNION ALL
    SELECT 'PLACED outcome without a SELECTED application at that posting' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Placement_Outcomes po
             WHERE po.final_status = 'PLACED'
               AND NOT EXISTS (SELECT 1 FROM Applications a
                                WHERE a.student_id = po.student_id
                                  AND a.posting_id = po.posting_id
                                  AND a.status = 'SELECTED')) AS violations
    UNION ALL
    SELECT 'PLACED outcome whose offer_ctc differs from the posting CTC' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Placement_Outcomes po
              JOIN Job_Postings jp ON jp.posting_id = po.posting_id
             WHERE po.final_status = 'PLACED' AND po.offer_ctc <> jp.ctc) AS violations
    UNION ALL
    SELECT 'PLACED outcome whose offer_date differs from the SELECT round date' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Placement_Outcomes po
              JOIN Applications a ON a.student_id = po.student_id
                                 AND a.posting_id = po.posting_id AND a.status = 'SELECTED'
             WHERE po.final_status = 'PLACED'
               AND po.offer_date <> (SELECT MAX(ir.round_date) FROM Interview_Rounds ir
                                      WHERE ir.application_id = a.application_id
                                        AND ir.result = 'SELECT')) AS violations
    UNION ALL
    SELECT 'posting whose requirement weights do not sum to 1.00' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM (SELECT posting_id
                                    FROM Posting_Requirements
                                   GROUP BY posting_id
                                  HAVING ABS(SUM(weight) - 1) > 0.011) x) AS violations
    UNION ALL
    SELECT 'posting without any requirement' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Job_Postings jp
             WHERE NOT EXISTS (SELECT 1 FROM Posting_Requirements pr
                                WHERE pr.posting_id = jp.posting_id)) AS violations
    UNION ALL
    SELECT 'Placement_Probability row outside the student''s cycle' AS check_name, 'ERROR' AS severity,
           (SELECT COUNT(*) FROM Placement_Probability pp
              JOIN Students s ON s.student_id = pp.student_id
             WHERE pp.cycle_year <> s.batch_year) AS violations
    UNION ALL
    SELECT 'student without any skill' AS check_name, 'WARN' AS severity,
           (SELECT COUNT(*) FROM Students s
             WHERE NOT EXISTS (SELECT 1 FROM Student_Skills ss
                                WHERE ss.student_id = s.student_id)) AS violations
    UNION ALL
    SELECT 'student without a placement outcome row' AS check_name, 'WARN' AS severity,
           (SELECT COUNT(*) FROM Students s
             WHERE NOT EXISTS (SELECT 1 FROM Placement_Outcomes po
                                WHERE po.student_id = s.student_id)) AS violations
    UNION ALL
    SELECT 'running application on a CLOSED posting' AS check_name, 'WARN' AS severity,
           (SELECT COUNT(*) FROM Applications a
              JOIN Job_Postings jp ON jp.posting_id = a.posting_id
             WHERE jp.status = 'CLOSED' AND a.status IN ('APPLIED', 'IN_PROGRESS')) AS violations
    UNION ALL
    SELECT 'own-cycle (student, posting) pair without a match score' AS check_name, 'WARN' AS severity,
           (SELECT COUNT(*) FROM Students s
              JOIN Job_Postings jp ON fn_cycle_year(jp.posted_date) = s.batch_year
              LEFT JOIN Match_Scores ms
                     ON ms.student_id = s.student_id AND ms.posting_id = jp.posting_id
             WHERE ms.score_id IS NULL) AS violations
    UNION ALL
    SELECT 'match-refresh queue entries still PENDING' AS check_name, 'WARN' AS severity,
           (SELECT COUNT(*) FROM Match_Refresh_Queue WHERE status = 'PENDING') AS violations
  ) q;
