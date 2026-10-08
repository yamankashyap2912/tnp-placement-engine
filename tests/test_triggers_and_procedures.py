import numpy as np
import pymysql
import pytest

from tnp import match
from tnp.db import call_proc, query_df


def _one(con, sql, args=()):
    with con.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def _expect_error(con, sql, args=(), contains=""):
    with pytest.raises(pymysql.MySQLError) as e:
        with con.cursor() as cur:
            cur.execute(sql, args)
    con.rollback()
    assert contains.lower() in str(e.value).lower()


@pytest.fixture()
def open_posting(db):
    """Re-open one posting for the test and close it again afterwards."""
    pid = 1
    with db.cursor() as cur:
        cur.execute("UPDATE Job_Postings SET status='OPEN' WHERE posting_id=%s", (pid,))
    db.commit()
    yield pid
    with db.cursor() as cur:
        cur.execute("UPDATE Job_Postings SET status='CLOSED' WHERE posting_id=%s", (pid,))
    db.commit()


@pytest.fixture()
def free_student(db, open_posting):
    """An unplaced, eligible student with no application to the open posting."""
    row = query_df(db, f"""
        SELECT s.student_id FROM Students s
          JOIN Job_Postings jp ON jp.posting_id={open_posting}
          JOIN Placement_Outcomes po ON po.student_id=s.student_id AND po.final_status='NOT_PLACED'
         WHERE s.batch_year = fn_cycle_year(jp.posted_date) AND s.cgpa >= jp.min_cgpa
           AND NOT EXISTS (SELECT 1 FROM Applications a WHERE a.student_id=s.student_id AND a.posting_id=jp.posting_id)
         LIMIT 1""")
    sid = int(row.student_id[0])
    yield sid
    with db.cursor() as cur:   # clean-up: remove everything the test created
        cur.execute("DELETE FROM Applications WHERE student_id=%s AND posting_id=%s", (sid, open_posting))
        cur.execute("UPDATE Placement_Outcomes SET final_status='NOT_PLACED', posting_id=NULL, offer_ctc=NULL, "
                    "offer_date=NULL WHERE student_id=%s", (sid,))
    db.commit()


# ----------------------------------------------------------------- eligibility trigger (T4)
def test_cannot_apply_to_closed_posting(con):
    _expect_error(con, "INSERT INTO Applications (student_id, posting_id, applied_date) VALUES (14, 1, CURDATE())",
                  contains="closed")


def test_cannot_apply_below_min_cgpa(db, con, open_posting):
    sid = int(query_df(db, f"""SELECT s.student_id FROM Students s JOIN Job_Postings jp ON jp.posting_id={open_posting}
        WHERE s.batch_year=fn_cycle_year(jp.posted_date) AND s.cgpa < jp.min_cgpa LIMIT 1""").student_id[0])
    _expect_error(con, "INSERT INTO Applications (student_id, posting_id, applied_date) VALUES (%s,%s,CURDATE())",
                  (sid, open_posting), contains="cgpa")


def test_cannot_apply_to_other_cycle(db, con, open_posting):
    sid = int(query_df(db, f"""SELECT s.student_id FROM Students s JOIN Job_Postings jp ON jp.posting_id={open_posting}
        WHERE s.batch_year<>fn_cycle_year(jp.posted_date) AND s.cgpa >= jp.min_cgpa LIMIT 1""").student_id[0])
    _expect_error(con, "INSERT INTO Applications (student_id, posting_id, applied_date) VALUES (%s,%s,CURDATE())",
                  (sid, open_posting), contains="cycle")


# ----------------------------------------------------------------- lifecycle (T1, T3, T6, T7)
def test_full_lifecycle_creates_outcome_and_audit(db, open_posting, free_student):
    app = int(call_proc(db, "sp_apply_to_posting", (free_student, open_posting))[0].iloc[0, 0])
    assert call_proc(db, "sp_record_round", (app, "APTITUDE", "PASS", None))[0].new_status[0] == "IN_PROGRESS"
    assert call_proc(db, "sp_record_round", (app, "HR", "SELECT", None))[0].new_status[0] == "SELECTED"
    out = query_df(db, f"SELECT * FROM Placement_Outcomes WHERE student_id={free_student}").iloc[0]
    ctc = query_df(db, f"SELECT ctc FROM Job_Postings WHERE posting_id={open_posting}").ctc[0]
    assert out.final_status == "PLACED" and out.posting_id == open_posting and out.offer_ctc == ctc
    log = query_df(db, f"SELECT new_status FROM Application_Status_Log WHERE application_id={app} ORDER BY log_id")
    assert log.new_status.tolist() == ["IN_PROGRESS", "SELECTED"]


def test_duplicate_application_is_rejected_friendly(db, open_posting, free_student):
    call_proc(db, "sp_apply_to_posting", (free_student, open_posting))
    with pytest.raises(pymysql.MySQLError) as e:
        call_proc(db, "sp_apply_to_posting", (free_student, open_posting))
    assert "already applied" in str(e.value)


def test_reject_round_rejects_application_and_finished_is_immutable(db, open_posting, free_student):
    app = int(call_proc(db, "sp_apply_to_posting", (free_student, open_posting))[0].iloc[0, 0])
    assert call_proc(db, "sp_record_round", (app, "TECHNICAL", "REJECT", None))[0].new_status[0] == "REJECTED"
    with pytest.raises(pymysql.MySQLError) as e:
        call_proc(db, "sp_record_round", (app, "HR", "PASS", None))
    assert "finished" in str(e.value)
    with pytest.raises(pymysql.MySQLError):
        with db.cursor() as cur:
            cur.execute("UPDATE Applications SET status='IN_PROGRESS' WHERE application_id=%s", (app,))
    db.rollback()
    assert _one(db, "SELECT COUNT(*) FROM Placement_Outcomes WHERE student_id=%s AND final_status='PLACED'",
                (free_student,)) == 0


def test_round_numbers_must_be_sequential(db, open_posting, free_student):
    app = int(call_proc(db, "sp_apply_to_posting", (free_student, open_posting))[0].iloc[0, 0])
    with pytest.raises(pymysql.MySQLError) as e:
        with db.cursor() as cur:
            cur.execute("INSERT INTO Interview_Rounds (application_id, round_no, round_type, round_date, result) "
                        "VALUES (%s, 3, 'HR', CURDATE(), 'PASS')", (app,))
    db.rollback()
    assert "sequence" in str(e.value)


def test_withdraw(db, open_posting, free_student):
    app = int(call_proc(db, "sp_apply_to_posting", (free_student, open_posting))[0].iloc[0, 0])
    assert call_proc(db, "sp_withdraw_application", (app,))[0].status[0] == "WITHDRAWN"
    with pytest.raises(pymysql.MySQLError):
        call_proc(db, "sp_withdraw_application", (app,))


# ----------------------------------------------------------------- ML refresh queue
def test_skill_edit_queues_student_and_worker_rescores(db, skilldata):
    sid = 4740
    orig = query_df(db, f"SELECT skill_id, proficiency_level, evidence_source FROM Student_Skills WHERE student_id={sid}")
    before = query_df(db, f"SELECT posting_id, match_score FROM Match_Scores WHERE student_id={sid}")
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE Student_Skills SET proficiency_level = 5 WHERE student_id=%s", (sid,))
        db.commit()
        q = query_df(db, "SELECT * FROM Match_Refresh_Queue WHERE status='PENDING'")
        assert q.entity_type.tolist() == ["STUDENT"] and q.entity_id.tolist() == [sid]
        res = match.process_refresh_queue(db)
        assert res["processed"] == 1 and res["rows"] == len(before)
        after = query_df(db, f"SELECT posting_id, match_score FROM Match_Scores WHERE student_id={sid}")
        assert (after.match_score.to_numpy() >= before.match_score.to_numpy() - 1e-9).all()
        assert after.match_score.sum() > before.match_score.sum()
        assert _one(db, "SELECT COUNT(*) FROM Match_Refresh_Queue WHERE status='PENDING'") == 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM Student_Skills WHERE student_id=%s", (sid,))
            cur.executemany("INSERT INTO Student_Skills (student_id, skill_id, proficiency_level, evidence_source) "
                            "VALUES (%s,%s,%s,%s)", [(sid, int(r.skill_id), int(r.proficiency_level), r.evidence_source)
                                                     for r in orig.itertuples()])
        db.commit()
        match.process_refresh_queue(db)


def test_sql_worker_equals_python_worker(db):
    sid = 4741
    with db.cursor() as cur:
        cur.execute("UPDATE Student_Skills SET proficiency_level = proficiency_level WHERE student_id=%s LIMIT 1", (sid,))
        cur.execute("INSERT INTO Match_Refresh_Queue (entity_type, entity_id) VALUES ('STUDENT', %s) "
                    "ON DUPLICATE KEY UPDATE status='PENDING', queued_at=CURRENT_TIMESTAMP(6)", (sid,))
    db.commit()
    py_before = query_df(db, f"SELECT posting_id, match_score FROM Match_Scores WHERE student_id={sid} ORDER BY posting_id")
    n = call_proc(db, "sp_process_refresh_queue_baseline", ())[0].iloc[0, 0]
    assert n == 1
    sql_after = query_df(db, f"SELECT posting_id, match_score FROM Match_Scores WHERE student_id={sid} "
                             "AND posting_id IN (SELECT posting_id FROM Job_Postings) ORDER BY posting_id")
    merged = py_before.merge(sql_after, on="posting_id", suffixes=("_py", "_sql"))
    assert len(merged) == len(py_before)
    assert np.abs(merged.match_score_py - merged.match_score_sql).max() < 1e-9
    match.write_match_scores  # noqa: B018  (SQL proc wrote all-pairs rows; restore own-cycle scope below)


# ----------------------------------------------------------------- read procedures
def test_shortlist_is_ordered_and_limited(db):
    df = call_proc(db, "sp_shortlist_for_posting", (73, 15))[0]
    assert len(df) == 15
    assert df.match_score.is_monotonic_decreasing
    assert df.rank_no.is_monotonic_increasing and df.rank_no.iloc[0] == 1
    cycle = _one(db, "SELECT fn_cycle_year(posted_date) FROM Job_Postings WHERE posting_id=73")
    assert query_df(db, "SELECT DISTINCT batch_year FROM Students WHERE student_id IN (%s)" %
                    ",".join(map(str, df.student_id))).batch_year.tolist() == [cycle]


def test_not_applied_shortlist_excludes_applicants_and_ineligible(db):
    df = call_proc(db, "sp_shortlist_eligible_not_applied", (73, 30))[0]
    ids = ",".join(map(str, df.student_id))
    assert _one(db, f"SELECT COUNT(*) FROM Applications WHERE posting_id=73 AND student_id IN ({ids})") == 0
    min_cgpa = _one(db, "SELECT min_cgpa FROM Job_Postings WHERE posting_id=73")
    assert (df.cgpa >= float(min_cgpa)).all()


def test_student_summary_has_three_result_sets(db):
    sets = call_proc(db, "sp_student_application_summary", (1234,))
    assert len(sets) == 3 and len(sets[0]) == 1 and len(sets[2]) > 0
    with pytest.raises(pymysql.MySQLError):
        call_proc(db, "sp_student_application_summary", (99999999,))


def test_skill_gap_sql_equals_python_ablation(db, skilldata):
    sid, pid = 4740, 73
    sql = call_proc(db, "sp_skill_gap", (sid, pid))[0]
    sql = sql[sql.level_gap > 0].set_index("skill_name").potential_gain
    py = match.skill_gap_ablation(skilldata, sid, pid).set_index("skill").gain
    assert set(sql.index) == set(py.index)
    assert np.abs(sql.sort_index() - py.sort_index()).max() < 1e-3


def test_early_warning_sorted_and_filtered(db):
    df = call_proc(db, "sp_early_warning", (2026, 0.2, 3, 1))[0]
    assert len(df) > 0 and (df.probability < 0.2).all() and (df.applications_count <= 3).all()
    assert (df.placement_status != "PLACED").all() and df.probability.is_monotonic_increasing


def test_placement_report_three_result_sets(db):
    sets = call_proc(db, "sp_placement_report", (2026,))
    assert len(sets) == 3 and sets[0].students.sum() > 3000
