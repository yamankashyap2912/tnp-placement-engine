"""Load the TnP CSV dataset into MySQL.

Two modes
---------
direct (default)   Fast path. Applications arrive with their final status and the
                   outcomes come from the CSV. Workflow triggers are skipped through
                   the session switch @tnp_bulk_load = 1 (constraints, foreign keys and
                   the eligibility trigger still run on every row).
via-triggers       The "whole pipeline" path. Applications arrive as APPLIED; the
                   interview rounds fire the triggers, which set every status, create
                   the PLACED outcomes and fill Application_Status_Log. The result must
                   be identical to the direct load (checked at the end).
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .config import OPTIONAL_DIR, RAW_DIR

CHUNK = 5000


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


def _insert(con, table: str, df: pd.DataFrame, expect_total: int | None = None) -> int:
    t0 = time.time()
    df = df.astype(object).where(df.notna(), None)  # empty cell -> SQL NULL
    cols = list(df.columns)
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})"
    rows = [tuple(r) for r in df.itertuples(index=False, name=None)]
    with con.cursor() as cur:
        for i in range(0, len(rows), CHUNK):
            cur.executemany(sql, rows[i : i + CHUNK])
        con.commit()
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
    want = expect_total if expect_total is not None else len(rows)
    flag = "OK" if n == want else "MISMATCH"
    print(f"  {table:26s} csv rows={len(rows):8d}  table rows={n:8d}  {flag}  ({time.time() - t0:5.1f}s)")
    if n != want:
        raise RuntimeError(f"Row-count mismatch for {table}: expected {want}, found {n}")
    return n


def _bulk_flag(con, value: int) -> None:
    with con.cursor() as cur:
        cur.execute("SET @tnp_bulk_load = %s", (value,))


def load_dataset(
    con,
    data_dir: Path = RAW_DIR,
    optional_dir: Path = OPTIONAL_DIR,
    via_triggers: bool = False,
    with_academic_profile: bool = True,
    with_dataset_match_scores: bool = False,
) -> None:
    P = lambda name: data_dir / f"{name}.csv"  # noqa: E731

    with con.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM Students")
        if cur.fetchone()[0] != 0:
            raise SystemExit(
                "Students is not empty. Run `python run.py setup-db` first (it recreates the database)."
            )

    print(f"Loading dataset ({'via triggers' if via_triggers else 'direct'} mode) ...")
    _bulk_flag(con, 1)  # master data + skills: no per-row queue / workflow triggers

    # parents first, children later (foreign-key order)
    _insert(con, "Companies", _read(P("companies")))
    _insert(con, "Skills", _read(P("skills")))
    _insert(con, "Students", _read(P("students")))
    _insert(con, "Job_Postings", _read(P("job_postings")))  # loaded OPEN; closed at the end
    _insert(con, "Posting_Requirements", _read(P("posting_requirements")))
    _insert(con, "Student_Skills", _read(P("student_skills")))

    apps = _read(P("applications"))
    final_status = dict(zip(apps.application_id, apps.status))

    if via_triggers:
        _bulk_flag(con, 0)  # now let the workflow triggers do their job
        apps = apps.assign(status="APPLIED")
    _insert(con, "Applications", apps)  # eligibility trigger checks every row
    _insert(con, "Interview_Rounds", _read(P("interview_rounds")))

    outcomes = _read(P("placement_outcomes"))
    if via_triggers:
        # Applications rejected at resume stage have no rounds -> no trigger saw them.
        with con.cursor() as cur:
            cur.execute("SELECT application_id FROM Applications WHERE status = 'APPLIED'")
            todo = [(i,) for (i,) in cur.fetchall() if final_status[i] == "REJECTED"]
            cur.executemany("UPDATE Applications SET status = 'REJECTED' WHERE application_id = %s", todo)
            con.commit()
            cur.execute("SELECT COUNT(*) FROM Placement_Outcomes")
            by_trigger = cur.fetchone()[0]
        print(f"  Placement_Outcomes rows created by trigger T6: {by_trigger}")
        # NOT_PLACED is an end-of-cycle decision no trigger can see.
        nots = outcomes[outcomes.final_status == "NOT_PLACED"].drop(columns=["outcome_id"])
        _insert(con, "Placement_Outcomes", nots, expect_total=by_trigger + len(nots))
        _bulk_flag(con, 1)
        _check_via_triggers_equals_csv(con, apps_final=final_status, outcomes=outcomes)
    else:
        _insert(con, "Placement_Outcomes", outcomes)

    if with_dataset_match_scores and P("match_scores").exists():
        _insert(con, "Match_Scores", _read(P("match_scores")))

    if with_academic_profile:
        prof_path = optional_dir / "student_academic_profile.csv"
        if prof_path.exists():
            _insert(con, "Student_Academic_Profile", _read(prof_path))

    # every posting in this dataset belongs to a finished cycle -> close them.
    # (Done last: the eligibility trigger refuses applications to CLOSED postings.)
    with con.cursor() as cur:
        cur.execute("UPDATE Job_Postings SET status = 'CLOSED' WHERE status = 'OPEN'")
    con.commit()
    _bulk_flag(con, 0)
    print("All postings closed. Dataset loaded.")


def _check_via_triggers_equals_csv(con, apps_final: dict, outcomes: pd.DataFrame) -> None:
    """Prove the trigger pipeline reproduced the CSV statuses and outcomes exactly."""
    with con.cursor() as cur:
        cur.execute("SELECT application_id, status FROM Applications")
        got = dict(cur.fetchall())
        bad = sum(1 for k, v in apps_final.items() if got.get(k) != v)
        cur.execute("SELECT student_id, final_status, posting_id, offer_ctc FROM Placement_Outcomes")
        out_db = {r[0]: (r[1], r[2], float(r[3]) if r[3] is not None else None) for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM Application_Status_Log")
        log_rows = cur.fetchone()[0]
    out_diff = 0
    for r in outcomes.itertuples(index=False):
        exp = (
            r.final_status,
            None if pd.isna(r.posting_id) else int(r.posting_id),
            None if pd.isna(r.offer_ctc) else float(r.offer_ctc),
        )
        if out_db.get(r.student_id) != exp:
            out_diff += 1
    print(
        f"  trigger pipeline vs CSV: {bad} application-status differences, "
        f"{out_diff} outcome differences, {log_rows} audit-log rows written"
    )
    if bad or out_diff:
        raise RuntimeError("Trigger-driven load differs from the CSV ground truth")


EXPECTED_ROWS = {
    "Companies": 22,
    "Skills": 49,
    "Students": 7225,
    "Job_Postings": 80,
    "Posting_Requirements": 738,
    "Student_Skills": 62432,
    "Applications": 31520,
    "Interview_Rounds": 80076,
    "Placement_Outcomes": 7225,
    "Student_Academic_Profile": 7225,
}


def dataset_row_counts(con) -> pd.DataFrame:
    rows = []
    with con.cursor() as cur:
        for table, expected in EXPECTED_ROWS.items():
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            rows.append((table, n, expected, "PASS" if n == expected else "FAIL"))
    return pd.DataFrame(rows, columns=["table", "rows", "expected", "status"])
