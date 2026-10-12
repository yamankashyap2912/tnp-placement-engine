-- =============================================================================
-- 03_functions.sql  --  Stored functions used by triggers, procedures and views
-- =============================================================================

DELIMITER $$

-- Placement cycle of a posting date. The recruiting season runs Aug -> Jul and a
-- batch graduates at the end of it:  Aug 2024 .. Jul 2025  ->  cycle 2025.
-- (Verified on the dataset: every application matches student.batch_year.)
DROP FUNCTION IF EXISTS fn_cycle_year$$
CREATE FUNCTION fn_cycle_year(p_date DATE)
RETURNS SMALLINT
DETERMINISTIC
NO SQL
BEGIN
    RETURN YEAR(p_date) + IF(MONTH(p_date) >= 8, 1, 0);
END$$

-- Is the student allowed to apply to the posting?  1 = eligible, 0 = not.
-- Rules: CGPA >= min_cgpa  AND  posting belongs to the student's own cycle.
DROP FUNCTION IF EXISTS fn_is_eligible$$
CREATE FUNCTION fn_is_eligible(p_student_id INT UNSIGNED, p_posting_id INT UNSIGNED)
RETURNS TINYINT
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_ok TINYINT DEFAULT 0;
    SELECT (s.cgpa >= jp.min_cgpa AND s.batch_year = fn_cycle_year(jp.posted_date))
      INTO v_ok
      FROM Students s, Job_Postings jp
     WHERE s.student_id = p_student_id AND jp.posting_id = p_posting_id;
    RETURN COALESCE(v_ok, 0);
END$$

-- Human readable band for a match score (used in reports / dashboards).
DROP FUNCTION IF EXISTS fn_match_band$$
CREATE FUNCTION fn_match_band(p_score DECIMAL(5,4))
RETURNS VARCHAR(10)
DETERMINISTIC
NO SQL
BEGIN
    RETURN CASE
             WHEN p_score IS NULL THEN 'UNKNOWN'
             WHEN p_score >= 0.7500 THEN 'STRONG'
             WHEN p_score >= 0.5000 THEN 'GOOD'
             WHEN p_score >= 0.3000 THEN 'FAIR'
             ELSE 'WEAK'
           END;
END$$

DELIMITER ;