"""Operations: pipeline writes, early warning, ML jobs, insights, database health, assistant."""
from __future__ import annotations

import threading
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import match as match_mod
from .. import placement as placement_mod
from ..config import REPORTS_DIR
from ..db import connect
from ..matrices import SkillData
from . import assistant
from .deps import (call_proc, current_user, ensure_posting_access, officer_con, one, query_df, readonly_con, records,
                   require)
from .security import Principal

router = APIRouter(prefix="/api")
_ML_LOCK = threading.Lock()


# =============================================================== pipeline writes (stored procedures do the work)
class ApplyBody(BaseModel):
    student_id: int
    posting_id: int


@router.post("/applications")
def apply(body: ApplyBody, p: Principal = Depends(require("ADMIN", "STUDENT")), con=Depends(officer_con)):
    if p.role == "STUDENT" and body.student_id != p.student_id:
        raise HTTPException(403, "You can only apply for yourself.")
    out = call_proc(con, "sp_apply_to_posting", (body.student_id, body.posting_id))
    return one(out[0])


class RoundBody(BaseModel):
    round_type: str
    result: str
    round_date: str | None = None


@router.post("/applications/{application_id}/rounds")
def record_round(application_id: int, body: RoundBody, p: Principal = Depends(require("ADMIN", "RECRUITER")),
                 con=Depends(officer_con)):
    row = query_df(con, "SELECT posting_id FROM Applications WHERE application_id=%s", (application_id,))
    if row.empty:
        raise HTTPException(404, "Application not found.")
    ensure_posting_access(con, p, int(row.posting_id.iloc[0]))
    if body.round_type.upper() not in ("APTITUDE", "TECHNICAL", "GD", "HR"):
        raise HTTPException(400, "Round type must be APTITUDE, TECHNICAL, GD or HR.")
    if body.result.upper() not in ("PENDING", "PASS", "REJECT", "SELECT"):
        raise HTTPException(400, "Result must be PENDING, PASS, REJECT or SELECT.")
    return one(call_proc(con, "sp_record_round",
                         (application_id, body.round_type.upper(), body.result.upper(), body.round_date))[0])


@router.post("/applications/{application_id}/withdraw")
def withdraw(application_id: int, p: Principal = Depends(require("ADMIN", "STUDENT")), con=Depends(officer_con)):
    row = query_df(con, "SELECT student_id FROM Applications WHERE application_id=%s", (application_id,))
    if row.empty:
        raise HTTPException(404, "Application not found.")
    if p.role == "STUDENT" and int(row.student_id.iloc[0]) != p.student_id:
        raise HTTPException(403, "Not your application.")
    return one(call_proc(con, "sp_withdraw_application", (application_id,))[0])


@router.get("/audit/status-log")
def status_log(limit: int = Query(40, ge=1, le=200), p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    return records(query_df(con, """
        SELECT l.log_id, l.changed_at, l.application_id, s.name AS student, c.name AS company, jp.role_title,
               l.old_status, l.new_status, l.changed_by
          FROM Application_Status_Log l
          JOIN Applications a ON a.application_id = l.application_id
          JOIN Students s ON s.student_id = a.student_id
          JOIN Job_Postings jp ON jp.posting_id = a.posting_id
          JOIN Companies c ON c.company_id = jp.company_id
         ORDER BY l.log_id DESC LIMIT %s""", (limit,)))


# =============================================================== early warning
@router.get("/early-warning")
def early_warning(cycle: int = 2026, threshold: float = Query(0.30, ge=0.01, le=1.0), max_apps: int | None = None,
                  branch: str | None = None, exclude_placed: bool = True,
                  p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    df = call_proc(con, "sp_early_warning", (cycle, threshold, max_apps, int(exclude_placed)))[0]
    if branch and not df.empty:
        df = df[df.branch == branch]
    bands = {"CRITICAL": 0, "HIGH": 0, "MODERATE": 0}
    for v in df.probability if not df.empty else []:
        bands["CRITICAL" if v < 0.15 else "HIGH" if v < 0.30 else "MODERATE"] += 1
    by_branch = df.groupby("branch").size().to_dict() if not df.empty else {}
    return {"count": int(len(df)), "bands": bands, "by_branch": by_branch, "rows": records(df.head(500))}


# =============================================================== ML operations
class MatchBody(BaseModel):
    method: str = "coverage"


class TrainBody(BaseModel):
    feature_set: str = "preseason"


def _locked(fn):
    if not _ML_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Another ML job is running. Try again in a moment.")
    try:
        return fn()
    finally:
        _ML_LOCK.release()


@router.post("/ml/match")
def ml_match(body: MatchBody, p: Principal = Depends(require("ADMIN"))):
    if body.method not in ("coverage", "cosine", "learned"):
        raise HTTPException(400, "Method must be coverage, cosine or learned.")

    def job():
        con = connect("ml")                      # least-privilege ML account
        try:
            d = SkillData.load(con)
            res = match_mod.score_matrix(d, con, body.method)
            run = match_mod.write_match_scores(con, d, res)
            return {"run_id": run, "method": body.method, "metrics": res.metrics}
        finally:
            con.close()
    return _locked(job)


@router.post("/ml/train")
def ml_train(body: TrainBody, p: Principal = Depends(require("ADMIN"))):
    def job():
        con = connect("ml")
        try:
            res, preds = placement_mod.train(con, body.feature_set)
            run = placement_mod.write_probabilities(con, preds, res)
            return {"run_id": run, "model": res.model_name, "metrics": res.metrics}
        finally:
            con.close()
    return _locked(job)


@router.post("/ml/worker")
def ml_worker(p: Principal = Depends(require("ADMIN"))):
    def job():
        con = connect("ml")
        try:
            return match_mod.process_refresh_queue(con)
        finally:
            con.close()
    return _locked(job)


@router.post("/ml/report")
def ml_report(p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    from ..reports import generate_report
    _locked(lambda: generate_report(con))
    return {"ok": True}


# =============================================================== insights (cached report files + live lineage)
def _csv(name: str) -> list[dict]:
    path = Path(REPORTS_DIR) / name
    return records(pd.read_csv(path)) if path.exists() else []


@router.get("/insights")
def insights(p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    runs = query_df(con, "SELECT run_id, run_kind, model_name, rows_written, status, started_at, finished_at "
                         "FROM Model_Runs ORDER BY run_id DESC LIMIT 15")
    queue = query_df(con, "SELECT status, COUNT(*) AS n FROM Match_Refresh_Queue GROUP BY status")
    return {"match_models": _csv("match_model_comparison.csv"),
            "placement_models": _csv("placement_model_comparison.csv"),
            "lift": _csv("placement_lift_by_decile.csv"),
            "importance": _csv("placement_feature_importance.csv")[:12],
            "runs": records(runs), "queue": records(queue),
            "report_ready": (Path(REPORTS_DIR) / "evaluation_report.md").exists()}


# =============================================================== database health
@router.get("/health/integrity")
def integrity(p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    return records(query_df(con, "SELECT check_name, severity, violations, status FROM v_integrity_checks"))


@router.get("/health/catalog")
def catalog(p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    objs = query_df(con, "SELECT object_type, object_name, detail FROM v_catalog_objects ORDER BY object_type, object_name")
    triggers = call_proc(con, "sp_catalog_triggers", ())[0]
    idx = query_df(con, "SELECT table_name, index_name, uniqueness, index_columns FROM v_catalog_indexes "
                        "ORDER BY table_name, index_name")
    tables = objs[objs.object_type == "TABLE"].object_name.tolist()
    counts = []
    for t in tables:
        n = int(query_df(con, f"SELECT COUNT(*) AS n FROM `{t}`").n.iloc[0])
        counts.append({"table": t, "rows": n})
    summary = objs.groupby("object_type").size().to_dict()
    summary["TRIGGER"] = int(len(triggers))
    return {"summary": summary, "tables": counts, "routines": records(objs[objs.object_type.isin(["PROCEDURE", "FUNCTION"])]),
            "views": records(objs[objs.object_type == "VIEW"]), "triggers": records(triggers),
            "indexes": records(idx), "benchmark": _csv("index_benchmark.csv")}


@router.get("/health/explain/{posting_id}")
def explain(posting_id: int, p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    plan = query_df(con, "EXPLAIN SELECT student_id, match_score FROM Match_Scores WHERE posting_id=%s "
                         "ORDER BY match_score DESC LIMIT 20", (posting_id,))
    return {"sql": f"SELECT student_id, match_score FROM Match_Scores WHERE posting_id = {posting_id} "
                   "ORDER BY match_score DESC LIMIT 20", "plan": records(plan)}


# =============================================================== assistant (readonly_analyst account)
class AskBody(BaseModel):
    question: str


class SqlBody(BaseModel):
    sql: str


@router.get("/assistant/examples")
def examples(p: Principal = Depends(require("ADMIN"))):
    return assistant.EXAMPLES


@router.post("/assistant/ask")
def ask(body: AskBody, p: Principal = Depends(require("ADMIN")), con=Depends(readonly_con)):
    try:
        return assistant.ask(con, body.question)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/assistant/sql")
def sql_console(body: SqlBody, p: Principal = Depends(require("ADMIN")), con=Depends(readonly_con)):
    try:
        return assistant.run_select(con, body.sql)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# =============================================================== student / recruiter home pages
@router.get("/me/overview")
def my_overview(p: Principal = Depends(require("STUDENT", "RECRUITER")), con=Depends(officer_con)):
    if p.role == "STUDENT":
        sets = call_proc(con, "sp_student_application_summary", (p.student_id,))
        matches = call_proc(con, "sp_student_matches", (p.student_id, 1, 6))[0]
        batch = int(sets[0].batch_year.iloc[0])
        peers = query_df(con, "SELECT COUNT(*) AS n, SUM(cgpa < %s) AS below FROM Students WHERE batch_year=%s",
                         (float(sets[0].cgpa.iloc[0]), batch))
        statuses = sets[1].status.value_counts().to_dict() if len(sets[1]) else {}
        return {"role": "STUDENT", "profile": one(sets[0]), "applications": records(sets[1]), "skills": records(sets[2]),
                "top_matches": records(matches), "status_counts": statuses,
                "cgpa_percentile": round(100 * float(peers.below.iloc[0]) / max(1, int(peers.n.iloc[0])), 1)}
    comp = query_df(con, "SELECT * FROM v_company_summary WHERE company_id=%s", (p.company_id,))
    posts = query_df(con, "SELECT ps.*, jp.posted_date FROM v_posting_stats ps JOIN Job_Postings jp "
                          "ON jp.posting_id=ps.posting_id WHERE jp.company_id=%s ORDER BY ps.cycle_year DESC, ps.applicants DESC",
                     (p.company_id,))
    return {"role": "RECRUITER", "company": one(comp), "postings": records(posts)}
