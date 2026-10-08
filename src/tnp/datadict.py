"""Generate docs/DATA_DICTIONARY.md from the live schema (never drifts from the database)."""
from __future__ import annotations

from .config import DOCS_DIR
from .db import connect, query_df


def generate() -> None:
    con = connect("admin")
    tables = query_df(con, """SELECT table_name AS t, table_comment AS c, table_rows AS approx_rows
                                FROM information_schema.tables
                               WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
                               ORDER BY table_name""")
    cols = query_df(con, """SELECT table_name AS t, column_name AS col, column_type AS typ,
                                   is_nullable AS nul, column_key AS k, column_default AS dflt,
                                   column_comment AS cmt, extra AS extra
                              FROM information_schema.columns WHERE table_schema = DATABASE()
                             ORDER BY table_name, ordinal_position""")
    fks = query_df(con, """SELECT k.table_name AS t, k.column_name AS col,
                                  CONCAT(k.referenced_table_name, '.', k.referenced_column_name) AS ref,
                                  r.delete_rule AS on_delete
                             FROM information_schema.key_column_usage k
                             JOIN information_schema.referential_constraints r
                               ON r.constraint_schema = k.table_schema AND r.constraint_name = k.constraint_name
                            WHERE k.table_schema = DATABASE() AND k.referenced_table_name IS NOT NULL""")
    checks = query_df(con, """SELECT tc.table_name AS t, cc.constraint_name AS name, cc.check_clause AS clause
                                FROM information_schema.check_constraints cc
                                JOIN information_schema.table_constraints tc
                                  ON tc.constraint_schema = cc.constraint_schema
                                 AND tc.constraint_name = cc.constraint_name
                               WHERE cc.constraint_schema = DATABASE() ORDER BY tc.table_name, cc.constraint_name""")
    idx = query_df(con, """SELECT table_name AS t, index_name AS i, non_unique AS nu,
                                  GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols
                             FROM information_schema.statistics WHERE table_schema = DATABASE()
                            GROUP BY table_name, index_name, non_unique ORDER BY table_name, index_name""")
    fk = {(r.t, r.col): f"{r.ref} (ON DELETE {r.on_delete})" for r in fks.itertuples()}
    out = ["# Data dictionary", "",
           "_Generated from the live database by `python run.py data-dictionary`._", ""]
    for t in tables.itertuples():
        out += [f"## {t.t}", "", f"{t.c}", "",
                "| column | type | null | key | default | notes |", "|---|---|---|---|---|---|"]
        for c in cols[cols.t == t.t].itertuples():
            key = {"PRI": "PK", "UNI": "UNIQUE", "MUL": "index"}.get(c.k, "")
            note = "; ".join(x for x in [c.cmt, fk.get((t.t, c.col), "") and "FK -> " + fk[(t.t, c.col)],
                                         c.extra.replace("DEFAULT_GENERATED", "")] if x)
            out.append(f"| {c.col} | `{c.typ}` | {c.nul} | {key} | {'' if c.dflt is None or c.dflt != c.dflt else c.dflt} | {note} |")
        ck = checks[checks.t == t.t]
        if len(ck):
            out += ["", "**CHECK constraints**", ""] + [f"- `{r.name}`: `{r.clause}`" for r in ck.itertuples()]
        ix = idx[idx.t == t.t]
        out += ["", "**Indexes**", ""] + [
            f"- `{r.i}` ({'unique' if not r.nu else 'non-unique'}): {r.cols}" for r in ix.itertuples()]
        out.append("")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "DATA_DICTIONARY.md").write_text("\n".join(out), encoding="utf-8")
    print(f"  wrote docs/DATA_DICTIONARY.md ({len(tables)} tables)")
