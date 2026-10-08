-- =============================================================================
-- 05_procedures.sql  --  The database API used by the TnP cell, the ML worker
--                        and (later) the FastAPI backend
--
--  Read / analytics
--    sp_shortlist_for_posting(posting_id, top_n)            ranked cohort shortlist
--    sp_shortlist_eligible_not_applied(posting_id, top_n)   actionable outreach list
--    sp_student_application_summary(student_id)             3 result sets
--    sp_skill_gap(student_id, posting_id)                   skill-gap coach, in SQL
--    sp_early_warning(cycle, threshold, max_apps, excl_placed)
--    sp_placement_report(cycle)
--  Transactional (ACID, row locking, friendly errors)
--    sp_apply_to_posting, sp_record_round, sp_withdraw_application, sp_close_posting
--  Match-score maintenance (SQL baseline = weighted skill coverage)
--    sp_refresh_match_scores_baseline / _for_student / _for_posting
--    sp_process_refresh_queue_baseline
--
--  Baseline formula (identical to the Python "coverage" method):
--    score = SUM(weight * LEAST(student_level / required_level, 1)) / SUM(weight)
-- =============================================================================

DELIMITER $$

-- -----------------------------------------------------------------------------
-- Ranked shortlist for a posting. Ranks only the posting's own cohort (batch =
-- posting cycle) because comparing students of different batches is meaningless.
-- The ORDER BY match_score is served by idx_ms_posting_score.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_shortlist_for_posting(
    IN p_posting_id INT UNSIGNED,
    IN p_top_n      INT
)
BEGIN
    DECLARE v_cycle SMALLINT;

    SELECT fn_cycle_year(posted_date) INTO v_cycle
      FROM Job_Postings WHERE posting_id = p_posting_id;
    IF v_cycle IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown posting_id';
    END IF;
    IF p_top_n IS NULL OR p_top_n < 1 THEN
        SET p_top_n = 20;
    END IF;

    SELECT RANK() OVER (ORDER BY ms.match_score DESC) AS rank_no,
           s.student_id,
           s.name,
           s.branch,
           s.cgpa,
           ms.match_score,
           fn_match_band(ms.match_score)                           AS band,
           IF(s.cgpa >= jp.min_cgpa, 'YES', 'NO')                  AS eligible,
           IF(a.application_id IS NULL, 'NO', 'YES')               AS already_applied,
           a.status                                                AS application_status
      FROM Match_Scores ms
      JOIN Students     s  ON s.student_id  = ms.student_id
      JOIN Job_Postings jp ON jp.posting_id = ms.posting_id
      LEFT JOIN Applications a
             ON a.student_id = ms.student_id AND a.posting_id = ms.posting_id
     WHERE ms.posting_id = p_posting_id
       AND s.batch_year  = v_cycle
     ORDER BY ms.match_score DESC, s.cgpa DESC, s.student_id
     LIMIT p_top_n;
END$$

-- Eligible students who have NOT applied yet, best match first: "who should the
-- TnP officer nudge for this posting?"
CREATE PROCEDURE sp_shortlist_eligible_not_applied(
    IN p_posting_id INT UNSIGNED,
    IN p_top_n      INT
)
BEGIN
    DECLARE v_cycle SMALLINT;

    SELECT fn_cycle_year(posted_date) INTO v_cycle
      FROM Job_Postings WHERE posting_id = p_posting_id;
    IF v_cycle IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown posting_id';
    END IF;
    IF p_top_n IS NULL OR p_top_n < 1 THEN
        SET p_top_n = 20;
    END IF;

    SELECT ROW_NUMBER() OVER (ORDER BY ms.match_score DESC, s.cgpa DESC) AS rank_no,
           s.student_id, s.name, s.branch, s.cgpa, s.email,
           ms.match_score, fn_match_band(ms.match_score) AS band
      FROM Match_Scores ms
      JOIN Students     s  ON s.student_id  = ms.student_id
      JOIN Job_Postings jp ON jp.posting_id = ms.posting_id
     WHERE ms.posting_id = p_posting_id
       AND s.batch_year  = v_cycle
       AND s.cgpa       >= jp.min_cgpa
       AND NOT EXISTS (SELECT 1 FROM Applications a
                        WHERE a.student_id = s.student_id
                          AND a.posting_id = p_posting_id)
     ORDER BY ms.match_score DESC, s.cgpa DESC
     LIMIT p_top_n;
END$$

-- -----------------------------------------------------------------------------
-- One student: profile + placement status, every application, every skill.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_student_application_summary(IN p_student_id INT UNSIGNED)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Students WHERE student_id = p_student_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown student_id';
    END IF;

    -- Result set 1: profile and placement status
    SELECT s.student_id, s.name, s.branch, s.cgpa, s.batch_year,
           COALESCE(po.final_status, 'IN_PROCESS') AS placement_status,
           po.offer_ctc,
           pp.probability                          AS predicted_probability
      FROM Students s
      LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
      LEFT JOIN Placement_Probability pp
             ON pp.student_id = s.student_id AND pp.cycle_year = s.batch_year
     WHERE s.student_id = p_student_id;

    -- Result set 2: every application with round progress and match score
    SELECT a.application_id, c.name AS company, jp.role_title, jp.ctc,
           a.applied_date, a.status,
           (SELECT COUNT(*) FROM Interview_Rounds ir
             WHERE ir.application_id = a.application_id) AS rounds_held,
           (SELECT COUNT(*) FROM Interview_Rounds ir
             WHERE ir.application_id = a.application_id
               AND ir.result IN ('PASS','SELECT'))        AS rounds_cleared,
           ms.match_score
      FROM Applications a
      JOIN Job_Postings jp ON jp.posting_id = a.posting_id
      JOIN Companies    c  ON c.company_id  = jp.company_id
      LEFT JOIN Match_Scores ms
             ON ms.student_id = a.student_id AND ms.posting_id = a.posting_id
     WHERE a.student_id = p_student_id
     ORDER BY a.applied_date, a.application_id;

    -- Result set 3: the student's skills
    SELECT sk.skill_name, sk.category, ss.proficiency_level, ss.evidence_source
      FROM Student_Skills ss
      JOIN Skills sk ON sk.skill_id = ss.skill_id
     WHERE ss.student_id = p_student_id
     ORDER BY ss.proficiency_level DESC, sk.skill_name;
END$$

-- -----------------------------------------------------------------------------
-- Skill-gap coach (PDF Phase 7), computed entirely in SQL.
-- potential_gain = exact score increase if the student reaches the required level
-- of that skill (exact for the coverage score; an approximation for other models).
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_skill_gap(
    IN p_student_id INT UNSIGNED,
    IN p_posting_id INT UNSIGNED
)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Students WHERE student_id = p_student_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown student_id';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM Job_Postings WHERE posting_id = p_posting_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown posting_id';
    END IF;

    -- Result set 1: requirement by requirement, biggest win first
    SELECT sk.skill_name,
           sk.category,
           pr.required_level,
           COALESCE(ss.proficiency_level, 0)                               AS student_level,
           GREATEST(CAST(pr.required_level AS SIGNED) - CAST(COALESCE(ss.proficiency_level, 0) AS SIGNED), 0) AS level_gap,
           pr.weight,
           ROUND(pr.weight * LEAST(COALESCE(ss.proficiency_level, 0) / pr.required_level, 1)
                 / tot.sum_w, 4)                                           AS current_contribution,
           ROUND(pr.weight * (1 - LEAST(COALESCE(ss.proficiency_level, 0) / pr.required_level, 1))
                 / tot.sum_w, 4)                                           AS potential_gain
      FROM Posting_Requirements pr
      JOIN Skills sk ON sk.skill_id = pr.skill_id
      JOIN (SELECT SUM(weight) AS sum_w
              FROM Posting_Requirements WHERE posting_id = p_posting_id) tot
      LEFT JOIN Student_Skills ss
             ON ss.student_id = p_student_id AND ss.skill_id = pr.skill_id
     WHERE pr.posting_id = p_posting_id
     ORDER BY potential_gain DESC, pr.weight DESC, sk.skill_name;

    -- Result set 2: where the student stands
    SELECT p_student_id AS student_id, p_posting_id AS posting_id,
           ms.match_score AS stored_match_score,
           fn_match_band(ms.match_score) AS band,
           fn_is_eligible(p_student_id, p_posting_id) AS eligible
      FROM (SELECT 1) dummy
      LEFT JOIN Match_Scores ms
             ON ms.student_id = p_student_id AND ms.posting_id = p_posting_id;
END$$

-- -----------------------------------------------------------------------------
-- Early-warning list for the TnP cell (needs Placement_Probability filled by ML).
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_early_warning(
    IN p_cycle_year     SMALLINT,
    IN p_threshold      DECIMAL(5,4),
    IN p_max_apps       INT,
    IN p_exclude_placed TINYINT
)
BEGIN
    SET p_threshold      = COALESCE(p_threshold, 0.3000);
    SET p_max_apps       = COALESCE(p_max_apps, 1000000);
    SET p_exclude_placed = COALESCE(p_exclude_placed, 1);

    SELECT t.*
      FROM (SELECT s.student_id, s.name, s.branch, s.cgpa,
                   pp.probability,
                   (SELECT COUNT(*) FROM Applications a
                     WHERE a.student_id = s.student_id)          AS applications_count,
                   COALESCE(po.final_status, 'IN_PROCESS')       AS placement_status
              FROM Placement_Probability pp
              JOIN Students s ON s.student_id = pp.student_id
              LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
             WHERE pp.cycle_year = p_cycle_year
               AND pp.probability < p_threshold
               AND (p_exclude_placed = 0 OR COALESCE(po.final_status, 'IN_PROCESS') <> 'PLACED')) t
     WHERE t.applications_count <= p_max_apps
     ORDER BY t.probability ASC, t.applications_count ASC, t.student_id;
END$$

-- -----------------------------------------------------------------------------
-- Cycle report: by branch, by company tier, top recruiters.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_placement_report(IN p_cycle_year SMALLINT)
BEGIN
    SELECT s.branch,
           COUNT(*)                                              AS students,
           SUM(po.final_status = 'PLACED')                       AS placed,
           ROUND(100 * SUM(po.final_status = 'PLACED') / COUNT(*), 1) AS placement_pct,
           ROUND(AVG(po.offer_ctc), 2)                           AS avg_ctc_lpa,
           MAX(po.offer_ctc)                                     AS max_ctc_lpa,
           ROUND(AVG(s.cgpa), 2)                                 AS avg_cgpa
      FROM Students s
      LEFT JOIN Placement_Outcomes po ON po.student_id = s.student_id
     WHERE s.batch_year = p_cycle_year
     GROUP BY s.branch
     ORDER BY placement_pct DESC;

    SELECT c.tier,
           COUNT(*)                   AS offers,
           ROUND(AVG(po.offer_ctc),2) AS avg_ctc_lpa,
           MAX(po.offer_ctc)          AS max_ctc_lpa
      FROM Placement_Outcomes po
      JOIN Students     s  ON s.student_id  = po.student_id
      JOIN Job_Postings jp ON jp.posting_id = po.posting_id
      JOIN Companies    c  ON c.company_id  = jp.company_id
     WHERE s.batch_year = p_cycle_year AND po.final_status = 'PLACED'
     GROUP BY c.tier
     ORDER BY c.tier;

    SELECT c.name AS company, COUNT(*) AS offers, ROUND(AVG(po.offer_ctc),2) AS avg_ctc_lpa
      FROM Placement_Outcomes po
      JOIN Students     s  ON s.student_id  = po.student_id
      JOIN Job_Postings jp ON jp.posting_id = po.posting_id
      JOIN Companies    c  ON c.company_id  = jp.company_id
     WHERE s.batch_year = p_cycle_year AND po.final_status = 'PLACED'
     GROUP BY c.company_id, c.name
     ORDER BY offers DESC, avg_ctc_lpa DESC
     LIMIT 5;
END$$

-- =============================================================================
-- Transactional procedures
-- =============================================================================

-- Apply to a posting. T4 (eligibility trigger) validates; we add a transaction,
-- a student-row lock and friendly duplicate handling.
CREATE PROCEDURE sp_apply_to_posting(
    IN p_student_id INT UNSIGNED,
    IN p_posting_id INT UNSIGNED
)
BEGIN
    DECLARE v_cgpa DECIMAL(4,2);

    DECLARE EXIT HANDLER FOR 1062
    BEGIN
        ROLLBACK;
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Student has already applied to this posting';
    END;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;
    -- serialise concurrent applications of the same student
    SELECT cgpa INTO v_cgpa FROM Students WHERE student_id = p_student_id FOR UPDATE;
    IF v_cgpa IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown student_id';
    END IF;

    INSERT INTO Applications (student_id, posting_id, applied_date)
    VALUES (p_student_id, p_posting_id, CURDATE());
    COMMIT;

    SELECT LAST_INSERT_ID() AS application_id;
END$$

-- Record the next interview round of an application. The application row is
-- locked (SELECT ... FOR UPDATE) so two officers cannot create the same round_no.
-- Triggers T1/T3/T6/T7 then move the status, create the outcome and write the audit log.
CREATE PROCEDURE sp_record_round(
    IN p_application_id INT UNSIGNED,
    IN p_round_type     VARCHAR(10),
    IN p_result         VARCHAR(10),
    IN p_round_date     DATE
)
BEGIN
    DECLARE v_status VARCHAR(15);
    DECLARE v_next   INT;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;
    SELECT status INTO v_status FROM Applications
     WHERE application_id = p_application_id FOR UPDATE;
    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown application_id';
    END IF;

    SELECT COALESCE(MAX(round_no), 0) + 1 INTO v_next
      FROM Interview_Rounds WHERE application_id = p_application_id;

    INSERT INTO Interview_Rounds (application_id, round_no, round_type, round_date, result)
    VALUES (p_application_id, v_next, p_round_type, COALESCE(p_round_date, CURDATE()), p_result);
    COMMIT;

    SELECT application_id, status AS new_status, v_next AS round_no
      FROM Applications WHERE application_id = p_application_id;
END$$

CREATE PROCEDURE sp_withdraw_application(IN p_application_id INT UNSIGNED)
BEGIN
    DECLARE v_status VARCHAR(15);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;
    SELECT status INTO v_status FROM Applications
     WHERE application_id = p_application_id FOR UPDATE;
    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown application_id';
    END IF;
    IF v_status NOT IN ('APPLIED', 'IN_PROGRESS') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only running applications can be withdrawn';
    END IF;
    UPDATE Applications SET status = 'WITHDRAWN' WHERE application_id = p_application_id;
    COMMIT;

    SELECT application_id, status FROM Applications WHERE application_id = p_application_id;
END$$

CREATE PROCEDURE sp_close_posting(IN p_posting_id INT UNSIGNED)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Job_Postings WHERE posting_id = p_posting_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown posting_id';
    END IF;
    UPDATE Job_Postings SET status = 'CLOSED' WHERE posting_id = p_posting_id;
    SELECT posting_id, status FROM Job_Postings WHERE posting_id = p_posting_id;
END$$

-- =============================================================================
-- Match-score maintenance, SQL baseline (weighted skill coverage)
-- =============================================================================

-- Full refresh: every own-cycle (student, posting) pair (student batch = posting cycle).
CREATE PROCEDURE sp_refresh_match_scores_baseline()
BEGIN
    INSERT INTO Match_Scores (student_id, posting_id, match_score)
    SELECT s.student_id,
           jp.posting_id,
           ROUND(SUM(pr.weight * LEAST(COALESCE(ss.proficiency_level, 0)
                                       / pr.required_level, 1))
                 / SUM(pr.weight), 4)
      FROM Students s
      CROSS JOIN Job_Postings jp
      JOIN Posting_Requirements pr ON pr.posting_id = jp.posting_id
      LEFT JOIN Student_Skills ss
             ON ss.student_id = s.student_id AND ss.skill_id = pr.skill_id
     WHERE s.batch_year = fn_cycle_year(jp.posted_date)
     GROUP BY s.student_id, jp.posting_id
    ON DUPLICATE KEY UPDATE match_score  = VALUES(match_score),
                            computed_at  = CURRENT_TIMESTAMP,
                            model_run_id = NULL;
END$$

-- Incremental: one student against the postings of his/her own cycle.
CREATE PROCEDURE sp_refresh_match_scores_for_student(IN p_student_id INT UNSIGNED)
BEGIN
    INSERT INTO Match_Scores (student_id, posting_id, match_score)
    SELECT s.student_id,
           jp.posting_id,
           ROUND(SUM(pr.weight * LEAST(COALESCE(ss.proficiency_level, 0)
                                       / pr.required_level, 1))
                 / SUM(pr.weight), 4)
      FROM Students s
      CROSS JOIN Job_Postings jp
      JOIN Posting_Requirements pr ON pr.posting_id = jp.posting_id
      LEFT JOIN Student_Skills ss
             ON ss.student_id = s.student_id AND ss.skill_id = pr.skill_id
     WHERE s.student_id = p_student_id
       AND s.batch_year = fn_cycle_year(jp.posted_date)
     GROUP BY s.student_id, jp.posting_id
    ON DUPLICATE KEY UPDATE match_score  = VALUES(match_score),
                            computed_at  = CURRENT_TIMESTAMP,
                            model_run_id = NULL;
END$$

-- Incremental: one posting against the students of its own cycle.
CREATE PROCEDURE sp_refresh_match_scores_for_posting(IN p_posting_id INT UNSIGNED)
BEGIN
    INSERT INTO Match_Scores (student_id, posting_id, match_score)
    SELECT s.student_id,
           jp.posting_id,
           ROUND(SUM(pr.weight * LEAST(COALESCE(ss.proficiency_level, 0)
                                       / pr.required_level, 1))
                 / SUM(pr.weight), 4)
      FROM Students s
      CROSS JOIN Job_Postings jp
      JOIN Posting_Requirements pr ON pr.posting_id = jp.posting_id
      LEFT JOIN Student_Skills ss
             ON ss.student_id = s.student_id AND ss.skill_id = pr.skill_id
     WHERE jp.posting_id = p_posting_id
       AND s.batch_year = fn_cycle_year(jp.posted_date)
     GROUP BY s.student_id, jp.posting_id
    ON DUPLICATE KEY UPDATE match_score  = VALUES(match_score),
                            computed_at  = CURRENT_TIMESTAMP,
                            model_run_id = NULL;
END$$

-- Drain Match_Refresh_Queue with the SQL baseline (works without Python).
-- Optimistic concurrency: an entry is marked DONE only if it was not re-queued
-- while we were processing it (queued_at unchanged, microsecond precision).
CREATE PROCEDURE sp_process_refresh_queue_baseline()
BEGIN
    DECLARE v_done   INT DEFAULT 0;
    DECLARE v_type   VARCHAR(10);
    DECLARE v_id     INT UNSIGNED;
    DECLARE v_queued TIMESTAMP(6);
    DECLARE v_n      INT DEFAULT 0;
    DECLARE cur CURSOR FOR
        SELECT entity_type, entity_id, queued_at
          FROM Match_Refresh_Queue WHERE status = 'PENDING' ORDER BY queued_at;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;

    OPEN cur;
    queue_loop: LOOP
        FETCH cur INTO v_type, v_id, v_queued;
        IF v_done = 1 THEN
            LEAVE queue_loop;
        END IF;
        IF v_type = 'STUDENT' THEN
            CALL sp_refresh_match_scores_for_student(v_id);
        ELSE
            CALL sp_refresh_match_scores_for_posting(v_id);
        END IF;
        UPDATE Match_Refresh_Queue
           SET status = 'DONE', processed_at = CURRENT_TIMESTAMP(6)
         WHERE entity_type = v_type AND entity_id = v_id AND queued_at = v_queued;
        SET v_n = v_n + 1;
    END LOOP;
    CLOSE cur;

    SELECT v_n AS queue_entries_processed;
END$$

DELIMITER ;
