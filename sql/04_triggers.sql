-- =============================================================================
-- 04_triggers.sql  --  Business rules and automation inside the database
--
-- Trigger map
--   Interview_Rounds : T1 after insert   -> move application status
--                      T2 after update   -> move application status
--                      T3 before insert  -> validate round (order, dates, not finished)
--   Applications     : T4 before insert  -> eligibility (closed / CGPA / cycle / date)
--                      T5 before update  -> status guard (finished apps are immutable)
--                      T6 after  update  -> final SELECT creates / upgrades Placement_Outcomes
--                      T7 after  update  -> audit trail in Application_Status_Log
--   Student_Skills / Posting_Requirements (3 each, insert/update/delete)
--                    -> enqueue the student / posting in Match_Refresh_Queue so the
--                       ML worker re-scores only what changed
--
-- Session switch  SET @tnp_bulk_load = 1;
--   Trusted bulk loads (scripts/load_data.py) skip the *workflow* triggers
--   (T3, T5, queue triggers). Integrity constraints, FKs and the eligibility
--   trigger T4 are NEVER skipped.
-- =============================================================================

DELIMITER $$

-- Internal helper: move an application forward based on a round result.
-- Final states (SELECTED / REJECTED / WITHDRAWN) are never overwritten.
CREATE PROCEDURE sp_apply_round_result(
    IN p_application_id INT UNSIGNED,
    IN p_result         VARCHAR(10)
)
BEGIN
    UPDATE Applications
       SET status = CASE p_result
                        WHEN 'REJECT' THEN 'REJECTED'
                        WHEN 'SELECT' THEN 'SELECTED'
                        ELSE 'IN_PROGRESS'
                    END
     WHERE application_id = p_application_id
       AND status IN ('APPLIED', 'IN_PROGRESS');
END$$

-- ---------------------------------------------------------------- Interview_Rounds

-- T1: a new interview round updates the application status
CREATE TRIGGER trg_round_after_insert
AFTER INSERT ON Interview_Rounds
FOR EACH ROW
BEGIN
    CALL sp_apply_round_result(NEW.application_id, NEW.result);
END$$

-- T2: a changed round result (e.g. PENDING -> SELECT) does the same
CREATE TRIGGER trg_round_after_update
AFTER UPDATE ON Interview_Rounds
FOR EACH ROW
BEGIN
    IF NEW.result <> OLD.result THEN
        CALL sp_apply_round_result(NEW.application_id, NEW.result);
    END IF;
END$$

-- T3: validate a new round (sequence, dates, application still running)
CREATE TRIGGER trg_round_before_insert_rules
BEFORE INSERT ON Interview_Rounds
FOR EACH ROW
BEGIN
    DECLARE v_status    VARCHAR(15);
    DECLARE v_applied   DATE;
    DECLARE v_last_no   INT;
    DECLARE v_last_date DATE;

    IF COALESCE(@tnp_bulk_load, 0) = 0 THEN
        SELECT status, applied_date INTO v_status, v_applied
          FROM Applications WHERE application_id = NEW.application_id;

        IF v_status IN ('SELECTED', 'REJECTED', 'WITHDRAWN') THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Application is already finished; no more rounds can be added';
        END IF;
        IF NEW.round_date < v_applied THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Round date is before the application date';
        END IF;

        SELECT COALESCE(MAX(round_no), 0), MAX(round_date)
          INTO v_last_no, v_last_date
          FROM Interview_Rounds WHERE application_id = NEW.application_id;

        IF NEW.round_no <> v_last_no + 1 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'round_no must be the next number in sequence';
        END IF;
        IF v_last_date IS NOT NULL AND NEW.round_date < v_last_date THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Round date is earlier than the previous round';
        END IF;
    END IF;
END$$

-- ---------------------------------------------------------------- Applications

-- T4: eligibility check before an application is accepted (never bypassed)
CREATE TRIGGER trg_app_before_insert_eligibility
BEFORE INSERT ON Applications
FOR EACH ROW
BEGIN
    DECLARE v_cgpa   DECIMAL(4,2);
    DECLARE v_batch  SMALLINT;
    DECLARE v_min    DECIMAL(4,2);
    DECLARE v_status VARCHAR(10);
    DECLARE v_posted DATE;

    SELECT cgpa, batch_year INTO v_cgpa, v_batch
      FROM Students WHERE student_id = NEW.student_id;
    SELECT min_cgpa, status, posted_date INTO v_min, v_status, v_posted
      FROM Job_Postings WHERE posting_id = NEW.posting_id;

    IF v_cgpa IS NULL OR v_min IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown student or posting';
    ELSEIF v_status = 'CLOSED' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Posting is closed for applications';
    ELSEIF v_cgpa < v_min THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Student CGPA is below the posting minimum CGPA';
    ELSEIF v_batch <> fn_cycle_year(v_posted) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Posting belongs to a different placement cycle than the student batch';
    ELSEIF NEW.applied_date < v_posted THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Application date is before the posting date';
    END IF;
END$$

-- T5: finished applications are immutable; the (student, posting) pair never changes
CREATE TRIGGER trg_app_before_update_status_guard
BEFORE UPDATE ON Applications
FOR EACH ROW
BEGIN
    IF NEW.student_id <> OLD.student_id OR NEW.posting_id <> OLD.posting_id THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'student_id and posting_id of an application cannot be changed';
    END IF;
    IF COALESCE(@tnp_bulk_load, 0) = 0
       AND NEW.status <> OLD.status
       AND OLD.status IN ('SELECTED', 'REJECTED', 'WITHDRAWN') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Application is already finished; its status cannot change';
    END IF;
END$$

-- T6: a final SELECT creates (or upgrades) the Placement_Outcomes row
CREATE TRIGGER trg_app_after_update_placement
AFTER UPDATE ON Applications
FOR EACH ROW
BEGIN
    DECLARE v_ctc  DECIMAL(5,2);
    DECLARE v_date DATE;

    IF NEW.status = 'SELECTED' AND OLD.status <> 'SELECTED' THEN
        SELECT ctc INTO v_ctc
          FROM Job_Postings
         WHERE posting_id = NEW.posting_id;

        SELECT COALESCE(MAX(round_date), CURDATE()) INTO v_date
          FROM Interview_Rounds
         WHERE application_id = NEW.application_id AND result = 'SELECT';

        IF NOT EXISTS (SELECT 1 FROM Placement_Outcomes
                        WHERE student_id = NEW.student_id) THEN
            INSERT INTO Placement_Outcomes
                   (student_id, posting_id, final_status, offer_ctc, offer_date)
            VALUES (NEW.student_id, NEW.posting_id, 'PLACED', v_ctc, v_date);
        ELSE
            -- keep the best offer: upgrade only if NOT_PLACED or a higher CTC
            UPDATE Placement_Outcomes
               SET posting_id   = NEW.posting_id,
                   final_status = 'PLACED',
                   offer_ctc    = v_ctc,
                   offer_date   = v_date
             WHERE student_id = NEW.student_id
               AND (final_status = 'NOT_PLACED' OR offer_ctc < v_ctc);
        END IF;
    END IF;
END$$

-- T7: audit trail of every status change (runs after T6, so order is deterministic)
CREATE TRIGGER trg_app_after_update_audit
AFTER UPDATE ON Applications
FOR EACH ROW
FOLLOWS trg_app_after_update_placement
BEGIN
    IF NEW.status <> OLD.status THEN
        INSERT INTO Application_Status_Log
               (application_id, old_status, new_status, changed_by)
        VALUES (NEW.application_id, OLD.status, NEW.status, USER());
    END IF;
END$$

-- ---------------------------------------------------------------- ML refresh queue
-- A skill (or a requirement) changed => the affected match scores are stale.
-- One queue row per entity (PK entity_type + entity_id): repeated edits collapse.

CREATE TRIGGER trg_ss_after_insert
AFTER INSERT ON Student_Skills
FOR EACH ROW
BEGIN
    IF COALESCE(@tnp_bulk_load, 0) = 0 THEN
        INSERT INTO Match_Refresh_Queue (entity_type, entity_id)
        VALUES ('STUDENT', NEW.student_id)
        ON DUPLICATE KEY UPDATE status = 'PENDING', queued_at = CURRENT_TIMESTAMP(6), processed_at = NULL;
    END IF;
END$$

CREATE TRIGGER trg_ss_after_update
AFTER UPDATE ON Student_Skills
FOR EACH ROW
BEGIN
    IF COALESCE(@tnp_bulk_load, 0) = 0
       AND (NEW.proficiency_level <> OLD.proficiency_level OR NEW.skill_id <> OLD.skill_id) THEN
        INSERT INTO Match_Refresh_Queue (entity_type, entity_id)
        VALUES ('STUDENT', NEW.student_id)
        ON DUPLICATE KEY UPDATE status = 'PENDING', queued_at = CURRENT_TIMESTAMP(6), processed_at = NULL;
    END IF;
END$$

CREATE TRIGGER trg_ss_after_delete
AFTER DELETE ON Student_Skills
FOR EACH ROW
BEGIN
    IF COALESCE(@tnp_bulk_load, 0) = 0 THEN
        INSERT INTO Match_Refresh_Queue (entity_type, entity_id)
        VALUES ('STUDENT', OLD.student_id)
        ON DUPLICATE KEY UPDATE status = 'PENDING', queued_at = CURRENT_TIMESTAMP(6), processed_at = NULL;
    END IF;
END$$

CREATE TRIGGER trg_pr_after_insert
AFTER INSERT ON Posting_Requirements
FOR EACH ROW
BEGIN
    IF COALESCE(@tnp_bulk_load, 0) = 0 THEN
        INSERT INTO Match_Refresh_Queue (entity_type, entity_id)
        VALUES ('POSTING', NEW.posting_id)
        ON DUPLICATE KEY UPDATE status = 'PENDING', queued_at = CURRENT_TIMESTAMP(6), processed_at = NULL;
    END IF;
END$$

CREATE TRIGGER trg_pr_after_update
AFTER UPDATE ON Posting_Requirements
FOR EACH ROW
BEGIN
    IF COALESCE(@tnp_bulk_load, 0) = 0
       AND (NEW.required_level <> OLD.required_level OR NEW.weight <> OLD.weight
            OR NEW.skill_id <> OLD.skill_id) THEN
        INSERT INTO Match_Refresh_Queue (entity_type, entity_id)
        VALUES ('POSTING', NEW.posting_id)
        ON DUPLICATE KEY UPDATE status = 'PENDING', queued_at = CURRENT_TIMESTAMP(6), processed_at = NULL;
    END IF;
END$$

CREATE TRIGGER trg_pr_after_delete
AFTER DELETE ON Posting_Requirements
FOR EACH ROW
BEGIN
    IF COALESCE(@tnp_bulk_load, 0) = 0 THEN
        INSERT INTO Match_Refresh_Queue (entity_type, entity_id)
        VALUES ('POSTING', OLD.posting_id)
        ON DUPLICATE KEY UPDATE status = 'PENDING', queued_at = CURRENT_TIMESTAMP(6), processed_at = NULL;
    END IF;
END$$

DELIMITER ;
