"""Create the demo accounts (one admin, one recruiter per company, one account per student).

All accounts of a group start with the same demo password. They share one salt+hash so seeding
7,225 students takes milliseconds instead of minutes; the first password change gives the user
their own fresh salt (see /api/auth/change-password). Change the defaults in .env for any real use.
"""
from __future__ import annotations

import os

from .api.security import hash_password

DEMO = {
    "admin": ("admin", os.environ.get("TNP_DEMO_ADMIN_PASSWORD", "admin123")),
    "recruiter": ("recruiter<company_id>", os.environ.get("TNP_DEMO_RECRUITER_PASSWORD", "recruiter123")),
    "student": ("<student email>", os.environ.get("TNP_DEMO_STUDENT_PASSWORD", "student123")),
}


def seed_users(con) -> dict:
    h_admin = hash_password(DEMO["admin"][1])
    h_rec = hash_password(DEMO["recruiter"][1])
    h_stu = hash_password(DEMO["student"][1])
    with con.cursor() as cur:
        cur.execute("DELETE FROM App_Users")
        cur.execute("INSERT INTO App_Users (username, password_hash, role, display_name) "
                    "VALUES ('admin', %s, 'ADMIN', 'TnP Officer')", (h_admin,))
        cur.execute("SELECT company_id, name FROM Companies ORDER BY company_id")
        recs = [(f"recruiter{cid}", h_rec, "RECRUITER", f"{name} Recruitment", cid) for cid, name in cur.fetchall()]
        cur.executemany("INSERT INTO App_Users (username, password_hash, role, display_name, company_id) "
                        "VALUES (%s,%s,%s,%s,%s)", recs)
        cur.execute("SELECT student_id, email, name FROM Students ORDER BY student_id")
        studs = [(email, h_stu, "STUDENT", name, sid) for sid, email, name in cur.fetchall()]
        for i in range(0, len(studs), 5000):
            cur.executemany("INSERT INTO App_Users (username, password_hash, role, display_name, student_id) "
                            "VALUES (%s,%s,%s,%s,%s)", studs[i:i + 5000])
    con.commit()
    return {"admin": 1, "recruiters": len(recs), "students": len(studs)}
