import pymysql
import pytest

from tnp.db import connect


def _fails(con, sql):
    with pytest.raises(pymysql.err.OperationalError) as e:
        with con.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
    assert e.value.args[0] in (1142, 1143, 1044, 1370)   # privilege errors


def test_ml_user_can_only_write_ml_tables(db):
    c = connect("ml")
    with c.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM Students"); assert cur.fetchone()[0] > 0
        cur.execute("INSERT INTO Model_Runs (run_kind, model_name) VALUES ('MATCH','security-test')")
    c.commit()
    _fails(c, "DELETE FROM Model_Runs")          # lineage is append/update-only for the ML user
    with db.cursor() as cur:
        cur.execute("DELETE FROM Model_Runs WHERE model_name='security-test'")
    db.commit()
    _fails(c, "UPDATE Students SET cgpa = 10 WHERE student_id = 1")
    _fails(c, "DELETE FROM Placement_Outcomes")
    _fails(c, "INSERT INTO Companies (name, sector, hq_city, tier) VALUES ('x','x','x','Tier 1')")
    c.close()


def test_officer_uses_procedures_not_direct_posting_updates(db):
    c = connect("officer")
    with c.cursor() as cur:
        cur.execute("CALL sp_shortlist_for_posting(73, 3)")
        assert len(cur.fetchall()) == 3
        while cur.nextset():
            pass
    _fails(c, "UPDATE Job_Postings SET ctc = 99 WHERE posting_id = 1")
    _fails(c, "DELETE FROM Students WHERE student_id = 1")
    _fails(c, "UPDATE Placement_Outcomes SET offer_ctc = 99 WHERE student_id = 1")
    c.close()


def test_readonly_cannot_see_pii_or_write(db):
    c = connect("readonly")
    with c.cursor() as cur:
        cur.execute("SELECT student_id, name, cgpa FROM Students LIMIT 1"); assert cur.fetchone()
        cur.execute("SELECT * FROM v_early_warning LIMIT 1")
    _fails(c, "SELECT email FROM Students LIMIT 1")
    _fails(c, "SELECT resume_url FROM Students LIMIT 1")
    _fails(c, "SELECT * FROM Student_Academic_Profile LIMIT 1")
    _fails(c, "UPDATE Students SET cgpa = 0")
    _fails(c, "CALL sp_close_posting(1)")
    c.close()


def test_ml_and_readonly_cannot_read_password_hashes(db):
    for role in ("ml", "readonly"):
        c = connect(role)
        _fails(c, "SELECT password_hash FROM App_Users LIMIT 1")
        _fails(c, "SELECT * FROM Login_Audit LIMIT 1")
        c.close()
    c = connect("officer")      # the API account may read accounts (to log users in) but not drop anything
    with c.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM App_Users"); assert cur.fetchone()[0] > 7000
    _fails(c, "DELETE FROM App_Users")
    c.close()
