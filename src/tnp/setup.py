"""Create the database and install the schema, functions, triggers, procedures, views, roles."""
from __future__ import annotations

from .config import SECURITY_FILE, SQL_DIR, SQL_FILES, get_settings
from .db import connect, query_df, run_sql_file


ROLES = ("tnp_admin", "tnp_officer", "ml_service", "readonly_analyst")


def _reset_role_grants(con, db_name: str) -> int:
    """Revoke every grant the four roles still hold on this database.

    MySQL keeps database/table/column privileges after DROP DATABASE, so a rebuilt database
    would silently inherit grants from an older version of 08_security.sql (for example a
    broad SELECT that exposes App_Users). Revoking first makes the security script the only
    source of truth. Grants on other databases are left alone."""
    n = 0
    with con.cursor() as cur:
        for role in ROLES:
            cur.execute("SELECT COUNT(*) FROM mysql.user WHERE user=%s", (role,))
            if not cur.fetchone()[0]:
                continue
            cur.execute(f"SHOW GRANTS FOR `{role}`")
            for (line,) in cur.fetchall():
                if f"`{db_name}`." not in line or not line.startswith("GRANT"):
                    continue
                stmt = "REVOKE" + line[len("GRANT"):]
                head, _, tail = stmt.rpartition(" TO ")
                stmt = head + " FROM " + tail.replace(" WITH GRANT OPTION", "")
                cur.execute(stmt)
                n += 1
    con.commit()
    return n


def setup_database(drop: bool = True, with_security: bool = True) -> None:
    s = get_settings()
    admin = connect("admin", database=False)
    with admin.cursor() as cur:
        if drop:
            cur.execute(f"DROP DATABASE IF EXISTS `{s.db_name}`")
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{s.db_name}` CHARACTER SET utf8mb4")
    admin.commit()
    admin.close()

    con = connect("admin")
    try:
        for name in SQL_FILES:
            n = run_sql_file(con, SQL_DIR / name)
            print(f"  {name:26s} {n:3d} statements")
        if with_security:
            revoked = _reset_role_grants(con, s.db_name)
            if revoked:
                print(f"  revoked {revoked} stale role grants on `{s.db_name}`")
            repl = {
                "DB_NAME": s.db_name,
                "OFFICER_PASSWORD": s.officer_password,
                "ML_PASSWORD": s.ml_password,
                "READONLY_PASSWORD": s.readonly_password,
            }
            n = run_sql_file(con, SQL_DIR / SECURITY_FILE, repl)
            print(f"  {SECURITY_FILE:26s} {n:3d} statements (roles + users)")
        inventory = query_df(
            con,
            """SELECT 'tables' AS object, COUNT(*) AS n FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
               UNION ALL SELECT 'views', COUNT(*) FROM information_schema.views
                WHERE table_schema = DATABASE()
               UNION ALL SELECT 'procedures', COUNT(*) FROM information_schema.routines
                WHERE routine_schema = DATABASE() AND routine_type = 'PROCEDURE'
               UNION ALL SELECT 'functions', COUNT(*) FROM information_schema.routines
                WHERE routine_schema = DATABASE() AND routine_type = 'FUNCTION'
               UNION ALL SELECT 'triggers', COUNT(*) FROM information_schema.triggers
                WHERE trigger_schema = DATABASE()""",
        )
        print("Database `%s` ready: %s" % (
            s.db_name, ", ".join(f"{r.n} {r.object}" for r in inventory.itertuples())))
    finally:
        con.close()
