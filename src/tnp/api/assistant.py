"""Read-only question answering over the database (project Phase 5, "NL2SQL assistant").

Two safe paths, both executed with the `readonly_analyst` account (no writes, no PII columns):
  * ask()      rule-based natural-language -> parameterised SQL for the questions a TnP officer asks
  * run_select() a guarded SQL console (single SELECT/WITH statement, capped rows and run time)
No external model is used, so the assistant is deterministic, auditable and works offline.
"""
from __future__ import annotations

import re

import pandas as pd

from ..db import query_df

MAX_ROWS = 500
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|replace|call|set|"
                       r"load|outfile|dumpfile|sleep|benchmark|into|handler|lock|unlock|rename|use|do)\b", re.I)

EXAMPLES = [
    "Top 10 students for posting 73",
    "Students matched above 0.8 for the Amazon SDE posting who haven't applied",
    "Show at-risk students in cycle 2026",
    "Placement rate by branch",
    "Average CTC by company tier",
    "Which companies made the most offers?",
    "Which posting has the most applicants?",
    "Students with Python level 4 or above",
    "How many students are placed?",
]


# ------------------------------------------------------------------ guarded SQL console
def run_select(con, sql: str) -> dict:
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise ValueError("Type a SELECT query first.")
    if ";" in text:
        raise ValueError("Only one statement at a time.")
    if "--" in text or "/*" in text or "#" in text:
        raise ValueError("Comments are not allowed in console queries.")
    if not re.match(r"^(select|with)\b", text, re.I):
        raise ValueError("Only SELECT (or WITH ... SELECT) queries are allowed here.")
    bad = FORBIDDEN.search(text)
    if bad:
        raise ValueError(f"'{bad.group(0)}' is not allowed in a read-only query.")
    with con.cursor() as cur:
        cur.execute("SET SESSION MAX_EXECUTION_TIME = 8000")
        cur.execute(text)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    return {"sql": text, "columns": cols, "rows": [list(r) for r in rows[:MAX_ROWS]],
            "truncated": len(rows) > MAX_ROWS}


# ------------------------------------------------------------------ natural language
def _find_posting(con, q: str) -> tuple[int | None, str]:
    m = re.search(r"posting\s*#?\s*(\d+)", q) or re.search(r"#(\d+)", q)
    if m:
        pid = int(m.group(1))
        row = query_df(con, "SELECT c.name, jp.role_title FROM Job_Postings jp JOIN Companies c "
                            "ON c.company_id=jp.company_id WHERE jp.posting_id=%s", (pid,))
        return (pid, f"{row.name[0]} - {row.role_title[0]}") if len(row) else (None, "")
    comp = query_df(con, "SELECT company_id, name FROM Companies")
    ql = q.lower()
    hit = comp[comp.name.str.lower().apply(lambda n: n in ql)]
    if hit.empty:  # first word of the company name ("Tech" would be ambiguous: require >= 4 letters)
        hit = comp[comp.name.str.lower().apply(lambda n: len(n.split()[0]) >= 4 and n.split()[0] in ql)]
    if hit.empty:
        return None, ""
    cid = int(hit.sort_values("name", key=lambda s: s.str.len(), ascending=False).company_id.iloc[0])
    posts = query_df(con, "SELECT jp.posting_id, jp.role_title, c.name, ps.applicants FROM Job_Postings jp "
                          "JOIN Companies c ON c.company_id=jp.company_id "
                          "JOIN v_posting_stats ps ON ps.posting_id=jp.posting_id WHERE jp.company_id=%s", (cid,))
    aliases = {"sde": "software", "swe": "software", "analyst": "analyst", "data": "data", "qa": "test"}
    for key, word in aliases.items():
        if re.search(rf"\b{key}\b", ql):
            sub = posts[posts.role_title.str.lower().str.contains(word)]
            if len(sub):
                posts = sub
                break
    best = posts.sort_values("applicants", ascending=False).iloc[0]
    return int(best.posting_id), f"{best['name']} - {best.role_title}"


def _num(q: str, pattern: str, default: float) -> float:
    m = re.search(pattern, q)
    return float(m.group(1)) if m else default


def ask(con, question: str) -> dict:
    q = question.lower().strip()
    if not q:
        raise ValueError("Ask a question first.")
    cycle = int(_num(q, r"\b(20\d\d)\b", 2026))
    sql = params = title = None

    if re.search(r"(haven'?t|have not|not)\s+applied|not applied|yet to apply", q) or \
            ("above" in q and "match" in q) or re.search(r"top\s+\d+.*posting|shortlist", q):
        pid, label = _find_posting(con, q)
        if pid is None:
            raise ValueError("Name a posting (for example 'posting 73' or 'the Amazon SDE posting').")
        n = int(_num(q, r"top\s+(\d+)", 25))
        if re.search(r"applied", q):
            thr = _num(q, r"(?:above|over|>=?|at least)\s*(0?\.\d+|\d+(?:\.\d+)?)", 0.0)
            sql = ("SELECT s.student_id, s.name, s.branch, s.cgpa, ms.match_score FROM Match_Scores ms "
                   "JOIN Students s ON s.student_id = ms.student_id "
                   "JOIN Job_Postings jp ON jp.posting_id = ms.posting_id "
                   "WHERE ms.posting_id = %s AND ms.match_score >= %s AND s.batch_year = fn_cycle_year(jp.posted_date) "
                   "AND s.cgpa >= jp.min_cgpa AND NOT EXISTS (SELECT 1 FROM Applications a "
                   "WHERE a.student_id = s.student_id AND a.posting_id = ms.posting_id) "
                   "ORDER BY ms.match_score DESC LIMIT %s")
            params = (pid, thr, n)
            title = f"Eligible students with match >= {thr:g} for {label} who have not applied"
        else:
            sql = ("SELECT s.student_id, s.name, s.branch, s.cgpa, ms.match_score FROM Match_Scores ms "
                   "JOIN Students s ON s.student_id = ms.student_id "
                   "JOIN Job_Postings jp ON jp.posting_id = ms.posting_id "
                   "WHERE ms.posting_id = %s AND s.batch_year = fn_cycle_year(jp.posted_date) "
                   "ORDER BY ms.match_score DESC, s.cgpa DESC LIMIT %s")
            params = (pid, n)
            title = f"Top {n} students for {label}"
    elif re.search(r"at[- ]risk|early.?warning|low probability|likely not|unlikely", q):
        br = re.search(r"\b(cse-ai|cse|it|ece)\b", q)
        sql = ("SELECT student_id, name, branch, cgpa, probability, risk_band, applications_count "
               "FROM v_early_warning WHERE batch_year = %s " + ("AND branch = %s " if br else "") +
               "ORDER BY probability LIMIT 50")
        params = (cycle,) + ((br.group(1).upper(),) if br else ())
        title = f"Unplaced students at risk in cycle {cycle}" + (f" ({br.group(1).upper()})" if br else "")
    elif re.search(r"placement (rate|percent)|placed (percent|%)|rate by branch|by branch", q):
        sql = ("SELECT batch_year, branch, students, placed, placement_pct, avg_ctc_lpa "
               "FROM v_branch_placement_summary WHERE (%s = 0 OR batch_year = %s) ORDER BY batch_year, branch")
        params = (cycle if re.search(r"\b20\d\d\b", q) else 0,) * 2
        title = "Placement rate by branch"
    elif re.search(r"(average|avg|mean).*(ctc|package|salary).*(tier)|tier", q):
        sql = ("SELECT c.tier, COUNT(*) AS offers, ROUND(AVG(po.offer_ctc), 2) AS avg_ctc_lpa, MAX(po.offer_ctc) AS max_ctc_lpa "
               "FROM Placement_Outcomes po JOIN Job_Postings jp ON jp.posting_id = po.posting_id "
               "JOIN Companies c ON c.company_id = jp.company_id WHERE po.final_status = 'PLACED' "
               "GROUP BY c.tier ORDER BY c.tier")
        params = ()
        title = "Average CTC by company tier"
    elif re.search(r"most offers|top recruiters?|which compan", q):
        sql = ("SELECT name AS company, tier, postings, applications, offers, offer_rate_pct FROM v_company_summary "
               "ORDER BY offers DESC LIMIT 10")
        params = ()
        title = "Companies with the most offers"
    elif re.search(r"most applicants|most popular|most applied", q):
        sql = ("SELECT posting_id, company, role_title, cycle_year, applicants, selected, selection_rate_pct "
               "FROM v_posting_stats ORDER BY applicants DESC LIMIT 10")
        params = ()
        title = "Postings with the most applicants"
    elif re.search(r"highest (ctc|package|salary)|top (ctc|package)", q):
        sql = ("SELECT s.name, s.branch, s.cgpa, po.offer_ctc, c.name AS company FROM Placement_Outcomes po "
               "JOIN Students s ON s.student_id = po.student_id JOIN Job_Postings jp ON jp.posting_id = po.posting_id "
               "JOIN Companies c ON c.company_id = jp.company_id WHERE po.final_status = 'PLACED' "
               "ORDER BY po.offer_ctc DESC LIMIT 10")
        params = ()
        title = "Highest offers"
    elif re.search(r"how many.*(placed|students)|number of (placed|students)", q):
        sql = ("SELECT s.batch_year, COUNT(*) AS students, SUM(po.final_status = 'PLACED') AS placed "
               "FROM Students s JOIN Placement_Outcomes po ON po.student_id = s.student_id "
               "GROUP BY s.batch_year ORDER BY s.batch_year")
        params = ()
        title = "Students and placements by batch"
    else:
        skills = query_df(con, "SELECT skill_id, skill_name FROM Skills")
        hit = skills[skills.skill_name.str.lower().apply(lambda n: re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", q) is not None)]
        if len(hit) and re.search(r"skill|with|know|level|proficien", q):
            sk = hit.sort_values("skill_name", key=lambda s: s.str.len(), ascending=False).iloc[0]
            lvl = int(_num(q, r"level\s*(\d)", 4))
            sql = ("SELECT s.student_id, s.name, s.branch, s.cgpa, ss.proficiency_level, ss.evidence_source "
                   "FROM Student_Skills ss JOIN Students s ON s.student_id = ss.student_id "
                   "WHERE ss.skill_id = %s AND ss.proficiency_level >= %s ORDER BY ss.proficiency_level DESC, s.cgpa DESC LIMIT 50")
            params = (int(sk.skill_id), lvl)
            title = f"Students with {sk.skill_name} at level {lvl} or above"
    if sql is None:
        raise ValueError("I could not map that question to a query. Try one of the examples, or use the SQL console.")
    with con.cursor() as cur:
        cur.execute("SET SESSION MAX_EXECUTION_TIME = 8000")
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchmany(MAX_ROWS)]
    shown = sql % tuple(repr(p) for p in params) if params else sql
    return {"title": title, "sql": shown, "columns": cols, "rows": rows, "truncated": False}
