import uuid

from services.api.database import SessionLocal
from services.api.models import Job, ScenarioRunPlayback
from services.api.worker import advance_scenario_playbacks, claim_next, execute_job, scenario_frame_timestamps


def completed_water_scenario(login, scenario="normal"):
    admin = login("admin")
    response = admin.post("/api/v1/scenarios", json={
        "domain": "water",
        "scenario": scenario,
        "parameters": {"seed": 1847},
        "idempotency_key": str(uuid.uuid4()),
    })
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    with SessionLocal() as db:
        others = db.query(Job).filter(Job.id != job_id, Job.status == "queued").all()
        for job in others:
            job.status = "paused"
        db.commit()
        assert claim_next(db) == job_id
        db.expire_all()
        token = db.get(Job, job_id).claim_token
        for job in others:
            job.status = "queued"
        db.commit()
    execute_job(job_id, token)
    assert admin.get(f"/api/v1/jobs/{job_id}").json()["status"] == "succeeded"
    return admin, job_id


def control(admin, job_id, state, action, **extra):
    response = admin.post(f"/api/v1/jobs/{job_id}/playback", json={"action": action, "version": state["version"], **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_scenario_clock_uses_unique_actual_branch_timestamps():
    rows = [{"timestamp": "2026-10-15T01:00:00+01:00"}, {"timestamp": "2026-10-15T00:00:00Z"}, {"timestamp": "2026-10-15T02:00:00Z"}]
    result = {"baseline": {"series": rows[:1]}, "series": rows[1:], "metadata": {"clock": "2026-10-15T03:00:00+00:00"}}
    assert scenario_frame_timestamps(result) == ["2026-10-15T00:00:00+00:00", "2026-10-15T02:00:00+00:00"]
    assert scenario_frame_timestamps({"baseline": {}, "series": [], "metadata": {"clock": "2026-10-15T03:00:00Z"}}) == ["2026-10-15T03:00:00+00:00"]
    assert scenario_frame_timestamps({"baseline": {}, "series": [], "metadata": {}}) == []


def test_playback_controls_persist_cursor_reject_stale_state_and_scope_access(login):
    admin, job_id = completed_water_scenario(login)
    state = admin.get(f"/api/v1/jobs/{job_id}/playback").json()
    job = admin.get(f"/api/v1/jobs/{job_id}").json()
    actual = {row["timestamp"] for row in job["result"]["baseline"]["series"] + job["result"]["series"]}
    assert set(state["frame_timestamps"]) == {stamp.replace("Z", "+00:00") for stamp in actual}
    assert state["cursor"] == 0 and state["status"] == "paused" and state["frame_count"] > 2

    citizen = login("citizen")
    assert citizen.get(f"/api/v1/jobs/{job_id}/playback").status_code == 404

    state = control(admin, job_id, state, "step_forward")
    assert (state["cursor"], state["status"]) == (1, "paused")
    stale = admin.post(f"/api/v1/jobs/{job_id}/playback", json={"action": "step_back", "version": 1})
    assert stale.status_code == 409
    state = control(admin, job_id, state, "seek", cursor=state["frame_count"] - 1)
    assert state["cursor"] == state["frame_count"] - 1
    invalid = admin.post(f"/api/v1/jobs/{job_id}/playback", json={"action": "seek", "version": state["version"], "cursor": state["frame_count"]})
    assert invalid.status_code == 422
    state = control(admin, job_id, state, "restart")
    assert state["cursor"] == 0 and state["status"] == "paused"
    state = control(admin, job_id, state, "speed", speed=4)
    assert state["speed"] == 4


def test_worker_advances_due_frames_and_pause_prevents_late_tick(login):
    admin, job_id = completed_water_scenario(login)
    state = admin.get(f"/api/v1/jobs/{job_id}/playback").json()
    state = control(admin, job_id, state, "speed", speed=4)
    state = control(admin, job_id, state, "play")
    assert state["status"] == "playing"
    with SessionLocal() as db:
        playback = db.get(ScenarioRunPlayback, job_id)
        first_due = playback.last_tick_at + .26
    assert advance_scenario_playbacks(first_due) == 1
    advanced = admin.get(f"/api/v1/jobs/{job_id}/playback").json()
    assert advanced["cursor"] == 1 and advanced["version"] == state["version"]

    paused = control(admin, job_id, advanced, "pause")
    assert paused["status"] == "paused" and paused["cursor"] == 1
    with SessionLocal() as db:
        playback = db.get(ScenarioRunPlayback, job_id)
        late_tick = playback.last_tick_at + 10
    assert advance_scenario_playbacks(late_tick) == 0
    assert admin.get(f"/api/v1/jobs/{job_id}/playback").json()["cursor"] == 1

    state = control(admin, job_id, paused, "play")
    while state["status"] == "playing":
        with SessionLocal() as db:
            playback = db.get(ScenarioRunPlayback, job_id)
            due = playback.last_tick_at + .26
        assert advance_scenario_playbacks(due) == 1
        state = admin.get(f"/api/v1/jobs/{job_id}/playback").json()
    assert state["cursor"] == state["frame_count"] - 1
    assert state["status"] == "paused"


def test_recorded_analysis_windows_replay_without_rewriting_case_decisions(login):
    admin, job_id = completed_water_scenario(login, "overnight_leak")
    run = admin.get(f"/api/v1/jobs/{job_id}").json()["result"]
    state = admin.get(f"/api/v1/jobs/{job_id}/playback").json()
    assert state["analysis"]["modified"]["events"] == []
    assert state["analysis"]["modified"]["observations"] == 1
    state = control(admin, job_id, state, "seek", cursor=state["frame_count"] - 1)
    event_ids = {event["id"] for event in state["analysis"]["modified"]["events"]}
    assert event_ids == {finding["id"] for finding in run["findings"]}
    assert state["analysis"]["modified"]["observations"] == len(run["series"])
    assert state["analysis"]["completed"] is True
    case_id = state["analysis"]["modified"]["events"][0]["case_id"]
    case = admin.get(f"/api/v1/cases/{case_id}").json()
    response = admin.post(f"/api/v1/cases/{case_id}/transition", json={
        "status": "investigating", "reason": "Inspect the recorded scenario evidence", "version": case["version"],
    })
    assert response.status_code == 200, response.text
    decided = response.json()
    state = control(admin, job_id, state, "restart")
    assert state["analysis"]["modified"]["events"] == []
    assert state["analysis"]["completed"] is False
    state = control(admin, job_id, state, "seek", cursor=state["frame_count"] - 1)
    replayed = admin.get(f"/api/v1/cases/{case_id}").json()
    assert replayed["status"] == decided["status"] == "investigating"
    assert replayed["version"] == decided["version"]
    assert admin.get(f"/api/v1/jobs/{job_id}").json()["result"] == run
