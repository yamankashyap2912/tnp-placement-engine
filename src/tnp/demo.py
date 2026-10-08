"""Scripted viva demo: every DBMS feature, live, and cleaned up afterwards.

    python run.py demo

  1. the core query: ranked shortlist straight from Match_Scores
  2. THE live moment: edit a student's skills -> trigger queues him/her -> worker
     re-scores -> the ranking changes -> everything is restored
  3. business rules enforced by triggers (closed posting, CGPA, finished application ...)
  4. a full transactional application lifecycle (apply -> rounds -> SELECT -> placement
     outcome + audit trail created by triggers) and its clean-up
  5. the skill-gap coach in SQL
The demo leaves the database exactly as it found it.
"""
from __future__ import annotations

import pandas as pd
import pymysql

from . import match as match_mod
from .db import call_proc, query_df
from .matrices import SkillData

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def _h(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def _expect_error(con, label: str, sql: str, args: tuple = ()) -> None:
    try:
        with con.cursor() as cur:
            cur.execute(sql, args)
        con.commit()
        print(f"  [UNEXPECTED SUCCESS] {label}")
    except pymysql.MySQLError as exc:
        con.rollback()
        msg = exc.args[1] if len(exc.args) > 1 else str(exc)
        print(f"  [BLOCKED] {label}\n            -> {msg}")


def run_demo(con) -> None:
    d = SkillData.load(con)

    # pick a posting with plenty of applicants and a clear cohort
    posting = query_df(con, "SELECT posting_id, company, role_title, cycle_year, applicants "
                            "FROM v_posting_stats ORDER BY applicants DESC LIMIT 1").iloc[0]
    pid = int(posting.posting_id)
    _h(f"1. Core query: sp_shortlist_for_posting({pid}, 10)  -- {posting.company}, {posting.role_title}")
    top = call_proc(con, "sp_shortlist_for_posting", (pid, 10))[0]
    print(top.to_string(index=False))
    print("\nEXPLAIN of the ORDER BY (served by idx_ms_posting_score, no filesort of the whole table):")
    print(query_df(con, "EXPLAIN SELECT student_id, match_score FROM Match_Scores "
                        f"WHERE posting_id = {pid} ORDER BY match_score DESC LIMIT 10")
          [["table", "type", "key", "rows", "Extra"]].to_string(index=False))

    # ------------------------------------------------------------------ 2
    _h("2. Live moment: edit skills -> trigger -> re-score -> ranking changes")
    full = call_proc(con, "sp_shortlist_for_posting", (pid, 60))[0]
    target = full.iloc[40]            # a student around rank 41
    sid = int(target.student_id)
    print(f"Student {sid} ({target['name']}) is currently rank {int(target.rank_no)} "
          f"with match {target.match_score:.4f}.")
    with con.cursor() as cur:
        cur.execute("SELECT skill_id, proficiency_level, evidence_source FROM Student_Skills WHERE student_id=%s", (sid,))
        original = cur.fetchall()
        cur.execute("SELECT skill_id, required_level FROM Posting_Requirements WHERE posting_id=%s", (pid,))
        reqs = cur.fetchall()
        for skill_id, level in reqs:      # student upskills in every required skill
            cur.execute(
                "INSERT INTO Student_Skills (student_id, skill_id, proficiency_level, evidence_source) "
                "VALUES (%s,%s,%s,'Certification') "
                "ON DUPLICATE KEY UPDATE proficiency_level = GREATEST(proficiency_level, VALUES(proficiency_level))",
                (sid, skill_id, level))
    con.commit()
    print("After the skill edit the triggers queued the student:")
    print(query_df(con, "SELECT * FROM Match_Refresh_Queue WHERE status='PENDING'").to_string(index=False))
    res = match_mod.process_refresh_queue(con, SkillData.load(con))
    print(f"Worker re-scored {res['rows']} (student, posting) pairs for {res['processed']} queue entries.")
    after = call_proc(con, "sp_shortlist_for_posting", (pid, 10))[0]
    print(after.head(5).to_string(index=False))
    # restore
    with con.cursor() as cur:
        cur.execute("DELETE FROM Student_Skills WHERE student_id=%s", (sid,))
        cur.executemany("INSERT INTO Student_Skills (student_id, skill_id, proficiency_level, evidence_source) "
                        "VALUES (%s,%s,%s,%s)", [(sid, *row) for row in original])
    con.commit()
    match_mod.process_refresh_queue(con, SkillData.load(con))
    restored = call_proc(con, "sp_shortlist_for_posting", (pid, 60))[0]
    r_now = int(restored[restored.student_id == sid].rank_no.iloc[0])
    print(f"(restored: student {sid} is back at rank {r_now})")

    # ------------------------------------------------------------------ 3
    _h("3. Business rules enforced INSIDE the database (triggers)")
    closed = int(pid)  # every dataset posting is CLOSED (finished cycle)
    stu = query_df(con, f"SELECT student_id FROM Students WHERE batch_year={int(posting.cycle_year)} LIMIT 1").iloc[0, 0]
    _expect_error(con, "apply to a CLOSED posting",
                  "INSERT INTO Applications (student_id, posting_id, applied_date) VALUES (%s,%s,CURDATE())",
                  (int(stu), closed))
    # re-open the posting for a moment so the remaining eligibility rules are reached
    with con.cursor() as cur:
        cur.execute("UPDATE Job_Postings SET status='OPEN' WHERE posting_id=%s", (pid,))
    con.commit()
    try:
        other = query_df(con, f"SELECT student_id FROM Students WHERE batch_year<>{int(posting.cycle_year)} LIMIT 1").iloc[0, 0]
        _expect_error(con, "wrong placement cycle (student of another batch)",
                      "INSERT INTO Applications (student_id, posting_id, applied_date) VALUES (%s,%s,CURDATE())",
                      (int(other), pid))
        low = query_df(con, f"SELECT s.student_id FROM Students s JOIN Job_Postings jp ON jp.posting_id={pid} "
                            f"WHERE s.batch_year={int(posting.cycle_year)} AND s.cgpa < jp.min_cgpa LIMIT 1")
        if len(low):
            _expect_error(con, "student CGPA below the posting minimum",
                          "INSERT INTO Applications (student_id, posting_id, applied_date) VALUES (%s,%s,CURDATE())",
                          (int(low.iloc[0, 0]), pid))
    finally:
        with con.cursor() as cur:
            cur.execute("UPDATE Job_Postings SET status='CLOSED' WHERE posting_id=%s", (pid,))
        con.commit()
    fin = query_df(con, "SELECT application_id FROM Applications WHERE status='REJECTED' LIMIT 1").iloc[0, 0]
    _expect_error(con, "change a finished (REJECTED) application back to IN_PROGRESS",
                  "UPDATE Applications SET status='IN_PROGRESS' WHERE application_id=%s", (int(fin),))
    _expect_error(con, "add a round to a finished application",
                  "INSERT INTO Interview_Rounds (application_id, round_no, round_type, round_date, result) "
                  "VALUES (%s, 99, 'HR', CURDATE(), 'PASS')", (int(fin),))
    _expect_error(con, "CGPA 11 (CHECK constraint)",
                  "UPDATE Students SET cgpa = 11 WHERE student_id = %s", (int(stu),))
    _expect_error(con, "delete a skill that postings still require (FK RESTRICT)",
                  "DELETE FROM Skills WHERE skill_id = 1")

    # ------------------------------------------------------------------ 4
    _h("4. Transactional lifecycle: apply -> rounds -> SELECT -> outcome + audit log")
    cand = query_df(con, """
        SELECT s.student_id, jp.posting_id
          FROM Students s
          JOIN Job_Postings jp ON fn_cycle_year(jp.posted_date) = s.batch_year AND jp.min_cgpa <= s.cgpa
          JOIN Placement_Outcomes po ON po.student_id = s.student_id AND po.final_status = 'NOT_PLACED'
         WHERE NOT EXISTS (SELECT 1 FROM Applications a WHERE a.student_id = s.student_id
                                                           AND a.posting_id = jp.posting_id)
         LIMIT 1""").iloc[0]
    cs, cp = int(cand.student_id), int(cand.posting_id)
    with con.cursor() as cur:
        cur.execute("SELECT status FROM Job_Postings WHERE posting_id=%s", (cp,))
        was = cur.fetchone()[0]
        cur.execute("UPDATE Job_Postings SET status='OPEN' WHERE posting_id=%s", (cp,))
    con.commit()
    try:
        app_id = int(call_proc(con, "sp_apply_to_posting", (cs, cp))[0].iloc[0, 0])
        print(f"sp_apply_to_posting({cs}, {cp}) -> application {app_id}")
        _expect_error(con, "apply twice to the same posting",
                      "CALL sp_apply_to_posting(%s,%s)", (cs, cp))
        for typ, res_ in [("APTITUDE", "PASS"), ("TECHNICAL", "PASS"), ("HR", "SELECT")]:
            out = call_proc(con, "sp_record_round", (app_id, typ, res_, None))[0]
            print(f"  round {typ:9s} {res_:6s} -> application status: {out.new_status.iloc[0]}")
        print("Trigger T6 created the outcome:")
        print(query_df(con, f"SELECT * FROM Placement_Outcomes WHERE student_id={cs}").to_string(index=False))
        print("Trigger T7 wrote the audit trail:")
        print(query_df(con, f"SELECT old_status,new_status,changed_by FROM Application_Status_Log "
                            f"WHERE application_id={app_id} ORDER BY log_id").to_string(index=False))
    finally:   # leave no trace
        with con.cursor() as cur:
            cur.execute("DELETE FROM Applications WHERE student_id=%s AND posting_id=%s", (cs, cp))
            cur.execute("UPDATE Placement_Outcomes SET final_status='NOT_PLACED', posting_id=NULL, "
                        "offer_ctc=NULL, offer_date=NULL WHERE student_id=%s", (cs,))
            cur.execute("UPDATE Job_Postings SET status=%s WHERE posting_id=%s", (was, cp))
        con.commit()
        print("(demo application removed, outcome and posting status restored)")

    # ------------------------------------------------------------------ 5
    _h("5. Skill-gap coach: sp_skill_gap(student, posting)")
    gap = call_proc(con, "sp_skill_gap", (sid, pid))
    print(gap[0].head(6).to_string(index=False))
    print("\nSame answer from the Python ablation (re-score with the skill fixed):")
    print(match_mod.skill_gap_ablation(SkillData.load(con), sid, pid).head(3).to_string(index=False))
    print("\nDemo finished; database restored.")
