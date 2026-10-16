"""Separate durable queue worker: python -m services.api.worker.

Leased compare-and-swap claims prevent concurrent processing. Expired jobs are
reclaimed after restart; deterministic event keys prevent duplicate cases.
"""
import argparse
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import or_, update
from .database import SessionLocal, init_db
from .domain import create_finding_case, notify_overdue
from .models import Configuration, Job, ModelRun, Reading, ScenarioRunPlayback, User, Zone, now, uid
from .priorities import DEFAULT_CASE_PRIORITY_WEIGHTS
from .security import DEMO_MODE

logger = logging.getLogger("civicsignal.worker")
LEASE_SECONDS = 600


def claim_next(db):
    clock = time.time()
    # A process crash consumes an attempt; exhausted expired leases become failed.
    db.execute(update(Job).where(Job.status == 'pausing', Job.lease_until < clock).values(status='paused', claim_token=None, lease_until=None, control_version=Job.control_version+1, updated_at=now(), attempts=Job.attempts-1))
    db.execute(update(Job).where(Job.status == "running", Job.lease_until < clock, Job.attempts >= Job.max_attempts).values(status="failed", claim_token=None, control_version=Job.control_version+1, error="Worker lease expired after maximum retries.", updated_at=now()))
    candidates = db.query(Job).filter(or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < clock)), Job.attempts < Job.max_attempts).order_by(Job.created_at).limit(10).all()
    for job in candidates:
        claim = db.execute(update(Job).where(Job.id == job.id, Job.status == job.status, Job.attempts == job.attempts, Job.claim_token == job.claim_token).values(status="running", attempts=job.attempts + 1, lease_until=clock + LEASE_SECONDS, claim_token=uid(), control_version=Job.control_version+1, error=None, updated_at=now()), execution_options={"synchronize_session": False})
        if claim.rowcount == 1:
            ident = job.id
            db.commit()
            return ident
    db.commit()
    return None


def publication_gate(db, job, token, output=None):
    """Lock the claimed row, then acknowledge pause or allow atomic publication."""
    locked = db.execute(update(Job).where(Job.id == job.id, Job.claim_token == token, Job.status.in_(['running', 'pausing'])).values(updated_at=now()), execution_options={'synchronize_session': False})
    if locked.rowcount != 1:
        db.rollback()
        return False
    db.refresh(job)
    if job.status == 'pausing':
        job.status = 'paused'
        job.checkpoint = output if output is not None else job.checkpoint
        job.claim_token = job.lease_until = None
        job.control_version += 1
        job.attempts = max(0, job.attempts-1)
        db.commit()
        return False
    return True


def configured_scenario_parameters(db, domain, parameters):
    """Freeze the currently audited domain settings into a scenario run."""
    result = dict(parameters or {})
    config = db.get(Configuration, "platform")
    if config:
        config_value = config.value if isinstance(config.value, dict) else {}
        result.setdefault("case_priority_weights", config_value.get("case_priority_weights", DEFAULT_CASE_PRIORITY_WEIGHTS))
        result.setdefault("case_priority_weights_version", getattr(config, "version", 1))
        if domain == "streetlights":
            result.setdefault("on_hour", config_value.get("streetlight_on_hour", 18))
            result.setdefault("off_hour", config_value.get("streetlight_off_hour", 6))
        elif domain == "roads":
            from services.analytics.pipeline import ROAD_PRIORITY_WEIGHTS
            result.setdefault("priority_weights", config_value.get("road_priority_weights", ROAD_PRIORITY_WEIGHTS))
            result.setdefault("priority_weights_version", config.version)
    return result


def scenario_frame_timestamps(result):
    """Freeze the actual timestamps emitted by the computed scenario branches."""
    timestamps = set()
    for rows in (result.get("baseline", {}).get("series", []), result.get("series", [])):
        for row in rows if isinstance(rows, list) else []:
            raw = row.get("timestamp") if isinstance(row, dict) else None
            if not isinstance(raw, str):
                continue
            try:
                stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if stamp.tzinfo is not None:
                    timestamps.add(stamp.astimezone(timezone.utc).isoformat())
            except ValueError:
                continue
    if not timestamps:
        clock = result.get("metadata", {}).get("clock")
        if isinstance(clock, str):
            try:
                stamp = datetime.fromisoformat(clock.replace("Z", "+00:00"))
                if stamp.tzinfo is not None:
                    timestamps.add(stamp.astimezone(timezone.utc).isoformat())
            except ValueError:
                pass
    return sorted(timestamps)


def advance_scenario_playbacks(now_seconds=None):
    """Advance each due, persisted scenario clock by exactly one stored frame."""
    clock = time.time() if now_seconds is None else float(now_seconds)
    advanced = 0
    with SessionLocal() as db:
        active = db.query(ScenarioRunPlayback).filter_by(status="playing").all()
        for playback in active:
            stamps = playback.frame_timestamps or []
            last = len(stamps) - 1
            if last <= playback.cursor:
                db.execute(update(ScenarioRunPlayback).where(
                    ScenarioRunPlayback.job_id == playback.job_id,
                    ScenarioRunPlayback.status == "playing",
                    ScenarioRunPlayback.version == playback.version,
                    ScenarioRunPlayback.cursor == playback.cursor,
                ).values(status="paused", last_tick_at=clock, updated_at=now()), execution_options={"synchronize_session": False})
                continue
            interval = 1. / max(.5, min(4., float(playback.speed)))
            if playback.last_tick_at is not None and clock - playback.last_tick_at < interval:
                continue
            cursor = min(last, playback.cursor + 1)
            status = "paused" if cursor == last else "playing"
            changed = db.execute(update(ScenarioRunPlayback).where(
                ScenarioRunPlayback.job_id == playback.job_id,
                ScenarioRunPlayback.status == "playing",
                ScenarioRunPlayback.version == playback.version,
                ScenarioRunPlayback.cursor == playback.cursor,
            ).values(cursor=cursor, status=status, last_tick_at=clock, updated_at=now()), execution_options={"synchronize_session": False})
            advanced += changed.rowcount == 1
        db.commit()
    return advanced


def scenario_playback_active():
    with SessionLocal() as db:
        return db.query(ScenarioRunPlayback.job_id).filter_by(status="playing").first() is not None


def execute_job(job_id, expected_token=None):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status not in {'running', 'pausing'} or (expected_token is not None and job.claim_token != expected_token):
            return
        token = job.claim_token
        user = db.get(User, job.user_id)
        domain = job.parameters.get("domain", "water")
        try:
            if not user or not user.active or user.role not in {"admin", "operator"} or (user.role != "admin" and domain not in user.domains):
                raise ValueError("Job authorization was revoked.")
            if user.role != "admin" and not {z.id for z in db.query(Zone).all()}.issubset(set(user.zones)):
                raise ValueError("Job zone authorization was revoked.")
            if job.kind == "scenario":
                if not DEMO_MODE:
                    raise ValueError("Scenario execution is disabled outside demo mode.")
                from services.analytics.pipeline import run_scenario
                if job.status == 'pausing':
                    publication_gate(db, job, token)
                    return
                scenario_parameters = configured_scenario_parameters(db, domain, job.parameters.get("parameters", {}))
                output = job.checkpoint or run_scenario(domain, job.parameters.get("scenario", "normal"), scenario_parameters)
                if not publication_gate(db, job, token, output):
                    return
                case_ids = []
                for finding in output.get("findings", []):
                    case = create_finding_case(db, {**finding, "domain": domain}, provenance="Simulated", prefix=f"scenario:{job.id}:", demo_owner_id=user.id, demo_session_id=job.demo_session_id, priority_weights=scenario_parameters.get("case_priority_weights"), priority_version=scenario_parameters.get("case_priority_weights_version"))
                    case_ids.append(case.id)
                output["case_ids"] = case_ids
                output["scope"] = "Isolated scenario: baseline readings and analytical snapshots remain unchanged."
            elif job.kind == "analysis":
                if domain not in {"water", "electricity"}:
                    raise ValueError("Persisted interval reruns support water and electricity; use domain scenario analysis for other modules.")
                from .baselines import analyze_version, checksum, registered_meters, stored_readings
                from .models import BaselineDeployment, BaselineVersion
                deployment = db.get(BaselineDeployment, domain)
                baseline = db.get(BaselineVersion, deployment.active_id) if deployment and deployment.active_id else None
                if not baseline:
                    raise ValueError('Evaluate and promote a baseline before running analysis.')
                data = stored_readings(db, domain)
                config = db.get(Configuration, "platform")
                tariff = (config.value if config else {}).get("water_tariff_per_m3" if domain == "water" else "electricity_tariff_per_kwh")
                config_value = config.value if config else {}
                case_priority_weights = config_value.get("case_priority_weights", DEFAULT_CASE_PRIORITY_WEIGHTS)
                case_priority_version = config.version if config else 1
                output = analyze_version(domain, data, baseline, tariff=tariff, expected_assets=registered_meters(db, domain), voltage_lower_v=config_value.get("voltage_lower_v", 207), voltage_upper_v=config_value.get("voltage_upper_v", 253))
                held_version = deployment.version
                current = db.execute(update(BaselineDeployment).where(BaselineDeployment.domain == domain, BaselineDeployment.version == held_version).values(version=held_version), execution_options={'synchronize_session': False})
                if current.rowcount != 1:
                    raise ValueError('The active baseline changed during analysis; retry with the new version.')
                output.pop('_rows', None)
                output['dataset_id'] = checksum(data)
                db.add(ModelRun(domain=domain, dataset_id=output['dataset_id'], model_version=baseline.id, output=output))
                for finding in output.get("findings", []):
                    create_finding_case(db, {**finding, "domain": domain}, provenance="Derived", priority_weights=case_priority_weights, priority_version=case_priority_version)
            elif job.kind == 'baseline_candidate':
                from .baselines import evaluate_candidate
                output = evaluate_candidate(db, job.parameters['baseline_id'])
            else:
                raise ValueError("Unsupported durable job kind.")
            if job.kind != 'scenario' and not publication_gate(db, job, token):
                return
            if job.kind == "scenario" and db.get(ScenarioRunPlayback, job_id) is None:
                db.add(ScenarioRunPlayback(job_id=job_id, frame_timestamps=scenario_frame_timestamps(output), cursor=0, status="paused", speed=1., version=1, updated_at=now()))
            job.result, job.status, job.error, job.updated_at, job.lease_until = output, "succeeded", None, now(), None
            job.checkpoint = job.claim_token = None
            job.control_version += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(Job, job_id)
            locked = db.execute(update(Job).where(Job.id == job_id, Job.claim_token == token, Job.status.in_(['running', 'pausing'])).values(updated_at=now()), execution_options={'synchronize_session': False})
            if locked.rowcount != 1:
                db.rollback()
                return
            db.refresh(job)
            job.error = f"{type(exc).__name__}: analytics could not complete. Review parameters and server logs."
            job.status = "failed" if job.attempts >= job.max_attempts else ('paused' if job.status == 'pausing' else 'queued')
            job.claim_token = None
            job.control_version += 1
            job.updated_at, job.lease_until = now(), None
            db.commit()
            logger.exception("Job %s failed on attempt %s", job.id, job.attempts)


def process_once():
    advanced = advance_scenario_playbacks()
    with SessionLocal() as db:
        notify_overdue(db)
        ident = claim_next(db)
        token = db.get(Job, ident).claim_token if ident else None
    if ident:
        execute_job(ident, token)
        return True
    return advanced > 0


def main():
    parser = argparse.ArgumentParser(description="CivicSignal 360 durable analytics worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    init_db()
    from .seed import seed_database
    with SessionLocal() as db:
        seed_database(db)
    while True:
        handled = process_once()
        if args.once:
            break
        if not handled:
            time.sleep(.25 if scenario_playback_active() else 1)


if __name__ == "__main__":
    main()
