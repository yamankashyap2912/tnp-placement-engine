"""Measure what every secondary index is worth.

MySQL 8 lets us make an index INVISIBLE: it still exists and is maintained, but the
optimizer ignores it. For each (index, query) pair we time the query with the index
invisible and visible and report the speed-up and the access type from EXPLAIN.

    python run.py benchmark   ->  reports/index_benchmark.csv
"""
from __future__ import annotations

import time

import pandas as pd

from .config import REPORTS_DIR
from .db import connect, query_df

# (table, index, label, query)
CASES = [
    ("Match_Scores", "idx_ms_posting_score", "shortlist: top 20 for a posting",
     "SELECT student_id, match_score FROM Match_Scores WHERE posting_id = 73 "
     "ORDER BY match_score DESC LIMIT 20"),
    ("Students", "idx_students_cohort", "cohort filter: batch + branch + CGPA",
     "SELECT COUNT(*) FROM Students WHERE batch_year = 2026 AND branch = 'CSE-AI' AND cgpa >= 8"),
    ("Placement_Probability", "idx_pp_cycle_prob", "early-warning scan",
     "SELECT student_id FROM Placement_Probability WHERE cycle_year = 2026 AND probability < 0.2 "
     "ORDER BY probability LIMIT 50"),
    ("Placement_Outcomes", "idx_po_status_ctc", "placed students by CTC",
     "SELECT student_id, offer_ctc FROM Placement_Outcomes WHERE final_status = 'PLACED' "
     "AND offer_ctc >= 20"),
    ("Interview_Rounds", "idx_ir_type_result", "funnel: pass rate per round type",
     "SELECT COUNT(*) FROM Interview_Rounds WHERE round_type = 'TECHNICAL' AND result = 'REJECT'"),
    ("Applications", "idx_app_date", "applications in a date window",
     "SELECT COUNT(*) FROM Applications WHERE applied_date BETWEEN '2025-01-01' AND '2025-01-31'"),
]


def _time(con, sql: str, repeat: int = 7) -> float:
    best = float("inf")
    with con.cursor() as cur:
        for _ in range(repeat):
            t = time.perf_counter()
            cur.execute(sql)
            cur.fetchall()
            best = min(best, time.perf_counter() - t)
    return best * 1000  # ms


def _access(con, sql: str) -> str:
    plan = query_df(con, "EXPLAIN " + sql)
    r = plan.iloc[0]
    return f"{r['type']} ({r['key']}, ~{int(r['rows'])} rows)"


def run_benchmark() -> pd.DataFrame:
    con = connect("admin")
    rows = []
    with con.cursor() as cur:
        for table, index, label, sql in CASES:
            cur.execute(f"ALTER TABLE {table} ALTER INDEX {index} INVISIBLE")
            con.commit()
            without_ms, without_plan = _time(con, sql), _access(con, sql)
            cur.execute(f"ALTER TABLE {table} ALTER INDEX {index} VISIBLE")
            con.commit()
            with_ms, with_plan = _time(con, sql), _access(con, sql)
            rows.append({"index": index, "query": label,
                         "ms_without": round(without_ms, 2), "ms_with": round(with_ms, 2),
                         "speedup_x": round(without_ms / max(with_ms, 0.001), 1),
                         "plan_without": without_plan, "plan_with": with_plan})
    df = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(REPORTS_DIR / "index_benchmark.csv", index=False)
    print(df[["index", "query", "ms_without", "ms_with", "speedup_x"]].to_string(index=False))
    print(f"\n  written to {REPORTS_DIR / 'index_benchmark.csv'}")
    return df
