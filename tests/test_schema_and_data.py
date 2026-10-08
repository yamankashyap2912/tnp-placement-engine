import pymysql
import pytest

from tnp.db import query_df
from tnp.loader import dataset_row_counts


def test_object_inventory(con):
    inv = query_df(con, """
        SELECT (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE') t,
               (SELECT COUNT(*) FROM information_schema.views  WHERE table_schema=DATABASE()) v,
               (SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()) g,
               (SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema=DATABASE()) r""").iloc[0]
    assert (inv.t, inv.v, inv.g, inv.r) == (17, 12, 13, 23)


def test_row_counts_match_dataset_spec(con):
    assert (dataset_row_counts(con).status == "PASS").all()


def test_integrity_checks_have_no_failures(con):
    chk = query_df(con, "SELECT * FROM v_integrity_checks")
    assert (chk.status == "FAIL").sum() == 0
    assert chk.violations[chk.severity == "ERROR"].sum() == 0


@pytest.mark.parametrize("sql", [
    "UPDATE Students SET cgpa = 10.5 WHERE student_id = 1",                           # CHECK
    "UPDATE Students SET branch = 'MECH' WHERE student_id = 1",                        # CHECK
    "INSERT INTO Student_Skills (student_id, skill_id, proficiency_level) VALUES (1, 1, 9)",  # CHECK
    "INSERT INTO Student_Skills (student_id, skill_id, proficiency_level) VALUES (999999, 1, 3)",  # FK
    "INSERT INTO Students (name,email,branch,cgpa,batch_year) "
    "SELECT name,email,branch,cgpa,batch_year FROM Students WHERE student_id=1",       # UNIQUE email
    "UPDATE Placement_Outcomes SET offer_ctc = NULL WHERE final_status='PLACED' LIMIT 1",  # consistency CHECK
    "DELETE FROM Companies WHERE company_id = 1",                                      # FK RESTRICT
])
def test_constraints_reject_bad_data(con, sql):
    with pytest.raises(pymysql.MySQLError):
        with con.cursor() as cur:
            cur.execute(sql)


def test_cascade_delete_removes_children(con):
    sid = 7000
    before = query_df(con, f"SELECT COUNT(*) n FROM Student_Skills WHERE student_id={sid}").n[0]
    assert before > 0
    with con.cursor() as cur:
        cur.execute("DELETE FROM Students WHERE student_id=%s", (sid,))
    assert query_df(con, f"SELECT COUNT(*) n FROM Student_Skills WHERE student_id={sid}").n[0] == 0
    assert query_df(con, f"SELECT COUNT(*) n FROM Applications WHERE student_id={sid}").n[0] == 0
    con.rollback()  # restore
    assert query_df(con, f"SELECT COUNT(*) n FROM Student_Skills WHERE student_id={sid}").n[0] == before


def test_functions(con):
    r = query_df(con, "SELECT fn_cycle_year('2024-08-01') a, fn_cycle_year('2025-07-31') b, "
                      "fn_match_band(0.8) c, fn_match_band(0.1) d").iloc[0]
    assert (r.a, r.b, r.c, r.d) == (2025, 2025, "STRONG", "WEAK")
