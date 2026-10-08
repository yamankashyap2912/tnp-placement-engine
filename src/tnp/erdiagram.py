"""Generate the ER diagram straight from the live schema (information_schema).

Writes docs/er_diagram.dot and, when Graphviz (`dot`) is installed, docs/er_diagram.png/.svg.
Because it reads the real foreign keys, the diagram can never drift from the database.
"""
from __future__ import annotations

import html
import shutil
import subprocess

from .config import DOCS_DIR
from .db import connect, query_df

ML_TABLES = {"Match_Scores", "Placement_Probability", "Model_Runs"}
OPS_TABLES = {"Application_Status_Log", "Match_Refresh_Queue"}


def generate() -> None:
    con = connect("admin")
    cols = query_df(con, """
        SELECT c.table_name AS t, c.column_name AS col, c.column_type AS typ, c.column_key AS k,
               c.ordinal_position AS pos
          FROM information_schema.columns c
          JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = DATABASE() AND t.table_type = 'BASE TABLE'
         ORDER BY c.table_name, c.ordinal_position""")
    fks = query_df(con, """
        SELECT table_name AS child, referenced_table_name AS parent, column_name AS col
          FROM information_schema.key_column_usage
         WHERE table_schema = DATABASE() AND referenced_table_name IS NOT NULL""")
    fk_cols = {(r.child, r.col) for r in fks.itertuples()}

    lines = ["digraph TnP {", '  rankdir=LR; fontname="Helvetica"; nodesep=0.35; ranksep=1.1;',
             '  node [shape=plaintext fontname="Helvetica" fontsize=10];',
             '  edge [color="#555555" arrowsize=0.7];']
    for t, g in cols.groupby("t", sort=False):
        head = "#cfe8ff"
        if t in ML_TABLES:
            head = "#c9f2d9"
        elif t in OPS_TABLES:
            head = "#ffe9b8"
        elif t == "Student_Academic_Profile":
            head = "#ececec"
        rows = []
        for r in g.itertuples():
            mark = "PK " if r.k == "PRI" else ("FK " if (t, r.col) in fk_cols else "   ")
            bold = "<B>" if r.k == "PRI" else ""
            endb = "</B>" if r.k == "PRI" else ""
            rows.append(f'<TR><TD ALIGN="LEFT" PORT="{r.col}">{bold}{mark}{r.col}{endb}</TD>'
                        f'<TD ALIGN="LEFT"><FONT COLOR="#666666">{html.escape(r.typ)}</FONT></TD></TR>')
        lines.append(f'  {t} [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">'
                     f'<TR><TD COLSPAN="2" BGCOLOR="{head}"><B>{t}</B></TD></TR>{"".join(rows)}</TABLE>>];')
    for r in fks.itertuples():
        lines.append(f"  {r.child} -> {r.parent} [taillabel=\"N\" headlabel=\"1\" fontsize=8];")
    lines.append("}")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dot_path = DOCS_DIR / "er_diagram.dot"
    dot_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {dot_path}  ({cols.t.nunique()} tables, {len(fks)} foreign keys)")
    if shutil.which("dot"):
        for fmt in ("png", "svg"):
            subprocess.run(["dot", f"-T{fmt}", str(dot_path), "-o", str(DOCS_DIR / f"er_diagram.{fmt}")], check=True)
        print("  rendered docs/er_diagram.png and .svg")
    else:
        print("  Graphviz not found: install it (https://graphviz.org) and re-run to get PNG/SVG, "
              "or paste docs/er_diagram.dot into https://dreampuf.github.io/GraphvizOnline")
