import time
import uuid

from services.api.database import SessionLocal
from services.api.models import Audit, Case, DemoSession, Evidence, Job, Reading, ScenarioRunPlayback, Session
from services.api.security import COOKIE_NAME, DEMO_COOKIE_NAME, token_hash


def session_id(client):
    raw = client.cookies.get(COOKIE_NAME)
    with SessionLocal() as db:
        return db.get(Session, token_hash(raw)).demo_session_id


def test_demo_cookie_survives_role_switch_and_separates_browser_profiles(login):
    browser = login("operator")
    demo_cookie = browser.cookies.get(DEMO_COOKIE_NAME)
    first_id = session_id(browser)
    assert demo_cookie and token_hash(demo_cookie) == first_id

    signed_out = browser.post("/api/v1/auth/logout")
    assert signed_out.status_code == 200
    assert browser.cookies.get(DEMO_COOKIE_NAME) == demo_cookie
    switched = browser.post("/api/v1/auth/login", json={"email": "inspector@civicsignal.local", "password": "CivicDemo!2026"})
    assert switched.status_code == 200
    browser.headers["X-CSRF-Token"] = switched.json()["csrf_token"]
    assert browser.get("/api/v1/auth/me").json()["user"]["role"] == "inspector"
    assert session_id(browser) == first_id

    another_browser = login("admin")
    other_id = session_id(another_browser)
    assert other_id != first_id
    with SessionLocal() as db:
        assert db.get(DemoSession, first_id) is not None
        assert db.get(DemoSession, other_id) is not None


def test_scenario_jobs_cases_admin_lists_and_reset_are_browser_isolated(login):
    first = login("admin")
    second = login("admin")
    first_session, second_session = session_id(first), session_id(second)
    assert first_session != second_session
    first_job_id, second_job_id, queued_job_id = (str(uuid.uuid4()) for _ in range(3))
    first_case_id, second_case_id, preserved_case_id = (str(uuid.uuid4()) for _ in range(3))
    with SessionLocal() as db:
        for job_id, demo_session_id, status in (
            (first_job_id, first_session, "succeeded"),
            (second_job_id, second_session, "succeeded"),
            (queued_job_id, second_session, "queued"),
        ):
            db.add(Job(
                id=job_id, user_id="demo-admin", kind="scenario", demo_session_id=demo_session_id,
                parameters={"domain": "water", "scenario": "overnight_excess"},
                dedupe_key="session-test:" + job_id, status=status,
                result={"case_ids": [second_case_id]} if status == "succeeded" else None,
            ))
        for case_id, job_id, demo_session_id, title in (
            (first_case_id, first_job_id, first_session, "Other browser synthetic case"),
            (second_case_id, second_job_id, second_session, "Resettable synthetic case"),
            (preserved_case_id, second_job_id, second_session, "Synthetic case with human evidence"),
        ):
            db.add(Case(
                id=case_id, event_key=f"scenario:{job_id}:{case_id}", title=title,
                domain="water", zone_id="river", severity="medium", summary="Test-only scenario record",
                provenance="Simulated", priority=50, demo_owner_id="demo-admin", demo_session_id=demo_session_id,
            ))
        db.add(Evidence(case_id=preserved_case_id, actor_id="demo-admin", kind="inspection", notes="Preserve human evidence across reset."))
        db.add(ScenarioRunPlayback(job_id=second_job_id, frame_timestamps=["2026-10-15T00:00:00+00:00"], cursor=0, status="playing", speed=1., last_tick_at=time.time(), version=3))
        reading_count = db.query(Reading).count()
        db.commit()

    assert second.get("/api/v1/jobs/" + first_job_id).status_code == 404
    assert second.get("/api/v1/cases/" + first_case_id).status_code == 403
    second_cases = {case["id"] for case in second.get("/api/v1/cases").json()}
    assert first_case_id not in second_cases
    assert second_case_id in second_cases
    first_admin = first.get("/api/v1/admin").json()
    second_admin = second.get("/api/v1/admin").json()
    assert first_job_id in {job["id"] for job in first_admin["jobs"]}
    assert first_job_id not in {job["id"] for job in second_admin["jobs"]}

    reset = second.post("/api/v1/demo-session/reset")
    assert reset.status_code == 200, reset.text
    payload = reset.json()
    assert payload["scenario_jobs"] == 2
    assert payload["cleared_scenario_results"] == 2
    assert payload["closed_cases"] == [second_case_id]
    assert payload["preserved_cases"] == [preserved_case_id]
    assert "uploaded readings" in payload["note"]

    with SessionLocal() as db:
        first_job, second_job, queued_job = (db.get(Job, job_id) for job_id in (first_job_id, second_job_id, queued_job_id))
        assert first_job.status == "succeeded" and first_job.result == {"case_ids": [second_case_id]}
        assert second_job.status == queued_job.status == "reset"
        assert second_job.result is None and queued_job.result is None
        assert db.get(Case, first_case_id).status == "needs_review"
        assert db.get(Case, second_case_id).status == "closed"
        assert db.get(Case, preserved_case_id).status == "needs_review"
        assert db.query(Evidence).filter_by(case_id=preserved_case_id).count() == 1
        assert db.query(ScenarioRunPlayback).filter_by(job_id=second_job_id).one().status == "paused"
        assert db.query(Audit).filter_by(action="demo_session_reset", case_id=None, demo_session_id=second_session).count() == 1
        assert db.query(Audit).filter(Audit.action == "demo_session_reset", Audit.case_id.in_([second_case_id, preserved_case_id])).count() == 1
        assert db.query(Reading).count() == reading_count

    assert first.get("/api/v1/jobs/" + first_job_id).json()["status"] == "succeeded"
    assert first.get("/api/v1/cases/" + first_case_id).status_code == 200
    assert second.get("/api/v1/jobs/" + first_job_id).status_code == 404


def test_reset_refuses_to_race_a_running_scenario(login):
    admin = login("admin")
    demo_session_id = session_id(admin)
    running_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Job(id=running_id, user_id="demo-admin", kind="scenario", demo_session_id=demo_session_id, parameters={"domain": "water"}, dedupe_key="running-reset:" + running_id, status="running", claim_token="test-token", lease_until=time.time() + 60))
        db.commit()
    response = admin.post("/api/v1/demo-session/reset")
    assert response.status_code == 409
    assert "still calculating" in response.json()["detail"]
    with SessionLocal() as db:
        job = db.get(Job, running_id)
        assert job.status == "running" and job.claim_token == "test-token"


def test_worker_tags_scenario_findings_with_the_creating_demo_session(login, monkeypatch):
    from services.analytics import pipeline
    from services.api.worker import execute_job

    admin = login("admin")
    demo_session_id = session_id(admin)
    response = admin.post("/api/v1/scenarios", json={"domain": "water", "scenario": "session-isolation", "idempotency_key": str(uuid.uuid4())})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    finding_id = str(uuid.uuid4())
    monkeypatch.setattr(pipeline, "run_scenario", lambda *args, **kwargs: {
        "findings": [{"id": finding_id, "domain": "water", "zone_id": "river", "severity": "medium", "title": "Session-scoped synthetic finding", "evidence": {"reason_codes": ["test"]}}],
        "series": [], "baseline": {"series": []}, "metadata": {"clock": "2026-10-15T00:00:00Z"},
    })
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.demo_session_id == demo_session_id
        token = str(uuid.uuid4())
        job.status, job.claim_token, job.lease_until = "running", token, time.time() + 600
        db.commit()
    execute_job(job_id, token)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        case = db.query(Case).filter_by(event_key=f"scenario:{job_id}:{finding_id}").one()
        assert job.status == "succeeded"
        assert case.demo_session_id == job.demo_session_id == demo_session_id
        case_id = case.id
    assert admin.get("/api/v1/cases/" + case_id).status_code == 200
