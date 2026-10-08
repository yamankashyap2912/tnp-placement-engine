"""Shared FastAPI dependencies: authentication, role checks, DB connections, JSON helpers."""
from __future__ import annotations

import datetime as dt
import json
from typing import Callable, Iterator

import pandas as pd
from fastapi import Depends, Header, HTTPException

from ..db import call_proc, connect, query_df
from .security import Principal, read_token


# ----------------------------------------------------------------- JSON helpers
def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (NaN -> null, dates -> ISO strings)."""
    if df is None or df.empty:
        return []
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v)
    return json.loads(df.to_json(orient="records", date_format="iso"))


def one(df: pd.DataFrame) -> dict | None:
    r = records(df.head(1))
    return r[0] if r else None


# ----------------------------------------------------------------- connections
def officer_con() -> Iterator:
    """The web API connects as the least-privilege officer account (procedures + selected writes)."""
    con = connect("officer")
    try:
        yield con
    finally:
        con.close()


def readonly_con() -> Iterator:
    con = connect("readonly")
    try:
        yield con
    finally:
        con.close()


# ----------------------------------------------------------------- authentication
def current_user(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    p = read_token(authorization.split(None, 1)[1])
    if p is None:
        raise HTTPException(401, "Your session has expired. Sign in again.")
    return p


def require(*roles: str) -> Callable[[Principal], Principal]:
    def dep(p: Principal = Depends(current_user)) -> Principal:
        if p.role not in roles:
            raise HTTPException(403, f"This area is for {' / '.join(r.lower() for r in roles)} accounts.")
        return p
    dep.roles = roles
    return dep


def posting_company(con, posting_id: int) -> int:
    row = query_df(con, "SELECT company_id FROM Job_Postings WHERE posting_id=%s", (posting_id,))
    if row.empty:
        raise HTTPException(404, "Posting not found.")
    return int(row.company_id.iloc[0])


def ensure_posting_access(con, p: Principal, posting_id: int) -> None:
    """Admin: any posting. Recruiter: own company only. Student: own placement cycle only."""
    if p.role == "ADMIN":
        return
    if p.role == "RECRUITER":
        if posting_company(con, posting_id) != p.company_id:
            raise HTTPException(403, "This posting belongs to another company.")
        return
    row = query_df(con, "SELECT 1 FROM Job_Postings jp JOIN Students s ON s.student_id=%s "
                        "WHERE jp.posting_id=%s AND fn_cycle_year(jp.posted_date)=s.batch_year",
                   (p.student_id, posting_id))
    if row.empty:
        raise HTTPException(403, "This posting is not part of your placement cycle.")


def ensure_student_access(p: Principal, student_id: int) -> None:
    if p.role == "ADMIN" or (p.role == "STUDENT" and p.student_id == student_id):
        return
    raise HTTPException(403, "You can only open your own profile.")


__all__ = ["records", "one", "officer_con", "readonly_con", "current_user", "require", "call_proc",
           "query_df", "ensure_posting_access", "ensure_student_access", "posting_company"]
