"""Auth, filters, overview, postings, companies, students.
Every endpoint is a thin wrapper around an existing stored procedure or view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .deps import (call_proc, current_user, ensure_posting_access, ensure_student_access, officer_con, one,
                   query_df, records, require)
from .security import Principal, hash_password, make_token, verify_password

router = APIRouter(prefix="/api")


# =============================================================== auth
class Login(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.post("/auth/login")
def login(body: Login, request: Request, con=Depends(officer_con)):
    row = query_df(con, "SELECT user_id, username, password_hash, role, display_name, student_id, company_id, is_active "
                        "FROM App_Users WHERE username=%s", (body.username.strip(),))
    ok = (not row.empty and bool(row.is_active.iloc[0]) and verify_password(body.password, row.password_hash.iloc[0]))
    ip = request.client.host if request.client else None
    with con.cursor() as cur:
        cur.execute("INSERT INTO Login_Audit (username, success, client_ip) VALUES (%s,%s,%s)",
                    (body.username.strip()[:120], int(ok), ip))
        if ok:
            cur.execute("UPDATE App_Users SET last_login_at = NOW() WHERE user_id=%s", (int(row.user_id.iloc[0]),))
    con.commit()
    if not ok:
        raise HTTPException(401, "Wrong username or password.")
    r = row.iloc[0]
    p = Principal(int(r.user_id), r.username, r.role, r.display_name,
                  None if r.student_id is None or r.student_id != r.student_id else int(r.student_id),
                  None if r.company_id is None or r.company_id != r.company_id else int(r.company_id))
    return {"token": make_token(p), "user": p.__dict__}


@router.get("/auth/demo-accounts")
def demo_accounts(con=Depends(officer_con)):
    """Sign-in shortcuts for the demo deployment (disable with TNP_DEMO_MODE=0)."""
    import os
    if os.environ.get("TNP_DEMO_MODE", "1") == "0":
        raise HTTPException(404, "Not available.")
    from ..users import DEMO
    rec = query_df(con, "SELECT u.username, c.name FROM App_Users u JOIN Companies c ON c.company_id=u.company_id "
                        "WHERE u.role='RECRUITER' ORDER BY (SELECT COUNT(*) FROM Job_Postings jp WHERE jp.company_id=c.company_id) DESC, u.user_id LIMIT 1")
    stu = query_df(con, "SELECT u.username, s.name, s.batch_year FROM App_Users u JOIN Students s ON s.student_id=u.student_id "
                        "JOIN Placement_Probability pp ON pp.student_id=s.student_id "
                        "WHERE s.batch_year=(SELECT MAX(batch_year) FROM Students) AND pp.probability BETWEEN 0.25 AND 0.4 "
                        "ORDER BY s.student_id LIMIT 1")
    accounts = [{"label": "TnP officer (full access)", "username": "admin", "password": DEMO["admin"][1]}]
    if len(rec):
        accounts.append({"label": f"Recruiter - {rec.name[0]}", "username": rec.username[0], "password": DEMO["recruiter"][1]})
    if len(stu):
        accounts.append({"label": f"Student - {stu.name[0]} (batch {int(stu.batch_year[0])})", "username": stu.username[0], "password": DEMO["student"][1]})
    return {"accounts": accounts}


@router.get("/auth/me")
def me(p: Principal = Depends(current_user)):
    return p.__dict__


@router.post("/auth/change-password")
def change_password(body: PasswordChange, p: Principal = Depends(current_user), con=Depends(officer_con)):
    if len(body.new_password) < 8:
        raise HTTPException(400, "Use at least 8 characters.")
    row = query_df(con, "SELECT password_hash FROM App_Users WHERE user_id=%s", (p.user_id,))
    if row.empty or not verify_password(body.old_password, row.password_hash.iloc[0]):
        raise HTTPException(400, "Current password is wrong.")
    with con.cursor() as cur:
        cur.execute("UPDATE App_Users SET password_hash=%s WHERE user_id=%s", (hash_password(body.new_password), p.user_id))
    con.commit()
    return {"ok": True}


# =============================================================== filters used by every page
@router.get("/meta/filters")
def filters(p: Principal = Depends(current_user), con=Depends(officer_con)):
    cycles = [int(c) for c in query_df(con, "SELECT DISTINCT batch_year FROM Students ORDER BY batch_year").batch_year]
    branches = list(query_df(con, "SELECT DISTINCT branch FROM Students ORDER BY branch").branch)
    sql = "SELECT posting_id, company, tier, role_title, ctc, min_cgpa, cycle_year, status FROM v_posting_stats"
    args: tuple = ()
    if p.role == "RECRUITER":
        sql += " WHERE posting_id IN (SELECT posting_id FROM Job_Postings WHERE company_id=%s)"
        args = (p.company_id,)
    elif p.role == "STUDENT":
        sql += " WHERE cycle_year = (SELECT batch_year FROM Students WHERE student_id=%s)"
        args = (p.student_id,)
    postings = query_df(con, sql + " ORDER BY cycle_year DESC, company, role_title", args)
    skills = query_df(con, "SELECT skill_id, skill_name, category FROM Skills ORDER BY skill_name")
    return {"cycles": cycles, "branches": branches, "postings": records(postings), "skills": records(skills)}


# =============================================================== overview (admin)
@router.get("/overview")
def overview(cycle: int | None = None, p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    kpis = one(call_proc(con, "sp_dashboard_kpis", (cycle,))[0])
    branch = query_df(con, "SELECT batch_year, branch, students, placed, placement_pct, avg_ctc_lpa, avg_cgpa "
                           "FROM v_branch_placement_summary WHERE (%s IS NULL OR batch_year=%s) ORDER BY batch_year, branch",
                      (cycle, cycle))
    rep = call_proc(con, "sp_placement_report", (cycle or 2026,))
    where = "AND s.batch_year=%s" if cycle else ""
    args = (cycle,) if cycle else ()
    ctc = query_df(con, f"SELECT FLOOR(po.offer_ctc/5)*5 AS bucket, COUNT(*) AS n FROM Placement_Outcomes po "
                        f"JOIN Students s ON s.student_id=po.student_id WHERE po.final_status='PLACED' {where} "
                        f"GROUP BY bucket ORDER BY bucket", args)
    prob = query_df(con, f"SELECT FLOOR(LEAST(pp.probability,0.9999)*10) AS bucket, COUNT(*) AS n FROM Placement_Probability pp "
                         f"JOIN Students s ON s.student_id=pp.student_id WHERE 1=1 {where} GROUP BY bucket ORDER BY bucket", args)
    top_posting = query_df(con, "SELECT posting_id FROM v_posting_stats WHERE (%s IS NULL OR cycle_year=%s) "
                                "ORDER BY applicants DESC LIMIT 1", (cycle, cycle))
    top_companies = query_df(con, "SELECT name, tier, offers, applications, offer_rate_pct FROM v_company_summary "
                                  "ORDER BY offers DESC LIMIT 6")
    return {"kpis": kpis, "branch": records(branch), "tiers": records(rep[1]), "top_recruiters": records(rep[2]),
            "ctc_hist": records(ctc), "prob_hist": records(prob), "top_companies": records(top_companies),
            "featured_posting_id": int(top_posting.posting_id.iloc[0]) if len(top_posting) else None}


# =============================================================== postings / companies
@router.get("/postings")
def postings(cycle: int | None = None, status: str | None = None, q: str | None = None,
             company_id: int | None = None, p: Principal = Depends(current_user), con=Depends(officer_con)):
    if p.role == "RECRUITER":
        company_id = p.company_id
    sql = ("SELECT ps.*, jp.company_id, jp.posted_date FROM v_posting_stats ps "
           "JOIN Job_Postings jp ON jp.posting_id = ps.posting_id WHERE 1=1")
    args: list = []
    if p.role == "STUDENT":
        sql += " AND ps.cycle_year = (SELECT batch_year FROM Students WHERE student_id=%s)"
        args.append(p.student_id)
    if cycle:
        sql += " AND ps.cycle_year=%s"; args.append(cycle)
    if status:
        sql += " AND ps.status=%s"; args.append(status.upper())
    if company_id:
        sql += " AND jp.company_id=%s"; args.append(company_id)
    if q:
        sql += " AND (ps.company LIKE %s OR ps.role_title LIKE %s)"; args += [f"%{q}%", f"%{q}%"]
    return records(query_df(con, sql + " ORDER BY ps.applicants DESC", args))


@router.get("/postings/{posting_id}")
def posting_detail(posting_id: int, p: Principal = Depends(current_user), con=Depends(officer_con)):
    ensure_posting_access(con, p, posting_id)
    head = query_df(con, "SELECT ps.*, c.sector, c.hq_city, jp.company_id, jp.posted_date FROM v_posting_stats ps "
                         "JOIN Job_Postings jp ON jp.posting_id=ps.posting_id JOIN Companies c ON c.company_id=jp.company_id "
                         "WHERE ps.posting_id=%s", (posting_id,))
    reqs = query_df(con, "SELECT sk.skill_id, sk.skill_name, sk.category, pr.required_level, pr.weight "
                         "FROM Posting_Requirements pr JOIN Skills sk ON sk.skill_id=pr.skill_id "
                         "WHERE pr.posting_id=%s ORDER BY pr.weight DESC", (posting_id,))
    funnel = query_df(con, "SELECT applications, stopped_at_resume, reached_round_1, reached_round_2, reached_round_3, selected "
                           "FROM v_application_funnel WHERE posting_id=%s", (posting_id,))
    return {"posting": one(head), "requirements": records(reqs), "funnel": one(funnel)}


@router.get("/postings/{posting_id}/shortlist")
def shortlist(posting_id: int, top: int = Query(20, ge=1, le=200), not_applied: bool = False,
              p: Principal = Depends(require("ADMIN", "RECRUITER")), con=Depends(officer_con)):
    ensure_posting_access(con, p, posting_id)
    proc = "sp_shortlist_eligible_not_applied" if not_applied else "sp_shortlist_for_posting"
    return records(call_proc(con, proc, (posting_id, top))[0])


@router.get("/postings/{posting_id}/pipeline")
def pipeline(posting_id: int, p: Principal = Depends(require("ADMIN", "RECRUITER")), con=Depends(officer_con)):
    ensure_posting_access(con, p, posting_id)
    return records(call_proc(con, "sp_posting_pipeline", (posting_id,))[0])


class StatusBody(BaseModel):
    status: str


@router.post("/postings/{posting_id}/status")
def posting_status(posting_id: int, body: StatusBody, p: Principal = Depends(require("ADMIN", "RECRUITER")),
                   con=Depends(officer_con)):
    ensure_posting_access(con, p, posting_id)
    st = body.status.upper()
    if st not in ("OPEN", "CLOSED"):
        raise HTTPException(400, "Status must be OPEN or CLOSED.")
    return one(call_proc(con, "sp_open_posting" if st == "OPEN" else "sp_close_posting", (posting_id,))[0])


@router.get("/companies")
def companies(p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    return records(query_df(con, "SELECT * FROM v_company_summary ORDER BY offers DESC"))


# =============================================================== students
@router.get("/students")
def students(q: str | None = None, cycle: int | None = None, branch: str | None = None,
             min_cgpa: float | None = None, status: str | None = None,
             page: int = Query(1, ge=1), size: int = Query(25, ge=5, le=100),
             p: Principal = Depends(require("ADMIN")), con=Depends(officer_con)):
    where, args = ["1=1"], []
    if q:
        if q.isdigit():
            where.append("student_id=%s"); args.append(int(q))
        else:
            where.append("name LIKE %s"); args.append(f"%{q}%")
    if cycle:
        where.append("batch_year=%s"); args.append(cycle)
    if branch:
        where.append("branch=%s"); args.append(branch)
    if min_cgpa:
        where.append("cgpa>=%s"); args.append(min_cgpa)
    if status:
        where.append("placement_status=%s"); args.append(status)
    w = " AND ".join(where)
    total = int(query_df(con, f"SELECT COUNT(*) n FROM v_student_status WHERE {w}", args).n.iloc[0])
    rows = query_df(con, f"SELECT * FROM v_student_status WHERE {w} ORDER BY student_id LIMIT %s OFFSET %s",
                    args + [size, (page - 1) * size])
    return {"total": total, "page": page, "size": size, "rows": records(rows)}


@router.get("/students/{student_id}")
def student_360(student_id: int, p: Principal = Depends(current_user), con=Depends(officer_con)):
    ensure_student_access(p, student_id)
    sets = call_proc(con, "sp_student_application_summary", (student_id,))
    prof = query_df(con, "SELECT internships, projects, workshops_certifications, aptitude_test_score, soft_skills_rating, "
                         "extracurricular_activities, placement_training FROM Student_Academic_Profile WHERE student_id=%s",
                    (student_id,))
    return {"profile": one(sets[0]), "applications": records(sets[1]), "skills": records(sets[2]),
            "academic": one(prof)}


@router.get("/students/{student_id}/matches")
def student_matches(student_id: int, only_eligible: bool = False, top: int = Query(100, ge=1, le=200),
                    p: Principal = Depends(current_user), con=Depends(officer_con)):
    ensure_student_access(p, student_id)
    return records(call_proc(con, "sp_student_matches", (student_id, int(only_eligible), top))[0])


@router.get("/students/{student_id}/skill-gap/{posting_id}")
def skill_gap(student_id: int, posting_id: int, p: Principal = Depends(current_user), con=Depends(officer_con)):
    ensure_student_access(p, student_id)
    ensure_posting_access(con, p, posting_id) if p.role != "ADMIN" else None
    sets = call_proc(con, "sp_skill_gap", (student_id, posting_id))
    gaps = records(sets[0])
    now = (one(sets[1]) or {}).get("stored_match_score") or 0.0
    gain = sum(g["potential_gain"] for g in gaps)
    return {"gaps": gaps, "summary": one(sets[1]), "max_possible": round(min(1.0, now + gain), 4)}


@router.get("/applications/{application_id}/rounds")
def rounds(application_id: int, p: Principal = Depends(current_user), con=Depends(officer_con)):
    head = query_df(con, "SELECT a.student_id, jp.company_id FROM Applications a JOIN Job_Postings jp "
                         "ON jp.posting_id=a.posting_id WHERE a.application_id=%s", (application_id,))
    if head.empty:
        raise HTTPException(404, "Application not found.")
    if p.role == "STUDENT" and p.student_id != int(head.student_id.iloc[0]):
        raise HTTPException(403, "Not your application.")
    if p.role == "RECRUITER" and p.company_id != int(head.company_id.iloc[0]):
        raise HTTPException(403, "Not your company's application.")
    return records(query_df(con, "SELECT round_no, round_type, round_date, result FROM Interview_Rounds "
                                 "WHERE application_id=%s ORDER BY round_no", (application_id,)))
