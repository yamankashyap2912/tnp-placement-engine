-- =============================================================================
-- 02_indexes.sql  --  Secondary indexes beyond the PK / UNIQUE / FK indexes
-- Every index below is justified by a concrete query (see docs/DBMS_CONCEPTS.md
-- and scripts/benchmark_indexes.py, which measures each one using MySQL 8
-- INVISIBLE indexes).
-- =============================================================================

-- Cohort filtering: "all CSE-AI students of batch 2026 with CGPA >= x"
CREATE INDEX idx_students_cohort ON Students (batch_year, branch, cgpa);

-- Funnel analytics: rounds by type and result
CREATE INDEX idx_ir_type_result ON Interview_Rounds (round_type, result);

-- Placement analytics: placed students by CTC
CREATE INDEX idx_po_status_ctc ON Placement_Outcomes (final_status, offer_ctc);

-- Early-warning list: lowest probabilities of one cycle first
CREATE INDEX idx_pp_cycle_prob ON Placement_Probability (cycle_year, probability);

-- Application timeline reports
CREATE INDEX idx_app_date ON Applications (applied_date);

-- NOT created on purpose (measured with `python run.py benchmark`, see docs/DBMS_CONCEPTS.md):
--   * Job_Postings(status, posted_date)       -- only 80 rows, a scan is as fast as the index
--   * Match_Scores(student_id, match_score)   -- uq_ms_pair (student_id, posting_id) already
--                                                narrows to <= 40 rows; sorting them is free
-- An index that does not pay for its write cost and storage is a liability.
