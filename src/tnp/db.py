"""MySQL helpers: connections, SQL-script runner (with DELIMITER support), DataFrames."""
from __future__ import annotations

import decimal
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
import pymysql

from .config import get_settings


def connect(role: str = "admin", database: bool = True, autocommit: bool = False):
    """Open a pymysql connection for one of the roles: admin | ml | officer | readonly.

    The ML steps connect as `ml` (least privilege: it can only write the ML output
    tables). If you skipped the security script, point TNP_ML_USER at the admin user.
    """
    s = get_settings()
    user, password = s.credentials(role)
    kwargs: dict[str, Any] = dict(
        user=user, password=password, charset="utf8mb4", autocommit=autocommit
    )
    if database:
        kwargs["database"] = s.db_name
    if s.socket:
        kwargs["unix_socket"] = s.socket
    else:
        kwargs["host"], kwargs["port"] = s.host, s.port
    try:
        return pymysql.connect(**kwargs)
    except pymysql.err.OperationalError as exc:
        raise SystemExit(
            f"Could not connect to MySQL as role '{role}' (user '{user}'): {exc}\n"
            "Check .env (TNP_* variables). For the ml/officer/readonly roles run "
            "`python run.py setup-db` first (it creates them)."
        ) from exc


@contextmanager
def transaction(con):
    """Commit on success, roll back on any exception."""
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def query_df(con, sql: str, params: Sequence | dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame (Decimal columns become float)."""
    with con.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(list(rows), columns=cols)
    for c in df.columns:
        if df[c].dtype == object:
            non_null = df[c].dropna()
            if len(non_null) and isinstance(non_null.iloc[0], decimal.Decimal):
                df[c] = df[c].astype(float)
    return df


def call_proc(con, name: str, args: Iterable = ()) -> list[pd.DataFrame]:
    """CALL a stored procedure and return every result set as a DataFrame."""
    args = list(args)
    placeholders = ",".join(["%s"] * len(args))
    frames: list[pd.DataFrame] = []
    with con.cursor() as cur:
        cur.execute(f"CALL {name}({placeholders})", args)
        while True:
            if cur.description:
                cols = [d[0] for d in cur.description]
                df = pd.DataFrame(list(cur.fetchall()), columns=cols)
                for c in df.columns:
                    if df[c].dtype == object:
                        nn = df[c].dropna()
                        if len(nn) and isinstance(nn.iloc[0], decimal.Decimal):
                            df[c] = df[c].astype(float)
                frames.append(df)
            if not cur.nextset():
                break
    con.commit()
    return frames


# ----------------------------------------------------------------------------
# SQL script runner. The mysql client understands DELIMITER; pymysql does not,
# so we split the script ourselves.
# ----------------------------------------------------------------------------
def split_sql(text: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    delim = ";"
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not buf:
            if not stripped or stripped.startswith("--"):
                continue
            if stripped.upper().startswith("DELIMITER"):
                delim = stripped.split(None, 1)[1].strip()
                continue
        elif stripped.startswith("--"):
            continue  # full-line comment inside a statement
        buf.append(line)
        if stripped.endswith(delim):
            stmt = "\n".join(buf).rstrip()
            stmt = stmt[: -len(delim)].rstrip()
            if stmt.strip():
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def run_sql_file(con, path: Path, replacements: dict[str, str] | None = None) -> int:
    """Execute every statement of a .sql file. Returns the statement count."""
    text = Path(path).read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        text = text.replace("{{" + key + "}}", value)
    statements = split_sql(text)
    with con.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    con.commit()
    return len(statements)


def to_json(obj: Any) -> str:
    """JSON-encode params/metrics for the Model_Runs table (numpy-safe)."""

    def default(o):
        if hasattr(o, "item"):
            return o.item()
        if hasattr(o, "tolist"):
            return o.tolist()
        return str(o)

    return json.dumps(obj, default=default)
