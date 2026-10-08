"""End-to-end tests of the web API (FastAPI TestClient, real MySQL, real stored procedures)."""
import pytest
from fastapi.testclient import TestClient

from tnp.api.main import app
from tnp.db import query_df


@pytest.fixture(scope="module")
def client(db):
    return TestClient(app)


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r


def H(r):
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def admin(client):
    return H(login(client, "admin", "admin123"))


@pytest.fixture(scope="module")
def student(client, db):
    email = query_df(db, "SELECT email FROM Students WHERE student_id=4740").email[0]
    return H(login(client, email, "student123")), 4740


@pytest.fixture(scope="module")
def recruiter(client, db):
    cid = int(query_df(db, "SELECT company_id FROM Companies ORDER BY company_id LIMIT 1").company_id[0])
    return H(login(client, f"recruiter{cid}", "recruiter123")), cid


# ------------------------------------------------------------------ authentication
def test_login_wrong_password_and_audit(client, db):
    assert login(client, "admin", "wrong").status_code == 401
    assert login(client, "nobody", "x").status_code == 401
    n = query_df(db, "SELECT COUNT(*) n FROM Login_Audit WHERE success=0").n[0]
    assert n >= 2


def test_endpoints_need_a_token(client):
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/overview", headers={"Authorization": "Bearer abc.def"}).status_code == 401


def test_demo_accounts_listed(client):
    accounts = client.get("/api/auth/demo-accounts").json()["accounts"]
    assert [a["username"] for a in accounts][0] == "admin" and len(accounts) == 3


def test_change_password_roundtrip(client, db):
    c = db.cursor()
    c.execute("SELECT email FROM Students WHERE student_id=7001"); email = c.fetchone()[0]
    h = H(login(client, email, "student123"))
    assert client.post("/api/auth/change-password", headers=h, json={"old_password": "nope", "new_password": "longenough1"}).status_code == 400
    assert client.post("/api/auth/change-password", headers=h, json={"old_password": "student123", "new_password": "short"}).status_code == 400
    assert client.post("/api/auth/change-password", headers=h, json={"old_password": "student123", "new_password": "NewPass#2026"}).status_code == 200
    assert login(client, email, "student123").status_code == 401
    assert login(client, email, "NewPass#2026").status_code == 200


# ------------------------------------------------------------------ role boundaries
def test_student_cannot_use_admin_or_other_students(client, student):
    h, sid = student
    assert client.get("/api/overview", headers=h).status_code == 403
    assert client.get("/api/students", headers=h).status_code == 403
    assert client.get("/api/students/1", headers=h).status_code == 403
    assert client.get("/api/postings/73/shortlist", headers=h).status_code == 403
    assert client.get(f"/api/students/{sid}", headers=h).status_code == 200
    assert client.post("/api/assistant/sql", headers=h, json={"sql": "SELECT 1"}).status_code == 403


def test_recruiter_is_limited_to_own_company(client, recruiter, db):
    h, cid = recruiter
    own = int(query_df(db, f"SELECT posting_id FROM Job_Postings WHERE company_id={cid} LIMIT 1").posting_id[0])
    other = int(query_df(db, f"SELECT posting_id FROM Job_Postings WHERE company_id<>{cid} LIMIT 1").posting_id[0])
    assert client.get(f"/api/postings/{own}/shortlist?top=3", headers=h).status_code == 200
    assert client.get(f"/api/postings/{other}/shortlist", headers=h).status_code == 403
    assert client.get("/api/students", headers=h).status_code == 403
    posts = client.get("/api/postings", headers=h).json()
    assert posts and all(p["company_id"] == cid for p in posts)
    filt = client.get("/api/meta/filters", headers=h).json()["postings"]
    assert all(p["posting_id"] in {x["posting_id"] for x in posts} for p in filt)


# ------------------------------------------------------------------ read endpoints
def test_overview_and_lists(client, admin):
    o = client.get("/api/overview?cycle=2026", headers=admin).json()
    assert o["kpis"]["students"] > 3000 and 0 < o["kpis"]["placement_pct"] < 100
    assert {"branch", "ctc_hist", "prob_hist", "top_companies", "featured_posting_id"} <= set(o)
    assert len(client.get("/api/postings?cycle=2026", headers=admin).json()) > 10
    s = client.get("/api/students?q=Dev&size=10", headers=admin).json()
    assert s["total"] > 0 and len(s["rows"]) <= 10
    assert client.get("/api/companies", headers=admin).json()


def test_shortlist_is_sorted_and_not_applied_excludes_applicants(client, admin):
    r = client.get("/api/postings/73/shortlist?top=15", headers=admin).json()
    scores = [x["match_score"] for x in r]
    assert scores == sorted(scores, reverse=True) and len(r) == 15
    fresh = client.get("/api/postings/73/shortlist?top=30&not_applied=true", headers=admin).json()
    pipeline_ids = {x["student_id"] for x in client.get("/api/postings/73/pipeline", headers=admin).json()}
    assert not ({x["student_id"] for x in fresh} & pipeline_ids)


def test_student_360_matches_and_skill_gap(client, student):
    h, sid = student
    d = client.get(f"/api/students/{sid}", headers=h).json()
    assert d["profile"]["student_id"] == sid and d["skills"]
    m = client.get(f"/api/students/{sid}/matches?top=5", headers=h).json()
    assert len(m) == 5 and m[0]["match_score"] >= m[-1]["match_score"]
    g = client.get(f"/api/students/{sid}/skill-gap/{m[0]['posting_id']}", headers=h).json()
    assert g["max_possible"] >= g["summary"]["stored_match_score"]
    assert g["gaps"] == sorted(g["gaps"], key=lambda x: -x["potential_gain"])


def test_early_warning(client, admin):
    r = client.get("/api/early-warning?cycle=2026&threshold=0.2&max_apps=3", headers=admin).json()
    assert r["count"] > 0 and all(x["probability"] < 0.2 and x["applications_count"] <= 3 for x in r["rows"])
    assert sum(r["bands"].values()) == r["count"]


def test_insights_and_health(client, admin):
    assert client.get("/api/insights", headers=admin).json()["runs"]
    cat = client.get("/api/health/catalog", headers=admin).json()
    assert cat["summary"]["TABLE"] == 17 and cat["summary"]["TRIGGER"] == 13 and len(cat["triggers"]) == 13
    integ = client.get("/api/health/integrity", headers=admin).json()
    assert all(c["status"] != "FAIL" for c in integ)
    plan = client.get("/api/health/explain/73", headers=admin).json()["plan"]
    assert plan[0]["key"] == "idx_ms_posting_score"


# ------------------------------------------------------------------ write workflow
def test_apply_round_withdraw_workflow(client, admin, student, db):
    h, sid = student
    pid = int(query_df(db, """SELECT jp.posting_id FROM Job_Postings jp JOIN Students s ON s.student_id=4740
        WHERE fn_cycle_year(jp.posted_date)=s.batch_year AND jp.min_cgpa<=s.cgpa
          AND jp.posting_id NOT IN (SELECT posting_id FROM Applications WHERE student_id=4740) LIMIT 1""").posting_id[0])
    cid = int(query_df(db, f"SELECT company_id FROM Job_Postings WHERE posting_id={pid}").company_id[0])
    rec = H(login(client, f"recruiter{cid}", "recruiter123"))
    aid = None
    try:
        r = client.post("/api/applications", headers=h, json={"student_id": sid, "posting_id": pid})
        assert r.status_code == 409 and "closed" in r.json()["detail"].lower()            # trigger T4
        assert client.post(f"/api/postings/{pid}/status", headers=h, json={"status": "OPEN"}).status_code == 403
        assert client.post(f"/api/postings/{pid}/status", headers=admin, json={"status": "OPEN"}).json()["status"] == "OPEN"
        assert client.post("/api/applications", headers=h, json={"student_id": 1, "posting_id": pid}).status_code == 403
        r = client.post("/api/applications", headers=h, json={"student_id": sid, "posting_id": pid})
        assert r.status_code == 200; aid = r.json()["application_id"]
        assert client.post("/api/applications", headers=h, json={"student_id": sid, "posting_id": pid}).status_code == 409
        r = client.post(f"/api/applications/{aid}/rounds", headers=rec, json={"round_type": "TECHNICAL", "result": "PASS"})
        assert r.json()["new_status"] == "IN_PROGRESS" and r.json()["round_no"] == 1
        other = H(login(client, f"recruiter{cid % 20 + 1}", "recruiter123"))
        assert client.post(f"/api/applications/{aid}/rounds", headers=other, json={"round_type": "HR", "result": "PASS"}).status_code == 403
        assert client.post(f"/api/applications/{aid}/rounds", headers=rec, json={"round_type": "BOGUS", "result": "PASS"}).status_code == 400
        rounds = client.get(f"/api/applications/{aid}/rounds", headers=h).json()
        assert [x["round_type"] for x in rounds] == ["TECHNICAL"]
        assert client.post(f"/api/applications/{aid}/withdraw", headers=h).json()["status"] == "WITHDRAWN"
        assert client.post(f"/api/applications/{aid}/rounds", headers=rec, json={"round_type": "HR", "result": "PASS"}).status_code == 409
        log = client.get("/api/audit/status-log?limit=5", headers=admin).json()
        assert log[0]["new_status"] == "WITHDRAWN"
    finally:
        with db.cursor() as cur:
            if aid:
                cur.execute("DELETE FROM Applications WHERE application_id=%s", (aid,))
            cur.execute("UPDATE Job_Postings SET status='CLOSED' WHERE posting_id=%s", (pid,))
        db.commit()


# ------------------------------------------------------------------ assistant
def test_assistant_answers_and_refuses(client, admin):
    r = client.post("/api/assistant/ask", headers=admin, json={"question": "Top 5 students for posting 73"}).json()
    assert len(r["rows"]) == 5 and "posting_id" not in r["columns"] and "email" not in r["columns"]
    r = client.post("/api/assistant/ask", headers=admin,
                    json={"question": "Students matched above 0.8 for the Amazon SDE posting who haven't applied"}).json()
    assert "Amazon" in r["title"] and all(row[4] >= 0.8 for row in r["rows"])
    assert client.post("/api/assistant/ask", headers=admin, json={"question": "tell me a joke"}).status_code == 400
    ok = client.post("/api/assistant/sql", headers=admin, json={"sql": "SELECT branch, COUNT(*) n FROM Students GROUP BY branch"})
    assert ok.status_code == 200 and len(ok.json()["rows"]) == 4
    for bad in ["DELETE FROM Students", "SELECT 1; DROP TABLE Skills", "SELECT SLEEP(5)", "UPDATE Students SET cgpa=0",
                "SELECT * FROM Students -- x"]:
        assert client.post("/api/assistant/sql", headers=admin, json={"sql": bad}).status_code == 400, bad
    assert client.post("/api/assistant/sql", headers=admin, json={"sql": "SELECT email FROM Students LIMIT 1"}).status_code == 403
    assert client.post("/api/assistant/sql", headers=admin, json={"sql": "SELECT password_hash FROM App_Users"}).status_code == 403


def test_ml_worker_endpoint(client, admin):
    r = client.post("/api/ml/worker", headers=admin)
    assert r.status_code == 200 and {"processed", "rows"} <= set(r.json())


def test_static_site_is_served(client):
    assert "Placement Atlas" in client.get("/").text
    assert client.get("/assets/css/app.css").status_code == 200
    assert client.get("/assets/img/hero.svg").status_code == 200
