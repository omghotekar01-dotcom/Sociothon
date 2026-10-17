"""CivicSignal 360 versioned REST API; cookie session and CSRF protected."""
import csv
import hashlib
import io
import json
import logging
import math
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from .database import DATA_DIR, ROOT, SessionLocal, get_db, init_db
from .domain import audit, case_access, create_finding_case, full_case, mutate_case, notify, notify_case, serialize_case, serialize_row, transition, visible_cases
from .models import Asset, Association, Audit, Case, CaseInspector, Configuration, Evidence, Job, ModelRun, Notification, Reading, Report, ScenarioRunPlayback, Session, Upload, User, Zone, now, uid
from .priorities import DEFAULT_CASE_PRIORITY_WEIGHTS, case_priority_snapshot, validate_case_priority_weights
from .security import COOKIE_NAME, DEMO_MODE, DOMAINS, SECURE_COOKIES, can_case, current_user, ensure_demo_session, hash_password, in_scope, public_user, rate_limit, require_admin, require_staff, token_hash, verify_password
from .seed import seed_database

logger = logging.getLogger("civicsignal.api")
DOMAIN = Literal["water", "electricity", "roads", "drainage", "waste", "streetlights", "general"]


@asynccontextmanager
async def lifespan(app):
    init_db()
    with SessionLocal() as db:
        seed_database(db)
    yield


app = FastAPI(title="CivicSignal 360", version="1.0.0", description="Independent hackathon prototype — not affiliated with an official government authority.", lifespan=lifespan)
from .admin_registry import router as registry_router
app.include_router(registry_router)
from .baselines import router as baseline_router
app.include_router(baseline_router)
from .water_operations import router as water_operations_router
app.include_router(water_operations_router)
from .staff_accounts import router as staff_accounts_router
app.include_router(staff_accounts_router)
from .ai_investigator import router as ai_investigator_router
app.include_router(ai_investigator_router)


@app.middleware("http")
async def response_headers(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = secrets.token_hex(8)
    logger.info(json.dumps({"method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}))
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse(status_code=409, content={"detail": "This record conflicts with an existing record. Refresh and retry."})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1] or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address.")
        return value


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=10, max_length=256)


def start_session(db, user, request, response):
    raw, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    demo_session_id = ensure_demo_session(request, response, db)
    db.add(Session(token_hash=token_hash(raw), user_id=user.id, csrf=csrf, expires_at=time.time() + 8 * 3600, demo_session_id=demo_session_id))
    db.commit()
    response.set_cookie(COOKIE_NAME, raw, httponly=True, secure=SECURE_COOKIES, samesite="strict", max_age=8 * 3600, path="/")
    return {"user": public_user(user), "csrf_token": csrf}


@app.get("/api/v1/health")
def health(db=Depends(get_db)):
    db.query(Configuration).first()
    return {"status": "ok", "service": "CivicSignal 360", "demo_mode": DEMO_MODE, "time": now()}


@app.post("/api/v1/auth/login")
def login(body: Credentials, request: Request, response: Response, db=Depends(get_db)):
    rate_limit("login:" + (request.client.host if request.client else "local"), 15, 60)
    user = db.query(User).filter_by(email=body.email, active=True).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    return start_session(db, user, request, response)


@app.post("/api/v1/auth/register", status_code=201)
def register(body: Registration, request: Request, response: Response, db=Depends(get_db)):
    rate_limit("register:" + (request.client.host if request.client else "local"), 8, 3600)
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(409, "This email is already registered.")
    user = User(name=body.name.strip(), email=body.email, password_hash=hash_password(body.password), role="citizen", domains=[], zones=[])
    db.add(user)
    db.flush()
    return start_session(db, user, request, response)


@app.get("/api/v1/auth/me")
def me(request: Request, user=Depends(current_user)):
    return {"user": public_user(user), "csrf_token": request.state.session.csrf}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(get_db)):
    session = db.get(Session, request.state.session.token_hash)
    if session:
        db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "signed_out"}


def zone_dict(zone):
    return serialize_row(zone, ["id", "name", "population", "geometry"])


def asset_dict(asset):
    return serialize_row(asset, ["id", "name", "domain", "zone_id", "kind", "x", "y", "provenance", "properties"])


def latest_analytics(db, domain):
    from .models import BaselineDeployment

    unavailable_quality = {"status": "not_evaluated", "coverage": None, "missing": None, "invalid": 0, "inactive": 0, "stale": None, "assets": [], "notes": ["No published analysis; coverage and freshness have not been assessed."]}
    deployment = db.get(BaselineDeployment, domain)
    query = db.query(ModelRun).filter_by(domain=domain)
    if deployment:
        if not deployment.active_id:
            return {"domain": domain, "series": [], "findings": [], "forecast": {"status": "insufficient_data", "points": []}, "evaluation": {"status": "not_evaluated", "reason": "Evaluate and promote a baseline before publishing analytics."}, "quality": unavailable_quality, "details": {"note": "Evaluate and promote a baseline before publishing analytics."}}
        query = query.filter_by(model_version=deployment.active_id)
    run = query.order_by(ModelRun.created_at.desc()).first()
    return run.output if run else {"domain": domain, "series": [], "findings": [], "forecast": {"status": "insufficient_data", "points": []}, "evaluation": {"status": "not_evaluated", "reason": "No analysis run has been published."}, "quality": unavailable_quality, "details": {}}


def scope_analytics(output, user, db):
    # Only an explicit all-zone grant permits unpartitioned snapshot aggregates.
    # Never infer scope from the number of zones or recursively pass unknown fields.
    all_zones = {z.id for z in db.query(Zone).all()}
    if user.role == "admin" or all_zones.issubset(set(user.zones)):
        return dict(output)
    result = {"domain": output.get("domain")}
    for key in ("series", "findings"):
        result[key] = [r for r in output.get(key, []) if r.get("zone_id") in user.zones]
    assets = [r for r in output.get("quality", {}).get("assets", []) if r.get("zone_id") in user.zones]
    coverage_values = [r.get("coverage") for r in assets if isinstance(r.get("coverage"), (int, float))]
    degraded = any(r.get("status") == "degraded" or r.get("stale") is True or r.get("irregular_sampling") is True or r.get("invalid", 0) > 0 or r.get("inactive", 0) > 0 or (isinstance(r.get("coverage"), (int, float)) and r["coverage"] < .8) for r in assets)
    all_classified = bool(assets) and all(r.get("status") in {"ready", "degraded"} for r in assets)
    result["quality"] = {"status": "insufficient_data" if not assets else ("degraded" if degraded else ("ready" if all_classified else "unknown")), "coverage": sum(coverage_values) / len(coverage_values) if coverage_values else None, "missing": sum(r.get("missing", 0) or 0 for r in assets), "invalid": sum(r.get("invalid", 0) or 0 for r in assets), "inactive": sum(r.get("inactive", 0) or 0 for r in assets), "stale": any(r.get("stale") is True for r in assets) if assets else None, "assets": assets, "notes": [note for asset in assets for note in asset.get("notes", [])] + ["Only authorized zone telemetry is included; unpartitioned aggregates are withheld."]}
    result["forecast"] = {"status": "Restricted aggregate: full zone scope required", "points": []}
    result["evaluation"] = {"status": "Restricted aggregate: full zone scope required"}
    result["details"] = {"limitation": "Cross-zone details are restricted to users with all-zone scope.", "unit": output.get("details", {}).get("unit"), "estimated_excess": sum(float(r.get("estimated_excess") or 0) for r in result["findings"])}
    return result


@app.get("/api/v1/public")
def public(db=Depends(get_db)):
    return {"name": "CivicSignal 360", "zones": [zone_dict(z) for z in db.query(Zone).all()], "domains": DOMAINS, "demo_mode": DEMO_MODE, "notice": "Independent hackathon prototype — not affiliated with an official government authority.", "counts": {"assets": db.query(Asset).count(), "service_zones": db.query(Zone).count()}}


@app.get("/api/v1/bootstrap")
def bootstrap(request: Request, user=Depends(current_user), db=Depends(get_db)):
    cases = visible_cases(db, user)
    assets = db.query(Asset).all()
    if user.role == "inspector":
        assets = [a for a in assets if a.id in {c.asset_id for c in cases}]
    elif user.role == "operator":
        assets = [a for a in assets if in_scope(user, a.domain, a.zone_id)]
    elif user.role == "citizen":
        # Only synthetic electricity asset labels are exposed for optional report linking.
        assets = [a for a in assets if a.domain == "electricity" and a.provenance == "Synthetic"]
    allzones = db.query(Zone).all()
    zones = allzones if user.role in {"admin", "citizen"} else [z for z in allzones if z.id in user.zones]
    water = scope_analytics(latest_analytics(db, "water"), user, db) if user.role == "admin" or (user.role == "operator" and "water" in user.domains) else {}
    counts = []
    for domain in DOMAINS:
        quality = scope_analytics(latest_analytics(db, domain), user, db).get("quality", {}) if user.role == "admin" or (user.role == "operator" and domain in user.domains) else {}
        counts.append({"domain": domain, "open_cases": len([c for c in cases if c.domain == domain and c.status not in {"closed", "resolved"}]), "assets": len([a for a in assets if a.domain == domain]), "coverage": quality.get("coverage") if user.role in {"operator", "admin"} and (user.role == "admin" or domain in user.domains) else None})
    report_count = db.query(Report).filter_by(user_id=user.id).count() if user.role == "citizen" else len([r for r in db.query(Report).all() if r.case_id in {c.id for c in cases}])
    config = db.get(Configuration, "platform")
    return {"user": public_user(user), "csrf_token": request.state.session.csrf, "zones": [zone_dict(z) for z in zones], "assets": [asset_dict(a) for a in assets], "cases": [serialize_case(c) for c in cases], "metrics": {"active_cases": len([c for c in cases if c.status not in {"resolved", "closed"}]), "high_priority": len([c for c in cases if getattr(c, "priority_review", {}).get("score", c.priority) >= 75 and c.status not in {"resolved", "closed"}]), "estimated_water_excess_litres": water.get("details", {}).get("estimated_excess"), "water_excess_basis": "Latest authorized analysis of stored interval readings; scenarios excluded", "coverage": water.get("quality", {}).get("coverage"), "assets": len(assets), "reports": report_count, "resolved_cases": len([c for c in cases if c.status == "resolved"])}, "series": water.get("series", []), "notifications": notifications(user, db), "domain_stats": counts, "config": {**(config.value if config else {}), "demo_mode": DEMO_MODE, "model_version": "civic-analytics-v1", "notice": "Independent hackathon prototype — not affiliated with an official government authority."}, "inspectors": [{"id": u.id, "name": u.name, "domains": u.domains, "zones": u.zones, "electrical_qualified": (u.settings or {}).get("electrical_qualified") is True} for u in db.query(User).filter_by(role="inspector", active=True).all() if user.role == "admin" or (user.role == "operator" and set(u.domains).intersection(user.domains) and set(u.zones).intersection(user.zones))] if user.role in {"admin", "operator"} else [], "updated_at": now()}


@app.get("/api/v1/cases")
def cases(domain: DOMAIN | None = None, zone: str | None = None, user=Depends(current_user), db=Depends(get_db)):
    return [serialize_case(c) for c in visible_cases(db, user) if (not domain or c.domain == domain) and (not zone or c.zone_id == zone)]


@app.get("/api/v1/cases/{case_id}")
def case_detail(case_id: str, user=Depends(current_user), db=Depends(get_db)):
    return full_case(db, case_access(db, user, case_id), user)


class TransitionBody(StrictModel):
    status: str
    reason: str = Field(min_length=3, max_length=4000)
    version: int = Field(ge=1)


@app.post("/api/v1/cases/{case_id}/transition")
def change_status(case_id: str, body: TransitionBody, user=Depends(current_user), db=Depends(get_db)):
    case = case_access(db, user, case_id)
    transition(db, user, case, body.status, body.reason, body.version)
    db.commit()
    return full_case(db, case, user)


class AssignmentBody(StrictModel):
    inspector_id: str
    reason: str = Field(min_length=3, max_length=4000)
    version: int = Field(ge=1)


@app.post("/api/v1/cases/{case_id}/assign")
def assign(case_id: str, body: AssignmentBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    case = case_access(db, user, case_id)
    if case.status not in {"needs_review", "investigating", "assigned", "monitoring"}:
        raise HTTPException(409, "Investigate or reopen this case before assigning work.")
    inspector = db.get(User, body.inspector_id)
    if not inspector or inspector.role != "inspector" or not inspector.active or not in_scope(inspector, case.domain, case.zone_id):
        raise HTTPException(422, "Choose an active inspector authorized for this domain and zone.")
    if case.domain == "electricity" and (inspector.settings or {}).get("electrical_qualified") is not True:
        raise HTTPException(422, "Electricity cases require an inspector whose electrical qualification was recorded by an administrator.")
    previous_support = case.secondary_assignees
    case.support_assignments = [entry for entry in case.support_assignments if entry.user_id != inspector.id]
    db.flush()
    mutate_case(db, user, case, body.version, "assignment", body.reason, assigned_to=inspector.id, status="assigned", audit_before={"secondary_assignees": previous_support}, audit_after={"secondary_assignees": case.secondary_assignees})
    db.commit()
    return full_case(db, case, user)


class SupportingInspectorsBody(StrictModel):
    inspector_ids: list[str] = Field(max_length=10)
    reason: str = Field(min_length=5, max_length=2000)
    version: int = Field(ge=1)


@app.post("/api/v1/cases/{case_id}/supporting-inspectors")
def supporting_inspectors(case_id: str, body: SupportingInspectorsBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    case = case_access(db, user, case_id)
    if not case.assigned_to or case.status in {"resolved", "closed"}:
        raise HTTPException(409, "Assign a lead to an open case before changing supporting inspectors.")
    ids = sorted(set(body.inspector_ids))
    if len(ids) != len(body.inspector_ids) or case.assigned_to in ids:
        raise HTTPException(422, "Choose distinct supporting inspectors; the lead is already assigned.")
    for ident in ids:
        inspector = db.get(User, ident)
        if not inspector or not inspector.active or inspector.role != "inspector" or not in_scope(inspector, case.domain, case.zone_id):
            raise HTTPException(422, "Each supporting inspector must be active and authorized for this domain and zone.")
        if case.domain == "electricity" and (inspector.settings or {}).get("electrical_qualified") is not True:
            raise HTTPException(422, "Supporting inspectors on electricity cases must have an administrator-recorded electrical qualification.")
    before = case.secondary_assignees
    existing = {entry.user_id: entry for entry in case.support_assignments}
    case.support_assignments = [existing.get(ident) or CaseInspector(case_id=case.id, user_id=ident) for ident in ids]
    # Flush changes in the same transaction; a stale case version rolls back the
    # assignment replacement as well as the attempted audit and notifications.
    db.flush()
    mutate_case(db, user, case, body.version, "supporting_assignment", body.reason, audit_before={"secondary_assignees": before}, audit_after={"secondary_assignees": ids})
    db.commit()
    return full_case(db, case, user)


class NoteBody(StrictModel):
    notes: str = Field(min_length=5, max_length=10000)
    version: int = Field(ge=1)
    checklist: dict[str, bool] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(default_factory=dict, max_length=20)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


def previous_field_submission(db, user, case, body, kind):
    if not body.idempotency_key:
        return None
    record = db.query(Evidence).filter_by(case_id=case.id, actor_id=user.id, idempotency_key=body.idempotency_key).first()
    if record and (record.kind != kind or record.notes != body.notes or record.checklist != body.checklist or (record.observations or {}) != body.observations):
        raise HTTPException(409, "This submission identifier already belongs to different field evidence.")
    return record


class InspectionBody(NoteBody):
    kind: Literal["inspection", "follow_up"] = "inspection"


@app.get("/api/v1/cases/{case_id}/field-schema")
def field_schema(case_id: str, user=Depends(current_user), db=Depends(get_db)):
    from .field_schema import SCHEMAS
    case = case_access(db, user, case_id)
    return {"domain": case.domain, "fields": SCHEMAS[case.domain], "provenance": "Manually recorded; not independently verified"}


@app.post("/api/v1/cases/{case_id}/inspection")
def inspect_case(case_id: str, body: InspectionBody, user=Depends(current_user), db=Depends(get_db)):
    case = case_access(db, user, case_id)
    if user.role not in {"inspector", "admin"}:
        raise HTTPException(403, "An assigned inspector records field findings.")
    if previous_field_submission(db, user, case, body, body.kind):
        return full_case(db, case, user)
    from .field_schema import validate_observations
    validate_observations(case.domain, body.observations)
    if case.domain == "electricity":
        if user.role != "inspector" or (user.settings or {}).get("electrical_qualified") is not True:
            raise HTTPException(403, "Electrical inspection records require an assigned inspector with an administrator-recorded electrical qualification.")
        if body.checklist.get("qualified_electricity_assessment") is not True:
            raise HTTPException(422, "Confirm the qualified electrical assessment before submitting this record.")
    if body.kind == "follow_up" and case.status != "monitoring":
        raise HTTPException(409, "Follow-up findings require the monitoring state.")
    record = Evidence(id=uid(), case_id=case.id, actor_id=user.id, kind=body.kind, notes=body.notes, checklist=body.checklist, observations=body.observations, idempotency_key=body.idempotency_key)
    mutate_case(db, user, case, body.version, body.kind, body.notes, evidence_ids=[record.id])
    db.add(record)
    db.commit()
    return full_case(db, case, user)


@app.post("/api/v1/cases/{case_id}/intervention")
def intervention(case_id: str, body: NoteBody, user=Depends(current_user), db=Depends(get_db)):
    case = case_access(db, user, case_id)
    if user.role not in {"inspector", "admin"}:
        raise HTTPException(403, "An assigned inspector records intervention evidence.")
    if previous_field_submission(db, user, case, body, "intervention"):
        return full_case(db, case, user)
    from .field_schema import validate_observations
    validate_observations(case.domain, body.observations)
    if case.domain == "electricity":
        if user.role != "inspector" or (user.settings or {}).get("electrical_qualified") is not True:
            raise HTTPException(403, "Electrical intervention records require an assigned inspector with an administrator-recorded electrical qualification.")
        if body.checklist.get("qualified_electricity_assessment") is not True:
            raise HTTPException(422, "Confirm qualified electrical responsibility before submitting this record.")
    if case.status != "assigned":
        raise HTTPException(409, "Assign this case before recording an intervention.")
    record = Evidence(id=uid(), case_id=case.id, actor_id=user.id, kind="intervention", notes=body.notes, checklist=body.checklist, observations=body.observations, idempotency_key=body.idempotency_key)
    mutate_case(db, user, case, body.version, "intervention", body.notes, status="intervention", evidence_ids=[record.id])
    db.add(record)
    db.commit()
    return full_case(db, case, user)


class ReportBody(StrictModel):
    domain: DOMAIN
    zone_id: str
    title: str = Field(min_length=4, max_length=180)
    description: str = Field(min_length=10, max_length=6000)
    location: str = Field(min_length=3, max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=100)
    incident_type: Literal["power_outage", "electrical_hazard", "voltage_observation", "other"] = "other"
    affected_asset_id: str | None = None

    @field_validator("affected_asset_id", mode="before")
    @classmethod
    def empty_asset_is_unlinked(cls, value):
        return None if value == "" else value


def reported_incident_metadata(db, body):
    if body.domain != "electricity":
        if body.incident_type != "other":
            raise HTTPException(422, "Electrical incident types are only valid for electricity reports.")
        if body.affected_asset_id:
            asset = db.get(Asset, body.affected_asset_id)
            if not asset or asset.domain != body.domain or asset.zone_id != body.zone_id:
                raise HTTPException(422, "The selected asset must belong to this report's domain and service zone.")
        return None
    if body.affected_asset_id:
        asset = db.get(Asset, body.affected_asset_id)
        if not asset or asset.domain != "electricity" or asset.zone_id != body.zone_id:
            raise HTTPException(422, "The selected electricity asset must belong to this report's service zone.")
    return {
        "type": body.incident_type,
        "affected_asset_id": body.affected_asset_id,
        "classification": "citizen_report_unverified",
        "requested_department": "electricity",
        "assignment_status": "awaiting_authorized_staff_assignment",
        "safety_guidance": "Keep away from suspected electrical hazards and use verified local emergency or utility channels. Do not touch, test, or repair energized equipment.",
    }


def report_dict(db, report):
    result = serialize_row(report, ["id", "case_id", "domain", "zone_id", "title", "description", "location", "created_at"])
    case = db.get(Case, report.case_id)
    result["status"] = case.status
    result["updated_at"] = case.updated_at
    result["reported_incident"] = (case.evidence or {}).get("reported_incident")
    result["receipt"] = "CS360-" + report.id[:8].upper()
    return result


@app.post("/api/v1/reports", status_code=201)
def create_report(body: ReportBody, user=Depends(current_user), db=Depends(get_db)):
    rate_limit("report:" + user.id, 20, 60)
    incident = reported_incident_metadata(db, body)
    existing = db.query(Report).filter_by(user_id=user.id, idempotency_key=body.idempotency_key).first()
    if existing:
        if any(getattr(existing, key) != getattr(body, key) for key in ("domain", "zone_id", "title", "description", "location")):
            raise HTTPException(409, "This submission key was already used for different content.")
        existing_case = db.get(Case, existing.case_id)
        recorded = (existing_case.evidence or {}).get("reported_incident") if existing_case else None
        legacy_electricity_report = body.domain == "electricity" and body.incident_type == "other" and not body.affected_asset_id and recorded is None
        if incident != recorded and not legacy_electricity_report:
            raise HTTPException(409, "This submission key was already used for a different incident type or affected asset.")
        return report_dict(db, existing)
    if not db.get(Zone, body.zone_id):
        raise HTTPException(422, "Choose a registered service zone.")
    if user.role != "citizen" and not in_scope(user, body.domain, body.zone_id):
        raise HTTPException(403, "Report outside authorized domain/zone.")
    evidence = {"observation": "Citizen-reported condition; unverified", "alternative_explanations": ["Routine operations", "Transient conditions", "Incomplete observation"], "data_quality": "No sensor corroboration assumed", **({"reported_incident": incident} if incident else {})}
    evidence["priority_configuration"] = case_priority_snapshot(db)
    report_severity = "high" if incident and incident["type"] in {"power_outage", "electrical_hazard"} else "medium"
    case = Case(id=uid(), event_key="report:" + user.id + ":" + body.idempotency_key, title=body.title, domain=body.domain, zone_id=body.zone_id, asset_id=body.affected_asset_id, severity=report_severity, summary="Citizen observation awaiting inspection. Reported details remain private.", provenance="Reported", priority=75 if report_severity == "high" else 50, evidence=evidence)
    db.add(case)
    config = db.get(Configuration, "platform")
    case.deadline_at = (datetime.fromisoformat(now()) + timedelta(hours=(config.value if config else {}).get("review_hours", 72))).isoformat()
    db.flush()
    report = Report(user_id=user.id, case_id=case.id, **body.model_dump(exclude={"incident_type", "affected_asset_id"}))
    db.add(report)
    db.flush()
    audit(db, user, case, "reported", "Citizen report submitted", after={"status": "needs_review", "report_id": report.id})
    notify_case(db, case, "Report received: " + body.title, "reported")
    db.commit()
    return report_dict(db, report)


@app.get("/api/v1/reports")
def reports(user=Depends(current_user), db=Depends(get_db)):
    query = db.query(Report)
    if user.role == "citizen":
        query = query.filter_by(user_id=user.id)
    else:
        query = query.filter(Report.case_id.in_([c.id for c in visible_cases(db, user)]))
    return [report_dict(db, r) for r in query.order_by(Report.created_at.desc()).all()]


@app.get("/api/v1/reports/submissions/{submission_key}")
def report_submission_status(submission_key: str, user=Depends(current_user), db=Depends(get_db)):
    if not 8 <= len(submission_key) <= 100:
        raise HTTPException(422, "Invalid report submission identifier.")
    report = db.query(Report).filter_by(user_id=user.id, idempotency_key=submission_key).first()
    return {"report": report_dict(db, report) if report else None}


@app.get("/api/v1/reports/{report_id}")
def report_detail(report_id: str, user=Depends(current_user), db=Depends(get_db)):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    case = db.get(Case, report.case_id)
    if report.user_id != user.id and not can_case(user, case):
        raise HTTPException(403, "This report is private.")
    result = report_dict(db, report)
    result["timeline"] = [{"action": a.action, "created_at": a.created_at, "status": a.after.get("status")} for a in db.query(Audit).filter_by(case_id=case.id).order_by(Audit.created_at).all()]
    return result


@app.get("/api/v1/analytics/{domain}")
def analytics(domain: DOMAIN, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    if user.role != "admin" and domain not in user.domains:
        raise HTTPException(403, "This department is outside your scope.")
    return scope_analytics(latest_analytics(db, domain), user, db)


@app.get("/api/v1/notifications")
def notifications(user=Depends(current_user), db=Depends(get_db)):
    permitted = {c.id for c in visible_cases(db, user)}
    permitted.update(r.case_id for r in db.query(Report).filter_by(user_id=user.id).all())
    return [serialize_row(n, ["id", "case_id", "title", "read", "created_at"]) for n in db.query(Notification).filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(100).all() if not n.case_id or n.case_id in permitted]


@app.post("/api/v1/notifications/{notification_id}/read")
def read_notification(notification_id: str, user=Depends(current_user), db=Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(404, "Notification not found.")
    notification.read = True
    db.commit()
    return {"status": "read"}


class SettingsBody(StrictModel):
    language: Literal["en", "mr"] | None = None
    timezone: Literal["Asia/Kolkata", "UTC"] | None = None
    notifications: bool | None = None
    display: Literal["dark", "light", "system"] | None = None


@app.patch("/api/v1/settings")
def settings(body: SettingsBody, user=Depends(current_user), db=Depends(get_db)):
    stored = db.get(User, user.id)
    stored.settings = {**stored.settings, **body.model_dump(exclude_none=True)}
    db.commit()
    return stored.settings


@app.get("/api/v1/network")
def network(user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    config = db.get(Configuration, "network")
    network = dict(config.value if config else {"nodes": [], "edges": []})
    nodes = [n for n in network.get("nodes", []) if user.role == "admin" or (n.get("zone_id") in user.zones and n.get("domain", "water") in user.domains)]
    ids = {n["id"] for n in nodes}
    network["nodes"] = nodes
    network["edges"] = [e for e in network.get("edges", []) if e["source"] in ids and e["target"] in ids]
    network["configuration_hash"] = hashlib.sha256(json.dumps({"nodes": network["nodes"], "edges": network["edges"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    network["limitation"] = "Topology only. Hydraulic result unavailable; connectivity does not determine pressure or delivered volume."
    return network


class PathBody(StrictModel):
    source: str
    target: str
    zone_id: str | None = None
    closed_edges: list[str] = Field(default_factory=list, max_length=100)


@app.post("/api/v1/network/path")
def path(body: PathBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    for ident in (body.source, body.target):
        asset = db.get(Asset, ident)
        if not asset or not in_scope(user, asset.domain, asset.zone_id):
            raise HTTPException(403, "Asset outside authorized scope.")
    from services.analytics.pipeline import network_path
    authorized_network = network(user, db)
    if body.zone_id:
        nodes = [n for n in authorized_network["nodes"] if n.get("zone_id") == body.zone_id]
        if not nodes:
            raise HTTPException(422, "Choose a zone in your authorized network.")
        ids = {n["id"] for n in nodes}
        authorized_network["nodes"] = nodes
        authorized_network["edges"] = [e for e in authorized_network["edges"] if e["source"] in ids and e["target"] in ids]
    if set(body.closed_edges) - {e["id"] for e in authorized_network.get("edges", [])}:
        raise HTTPException(422, "Choose a pipe in your authorized network.")
    try:
        result = network_path(body.source, body.target, body.closed_edges, data=authorized_network)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # Do not expose traversal through zones outside the operator scope.
    for ident in result.get("path", []):
        asset = db.get(Asset, ident)
        if not asset or not in_scope(user, asset.domain, asset.zone_id):
            raise HTTPException(403, "Path traverses a restricted service zone.")
    authorized_ids = {n["id"] for n in authorized_network.get("nodes", [])}
    result["reachable"] = [ident for ident in result.get("reachable", []) if ident in authorized_ids]
    return result


class SavedNetworkInput(StrictModel):
    name: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=5, max_length=2000)
    inputs: PathBody
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("name", "reason")
    @classmethod
    def meaningful(cls, value, info):
        if len(value.strip()) < (5 if info.field_name == "reason" else 3):
            raise ValueError("Enter a meaningful scenario name and reason.")
        return value.strip()


def saved_network_row(db, user, ident):
    require_staff(user)
    row = db.get(Configuration, "network-scenario:" + user.id + ":" + ident)
    if not row or row.value.get("owner_id") != user.id:
        raise HTTPException(404, "Saved network scenario not found.")
    return row


def network_scenario_dict(row):
    return {"id": row.key.rsplit(":", 1)[-1], "version": row.version, **{key: value for key, value in row.value.items() if key not in {"request_hash", "owner_id"}}}


@app.get("/api/v1/network/scenarios")
def list_network_scenarios(user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    current = network(user, db)
    output = []
    rows = db.query(Configuration).filter(Configuration.key.startswith("network-scenario:"+user.id+":", autoescape=True)).order_by(Configuration.key).limit(200).all()
    for row in rows:
        if row.value.get("owner_id") != user.id:
            continue
        try:
            path(PathBody(**row.value["inputs"]), user, db)
        except HTTPException:
            continue
        output.append({**network_scenario_dict(row), "topology_changed": row.value["configuration_hash"] != current["configuration_hash"]})
    return sorted(output, key=lambda item: item["created_at"], reverse=True)


@app.post("/api/v1/network/scenarios")
def save_network_scenario(body: SavedNetworkInput, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    path(body.inputs, user, db)
    if len(set(body.inputs.closed_edges)) != len(body.inputs.closed_edges):
        raise HTTPException(422, "Select each closed pipe once.")
    ident = hashlib.sha256((user.id+":"+body.idempotency_key).encode()).hexdigest()
    key = "network-scenario:"+user.id+":"+ident
    request_hash = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    previous = db.get(Configuration, key)
    if previous:
        if previous.value["request_hash"] != request_hash:
            raise HTTPException(409, "This submission identifier belongs to a different scenario.")
        return {**network_scenario_dict(previous), "duplicate": True}
    if body.configuration_hash != network(user, db)["configuration_hash"]:
        raise HTTPException(409, "Network configuration or permissions changed. Reload and review the topology before saving.")
    if db.query(Configuration).filter(Configuration.key.startswith("network-scenario:"+user.id+":", autoescape=True)).count() >= 200:
        raise HTTPException(422, "This prototype retains at most 200 named scenarios per account.")
    value = {"owner_id": user.id, "name": body.name, "reason": body.reason, "inputs": body.inputs.model_dump(), "configuration_hash": body.configuration_hash,
             "request_hash": request_hash, "created_at": now(), "archived": False}
    row = Configuration(key=key, version=1, value=value)
    db.add(row)
    audit(db, user, None, "network_scenario_saved", body.reason, after={"scenario_id": ident, "configuration_hash": body.configuration_hash})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A concurrent save completed. Retry the same submission identifier.") from exc
    return {**network_scenario_dict(row), "duplicate": False}


@app.get("/api/v1/network/scenarios/{scenario_id}")
def load_network_scenario(scenario_id: str, user=Depends(current_user), db=Depends(get_db)):
    row = saved_network_row(db, user, scenario_id)
    path(PathBody(**row.value["inputs"]), user, db)
    if row.value["archived"]:
        raise HTTPException(409, "Restore the archived scenario before loading it.")
    if row.value["configuration_hash"] != network(user, db)["configuration_hash"]:
        raise HTTPException(409, "Network configuration or permissions changed. Review the current topology and save a new scenario.")
    return network_scenario_dict(row)


class NetworkArchiveInput(StrictModel):
    version: int = Field(ge=1)
    archived: bool
    reason: str = Field(min_length=5, max_length=2000)


@app.post("/api/v1/network/scenarios/{scenario_id}/archive")
def archive_network_scenario(scenario_id: str, body: NetworkArchiveInput, user=Depends(current_user), db=Depends(get_db)):
    row = saved_network_row(db, user, scenario_id)
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, "Explain the archive or restore action.")
    value = {**row.value, "archived": body.archived, "updated_at": now()}
    changed = db.execute(update(Configuration).where(Configuration.key == row.key, Configuration.version == body.version).values(value=value, version=body.version+1))
    if changed.rowcount != 1:
        raise HTTPException(409, "This saved scenario changed. Refresh before updating it.")
    audit(db, user, None, "network_scenario_archived" if body.archived else "network_scenario_restored", body.reason, after={"scenario_id": scenario_id, "version": body.version+1})
    db.commit()
    return network_scenario_dict(row)


class JobBody(StrictModel):
    kind: Literal["analysis", "scenario"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=100)


def serialize_job(job):
    return {**serialize_row(job, ["id", "kind", "parameters", "status", "attempts", "max_attempts", "result", "error", "created_at", "updated_at", "control_version"]), "checkpoint_ready": job.checkpoint is not None, "checkpoint_stage": "calculated; cases not published" if job.checkpoint is not None else "not calculated"}


def enqueue(db, user, kind, parameters, key=None, start_paused=False, demo_session_id=None):
    require_staff(user)
    if kind == "scenario" and not DEMO_MODE:
        raise HTTPException(403, "Synthetic scenarios are only enabled in local demo mode.")
    domain = parameters.get("domain", "water")
    if domain not in DOMAINS or (user.role != "admin" and domain not in user.domains):
        raise HTTPException(403, "Scenario domain outside authorized scope.")
    if user.role != "admin" and set(user.zones) != {z.id for z in db.query(Zone).all()}:
        raise HTTPException(403, "Scenario and aggregate analysis require all-zone authorization.")
    if kind == "scenario" and DEMO_MODE:
        from .worker import configured_scenario_parameters
        parameters = {**parameters, "parameters": configured_scenario_parameters(db, domain, parameters.get("parameters", {}))}
    try:
        encoded_parameters = json.dumps(parameters, allow_nan=False)
    except (ValueError, TypeError):
        raise HTTPException(422, "Parameters must contain finite JSON values.") from None
    if len(encoded_parameters) > 20000:
        raise HTTPException(413, "Scenario parameters too large.")
    if kind == "scenario" and DEMO_MODE and not demo_session_id:
        raise HTTPException(409, "Sign in to an isolated browser demo session before creating a scenario.")
    dedupe = (user.id + ":scenario:" + demo_session_id + ":" if kind == "scenario" and DEMO_MODE else user.id + ":") + (key or uid())
    job = db.query(Job).filter_by(dedupe_key=dedupe).first()
    if not job:
        job = Job(user_id=user.id, kind=kind, parameters=parameters, dedupe_key=dedupe, status='paused' if start_paused else 'queued', demo_session_id=demo_session_id if kind == "scenario" and DEMO_MODE else None)
        db.add(job)
        db.commit()
    elif job.kind != kind or job.parameters != parameters:
        raise HTTPException(409, "This job key already belongs to different parameters.")
    return serialize_job(job)


@app.post("/api/v1/jobs", status_code=202)
def create_job(body: JobBody, request: Request, user=Depends(current_user), db=Depends(get_db)):
    return enqueue(db, user, body.kind, body.parameters, body.idempotency_key, demo_session_id=request.state.session.demo_session_id)


@app.get("/api/v1/jobs/{job_id}")
def job_detail(job_id: str, user=Depends(current_user), db=Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or (job.user_id != user.id and user.role != "admin") or (job.demo_session_id and job.demo_session_id != getattr(user, "_demo_session_id", None)):
        raise HTTPException(404, "Job not found.")
    require_staff(user)
    if user.role != "admin" and (job.parameters.get("domain", "water") not in user.domains or not {z.id for z in db.query(Zone).all()}.issubset(set(user.zones))):
        raise HTTPException(403, "Job result exceeds your current authorized scope.")
    return serialize_job(job)


def scenario_playback_for_job(db, job):
    if job.kind != "scenario" or job.status != "succeeded" or job.result is None:
        raise HTTPException(409, "Scenario playback is available after a scenario run succeeds.")
    playback = db.get(ScenarioRunPlayback, job.id)
    if playback is None:
        from .worker import scenario_frame_timestamps
        playback = ScenarioRunPlayback(job_id=job.id, frame_timestamps=scenario_frame_timestamps(job.result), cursor=0, status="paused", speed=1., version=1, updated_at=now())
        db.add(playback)
        db.commit()
        db.refresh(playback)
    return playback


def serialize_playback(playback, result=None):
    from .playback import playback_analysis
    timestamps = playback.frame_timestamps or []
    cursor = min(max(0, playback.cursor), max(0, len(timestamps) - 1))
    timestamp = timestamps[cursor] if timestamps else None
    return {"job_id": playback.job_id, "frame_timestamps": timestamps, "frame_count": len(timestamps), "cursor": cursor, "timestamp": timestamp, "status": playback.status, "speed": playback.speed, "version": playback.version, "updated_at": playback.updated_at, "analysis": playback_analysis(result, timestamp, completed=bool(timestamps) and cursor == len(timestamps) - 1)}


@app.get("/api/v1/jobs/{job_id}/playback")
def job_playback(job_id: str, user=Depends(current_user), db=Depends(get_db)):
    job_detail(job_id, user, db)
    job = db.get(Job, job_id)
    return serialize_playback(scenario_playback_for_job(db, job), job.result)


class PlaybackControlBody(StrictModel):
    action: Literal["play", "pause", "step_forward", "step_back", "seek", "restart", "speed"]
    version: int = Field(ge=1)
    cursor: int | None = Field(default=None, ge=0)
    speed: float | None = Field(default=None, ge=.5, le=4.)


@app.post("/api/v1/jobs/{job_id}/playback")
def control_job_playback(job_id: str, body: PlaybackControlBody, user=Depends(current_user), db=Depends(get_db)):
    job_detail(job_id, user, db)
    job = db.get(Job, job_id)
    playback = scenario_playback_for_job(db, job)
    action = body.action
    frame_count = len(playback.frame_timestamps or [])
    last = max(0, frame_count - 1)
    cursor = playback.cursor
    status = playback.status
    speed = playback.speed
    tick_at = time.time()
    if action == "play":
        status = "playing" if frame_count > 1 and cursor < last else "paused"
        playback.last_tick_at = tick_at if status == "playing" else playback.last_tick_at
    elif action == "pause":
        status = "paused"
        playback.last_tick_at = tick_at
    elif action == "step_forward":
        cursor, status = min(last, cursor + 1), "paused"
        playback.last_tick_at = tick_at
    elif action == "step_back":
        cursor, status = max(0, cursor - 1), "paused"
        playback.last_tick_at = tick_at
    elif action == "seek":
        if body.cursor is None or body.cursor > last:
            raise HTTPException(422, "Choose a recorded frame in this scenario.")
        cursor, status = body.cursor, "paused"
        playback.last_tick_at = tick_at
    elif action == "restart":
        cursor, status = 0, "paused"
        playback.last_tick_at = tick_at
    elif action == "speed":
        if body.speed not in {.5, 1., 2., 4.}:
            raise HTTPException(422, "Choose a playback speed of 0.5×, 1×, 2× or 4×.")
        speed = body.speed
        playback.last_tick_at = tick_at
    before = {"cursor": playback.cursor, "status": playback.status, "speed": playback.speed}
    changed = db.execute(update(ScenarioRunPlayback).where(
        ScenarioRunPlayback.job_id == job.id,
        ScenarioRunPlayback.version == body.version,
    ).values(cursor=cursor, status=status, speed=speed, last_tick_at=playback.last_tick_at, version=body.version + 1, updated_at=now()), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "The playback clock changed. Refresh its state before controlling it again.")
    db.commit()
    db.refresh(playback)
    return serialize_playback(playback, job.result)


class JobControlBody(StrictModel):
    version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=2000)


@app.post('/api/v1/jobs/{job_id}/{action}')
def control_job(job_id: str, action: Literal['pause', 'resume'], body: JobControlBody, user=Depends(current_user), db=Depends(get_db)):
    job_detail(job_id, user, db)
    job = db.get(Job, job_id)
    if job.kind != 'scenario':
        raise HTTPException(422, 'Pause and resume currently support scenario jobs only.')
    if not body.reason.strip():
        raise HTTPException(422, 'A control reason is required.')
    before = job.status
    if action == 'pause' and before in {'queued', 'running'}:
        target = 'paused' if before == 'queued' else 'pausing'
    elif action == 'resume' and before == 'paused':
        target = 'queued'
    else:
        raise HTTPException(409, 'This job state does not allow that action. Refresh its status.')
    values = {'status': target, 'control_version': body.version+1, 'updated_at': now()}
    if target != 'pausing':
        values.update(claim_token=None, lease_until=None)
    changed = db.execute(update(Job).where(Job.id == job.id, Job.status == before, Job.control_version == body.version).values(**values), execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'The job changed. Refresh before sending another control.')
    audit(db, user, None, 'job_'+action, body.reason, before={'status': before}, after={'job_id': job.id, 'status': target, 'control_version': body.version+1})
    db.commit()
    db.refresh(job)
    return serialize_job(job)


class ScenarioBody(StrictModel):
    domain: DOMAIN
    scenario: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=100)
    start_paused: bool = False


@app.post("/api/v1/scenarios", status_code=202)
def scenario(body: ScenarioBody, request: Request, user=Depends(current_user), db=Depends(get_db)):
    if not DEMO_MODE:
        raise HTTPException(403, "Synthetic scenarios are only enabled in local demo mode.")
    return enqueue(db, user, "scenario", {"domain": body.domain, "scenario": body.scenario, "parameters": body.parameters, "start_paused": body.start_paused}, body.idempotency_key, body.start_paused, request.state.session.demo_session_id)


@app.get("/api/v1/admin")
def admin(request: Request, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    jobs = db.query(Job)
    audits = db.query(Audit)
    if DEMO_MODE:
        session_id = request.state.session.demo_session_id
        jobs = jobs.filter((Job.demo_session_id.is_(None)) | (Job.demo_session_id == session_id))
        audits = audits.filter((Audit.demo_session_id.is_(None)) | (Audit.demo_session_id == session_id))
    return {"users": [public_user(u) | {"active": u.active} for u in db.query(User).all()], "zones": [zone_dict(z) for z in db.query(Zone).all()], "assets": [asset_dict(a) for a in db.query(Asset).all()], "configuration": {c.key: {"value": c.value, "version": c.version} for c in db.query(Configuration).filter(Configuration.key == "platform").all()}, "jobs": [serialize_job(j) for j in jobs.order_by(Job.created_at.desc()).limit(30).all()], "audits": [serialize_row(a, ["id", "actor_id", "case_id", "action", "reason", "before", "after", "created_at"]) for a in audits.order_by(Audit.created_at.desc()).limit(100).all()]}


class UserUpdate(StrictModel):
    role: Literal["citizen", "operator", "inspector", "admin"]
    domains: list[DOMAIN]
    zones: list[str]
    active: bool = True
    electrical_qualified: bool | None = None
    reason: str = Field(min_length=5, max_length=2000)


@app.patch("/api/v1/admin/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if target.id == user.id and (body.role != "admin" or not body.active):
        raise HTTPException(409, "You cannot remove your own administrator access.")
    if set(body.zones) - {z.id for z in db.query(Zone).all()}:
        raise HTTPException(422, "Unknown service zone.")
    if body.electrical_qualified is True and (body.role != "inspector" or "electricity" not in body.domains):
        raise HTTPException(422, "Electrical qualification can only be recorded for an inspector authorized for the electricity department.")
    before = public_user(target)
    target.role, target.domains, target.zones, target.active = body.role, body.domains, body.zones, body.active
    old_settings = target.settings or {}
    eligible = body.role == "inspector" and "electricity" in body.domains
    qualified = body.electrical_qualified if body.electrical_qualified is not None else old_settings.get("electrical_qualified", False)
    target.settings = {**old_settings, "electrical_qualified": bool(qualified) if eligible else False}
    db.query(Session).filter_by(user_id=target.id).delete()
    audit(db, user, None, "user_permissions", body.reason, before, public_user(target))
    db.commit()
    return public_user(target)


class RoadPriorityWeights(StrictModel):
    severity: float = Field(ge=0, le=100)
    extent_m2: float = Field(ge=0, le=100)
    daily_exposure: float = Field(ge=0, le=100)
    repeat_count: float = Field(ge=0, le=100)
    vulnerable_location: float = Field(ge=0, le=100)


class CasePriorityWeights(StrictModel):
    severity: float = Field(ge=0, le=100)
    persistence: float = Field(ge=0, le=100)
    exposure: float = Field(ge=0, le=100)
    evidence_diversity: float = Field(ge=0, le=100)
    case_age: float = Field(ge=0, le=100)
    cross_domain_hazard: float = Field(ge=0, le=100)


class ConfigBody(StrictModel):
    water_tariff_per_m3: float | None = Field(default=None, ge=0, le=100000)
    electricity_tariff_per_kwh: float | None = Field(default=None, ge=0, le=100000)
    voltage_lower_v: float | None = Field(default=None, ge=0, le=1000)
    voltage_upper_v: float | None = Field(default=None, ge=0, le=1000)
    streetlight_on_hour: int | None = Field(default=None, ge=0, le=23)
    streetlight_off_hour: int | None = Field(default=None, ge=0, le=23)
    review_hours: int = Field(default=72, ge=1, le=720)
    cross_domain_max_distance_m: float | None = Field(default=None, ge=0, le=50000)
    cross_domain_max_hours: float | None = Field(default=None, ge=0, le=720)
    road_priority_weights: RoadPriorityWeights | None = None
    case_priority_weights: CasePriorityWeights | None = None
    version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=2000)


@app.patch("/api/v1/admin/config")
def admin_config(body: ConfigBody, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    config = db.get(Configuration, "platform")
    if not config or config.version != body.version:
        raise HTTPException(409, "Configuration changed; refresh before editing.")
    old = config.value
    voltage_lower_v = body.voltage_lower_v if body.voltage_lower_v is not None else old.get("voltage_lower_v", 207)
    voltage_upper_v = body.voltage_upper_v if body.voltage_upper_v is not None else old.get("voltage_upper_v", 253)
    if voltage_lower_v >= voltage_upper_v:
        raise HTTPException(422, "Illustrative voltage lower threshold must be below the upper threshold.")
    streetlight_on_hour = body.streetlight_on_hour if body.streetlight_on_hour is not None else old.get("streetlight_on_hour", 18)
    streetlight_off_hour = body.streetlight_off_hour if body.streetlight_off_hour is not None else old.get("streetlight_off_hour", 6)
    if streetlight_on_hour == streetlight_off_hour:
        raise HTTPException(422, "Streetlight on and off schedule hours must be distinct.")
    try:
        cross_domain_max_distance_m = float(body.cross_domain_max_distance_m if body.cross_domain_max_distance_m is not None else old.get("cross_domain_max_distance_m", 500))
        cross_domain_max_hours = float(body.cross_domain_max_hours if body.cross_domain_max_hours is not None else old.get("cross_domain_max_hours", 24))
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, "Cross-domain distance and time windows must be finite and nonnegative.") from None
    if not math.isfinite(cross_domain_max_distance_m) or cross_domain_max_distance_m < 0 or not math.isfinite(cross_domain_max_hours) or cross_domain_max_hours < 0:
        raise HTTPException(422, "Cross-domain distance and time windows must be finite and nonnegative.")
    from services.analytics.pipeline import ROAD_PRIORITY_WEIGHTS
    priority_weights = body.road_priority_weights.model_dump() if body.road_priority_weights is not None else old.get("road_priority_weights", ROAD_PRIORITY_WEIGHTS)
    if abs(sum(priority_weights.values()) - 100) > 1e-6:
        raise HTTPException(422, "Road repair priority weights must total 100 points.")
    case_priority_weights = body.case_priority_weights.model_dump() if body.case_priority_weights is not None else old.get("case_priority_weights", DEFAULT_CASE_PRIORITY_WEIGHTS)
    try:
        case_priority_weights = validate_case_priority_weights(case_priority_weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    updates = body.model_dump(exclude={"reason", "version", "road_priority_weights", "case_priority_weights", "cross_domain_max_distance_m", "cross_domain_max_hours"})
    updates["voltage_lower_v"], updates["voltage_upper_v"] = voltage_lower_v, voltage_upper_v
    updates["streetlight_on_hour"], updates["streetlight_off_hour"] = streetlight_on_hour, streetlight_off_hour
    updates["cross_domain_max_distance_m"], updates["cross_domain_max_hours"] = cross_domain_max_distance_m, cross_domain_max_hours
    updates["road_priority_weights"] = priority_weights
    updates["case_priority_weights"] = case_priority_weights
    config.value = {**old, **updates}
    config.version += 1
    audit(db, user, None, "configuration", body.reason, old, config.value)
    db.commit()
    return {"value": config.value, "version": config.version}


@app.get("/api/v1/uploads/template")
def csv_template(domain: Literal["water", "electricity"] = "water", user=Depends(current_user)):
    require_staff(user)
    from .ingestion import FIELDS, OPTIONAL_FIELDS
    stream = io.StringIO()
    writer = csv.writer(stream)
    fields = FIELDS + OPTIONAL_FIELDS if domain == "electricity" else FIELDS
    writer.writerow(fields)
    sample = ["new-reading-001", f"{domain}-river", "river", "2026-11-01T00:00:00+00:00", 60, 100 if domain == "water" else 10, "L" if domain == "water" else "kWh", "Uploaded", "valid"]
    writer.writerow(sample + ([230, "V", "", "", "", ""] if domain == "electricity" else []))
    return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{domain}-interval-template.csv"'})


@app.post("/api/v1/uploads/preview")
async def csv_preview(file: UploadFile = File(...), user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "Upload a CSV file.")
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "CSV size limit is 2 MB.")
    from .ingestion import preview_csv
    return preview_csv(db, user, content)


@app.post("/api/v1/uploads/{upload_id}/commit")
def csv_commit(upload_id: str, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    upload = db.get(Upload, upload_id)
    if not upload or (upload.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Preview not found.")
    if upload.status == "committed":
        return {"accepted": len(upload.rows), "duplicates": 0, "status": "committed", "idempotent": True}
    if upload.errors:
        raise HTTPException(422, "Correct rejected rows and upload again. Imports commit atomically.")
    # Serialize writers on affected asset rows (also a write lock on SQLite).
    # Validate again under that lock; a preview is not an import reservation.
    for asset_id in sorted({r["asset_id"] for r in upload.rows}):
        db.execute(update(Asset).where(Asset.id == asset_id).values(name=Asset.name))
    db.refresh(upload)
    if upload.status == "committed":
        return {"accepted": len(upload.rows), "duplicates": 0, "status": "committed", "idempotent": True}
    for raw in upload.rows:
        if not in_scope(user, raw["domain"], raw["zone_id"]):
            raise HTTPException(403, "Upload scope is no longer authorized.")
        if db.get(Reading, raw["id"]) or db.query(Reading).filter_by(asset_id=raw["asset_id"], timestamp=raw["timestamp"]).first():
            raise HTTPException(409, "Readings changed after preview. Create a fresh preview.")
        start = datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
        end = start + timedelta(minutes=raw["interval_minutes"])
        for stored in db.query(Reading).filter_by(asset_id=raw["asset_id"]).all():
            old_start = datetime.fromisoformat(stored.timestamp.replace("Z", "+00:00"))
            if start < old_start + timedelta(minutes=stored.interval_minutes) and end > old_start:
                raise HTTPException(409, "An overlapping interval was committed after preview. Create a fresh preview.")
    db.add_all([Reading(**raw) for raw in upload.rows])
    upload.status = "committed"
    audit(db, user, None, "reading_import", "Validated interval CSV import", after={"upload_id": upload.id, "count": len(upload.rows), "checksum": upload.checksum})
    db.commit()
    return {"accepted": len(upload.rows), "duplicates": 0, "status": "committed", "analysis": "Queue an analysis job to recompute derived findings."}


@app.post("/api/v1/cases/{case_id}/evidence")
async def upload_evidence(case_id: str, file: UploadFile = File(...), notes: str = Form("Photographic observation"), idempotency_key: str | None = Form(None), user=Depends(current_user), db=Depends(get_db)):
    case = db.get(Case, case_id)
    own_report = case and db.query(Report).filter_by(case_id=case.id, user_id=user.id).first()
    if not case or not (can_case(user, case) or own_report):
        raise HTTPException(403, "Evidence is private to authorized case participants.")
    if len(notes) > 4000:
        raise HTTPException(422, "Evidence note is too long.")
    if Path(file.filename or "").suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(422, "Only PNG and JPEG photographs are supported.")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Photographs must be under 5 MB.")
    checksum = hashlib.sha256(content).hexdigest()
    submission_key = idempotency_key or hashlib.sha256(content + notes.encode("utf-8")).hexdigest()
    if not 8 <= len(submission_key) <= 100:
        raise HTTPException(422, "Evidence submission key must be 8–100 characters.")
    existing = db.query(Evidence).filter_by(case_id=case.id, actor_id=user.id, idempotency_key=submission_key).first()
    if existing:
        if existing.content_hash != checksum or existing.notes != notes:
            raise HTTPException(409, "Evidence submission key was already used for different content.")
        return {"id": existing.id, "kind": existing.kind, "notes": existing.notes, "url": f"/api/v1/evidence/{existing.id}/download", "created_at": existing.created_at, "idempotent": True}
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG"} or image.width * image.height > 20_000_000:
                raise ValueError("Unsupported image format or dimensions.")
            image.load()
            image = image.convert("RGB")
            image.thumbnail((2400, 2400))
            folder = DATA_DIR / "private-evidence"
            folder.mkdir(parents=True, exist_ok=True)
            filename = uid() + ".jpg"
            image.save(folder / filename, "JPEG", quality=88)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "The file is not a supported safe photograph.") from exc
    record = Evidence(case_id=case.id, actor_id=user.id, kind="photograph", notes=notes, filename=filename, mime="image/jpeg", content_hash=checksum, idempotency_key=submission_key)
    db.add(record)
    db.flush()
    audit(db, user, case, "evidence_added", notes, after={"evidence_id": record.id})
    try:
        db.commit()
    except Exception:
        (folder / filename).unlink(missing_ok=True)
        raise
    return {"id": record.id, "kind": record.kind, "notes": record.notes, "url": f"/api/v1/evidence/{record.id}/download", "created_at": record.created_at}


@app.get("/api/v1/cases/{case_id}/evidence/submissions/{submission_key}")
def photograph_submission_status(case_id: str, submission_key: str, user=Depends(current_user), db=Depends(get_db)):
    case = db.get(Case, case_id)
    own_report = case and db.query(Report).filter_by(case_id=case.id, user_id=user.id).first()
    if not case or not (can_case(user, case) or own_report):
        raise HTTPException(403, "Evidence is private to authorized case participants.")
    if not 8 <= len(submission_key) <= 100:
        raise HTTPException(422, "Evidence submission key must be 8–100 characters.")
    record = db.query(Evidence).filter_by(case_id=case.id, actor_id=user.id, kind="photograph", idempotency_key=submission_key).first()
    return {"evidence": {"id": record.id, "kind": record.kind, "notes": record.notes, "url": f"/api/v1/evidence/{record.id}/download", "created_at": record.created_at} if record else None}


@app.get("/api/v1/evidence/{evidence_id}/download")
def download_evidence(evidence_id: str, user=Depends(current_user), db=Depends(get_db)):
    evidence = db.get(Evidence, evidence_id)
    if not evidence or not evidence.filename:
        raise HTTPException(404, "Photograph not found.")
    case = db.get(Case, evidence.case_id)
    own_report = db.query(Report).filter_by(case_id=case.id, user_id=user.id).first()
    if not can_case(user, case) and not (own_report and evidence.actor_id == user.id):
        raise HTTPException(403, "This photograph is private.")
    return FileResponse(DATA_DIR / "private-evidence" / evidence.filename, media_type="image/jpeg", filename="case-evidence.jpg", headers={"Content-Disposition": "inline; filename=case-evidence.jpg"})


@app.get("/api/v1/cases/{case_id}/export")
def export_case(case_id: str, user=Depends(current_user), db=Depends(get_db)):
    case = case_access(db, user, case_id)
    return JSONResponse(full_case(db, case, user), headers={"Content-Disposition": f'attachment; filename="case-{case.id}.json"'})


class LinkBody(StrictModel):
    target_id: str
    reason: str = Field(min_length=5, max_length=2000)


@app.post("/api/v1/cases/{case_id}/link")
def link_case(case_id: str, body: LinkBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    source, target = case_access(db, user, case_id), case_access(db, user, body.target_id)
    if source.id == target.id:
        raise HTTPException(422, "A case cannot link to itself.")
    first, second = sorted([source.id, target.id])
    existing = db.query(Association).filter_by(source_id=first, target_id=second).first()
    if existing:
        return serialize_row(existing, ["id", "source_id", "target_id", "status", "basis"])
    same_asset = bool(source.asset_id and source.asset_id == target.asset_id)
    link = Association(source_id=first, target_id=second, status="accepted", basis={"reason": body.reason, "source": "Human review", "relationship": "shared_asset" if same_asset else "shared_zone" if source.zone_id == target.zone_id else "operator_linked", "same_asset": same_asset, "causation": "Not established"})
    db.add(link)
    db.flush()
    audit(db, user, source, "case_linked", body.reason, after={"target_id": target.id})
    audit(db, user, target, "case_linked", body.reason, after={"target_id": source.id})
    for case in (source, target):
        notify_case(db, case, "Case link accepted for coordination", "association:" + link.id)
    db.commit()
    return serialize_row(link, ["id", "source_id", "target_id", "status", "basis"])


@app.get("/api/v1/associations")
def associations(user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    cases = visible_cases(db, user)
    ids = {c.id for c in cases}
    links = [a for a in db.query(Association).all() if a.source_id in ids and a.target_id in ids]
    known_pairs = {tuple(sorted((link.source_id, link.target_id))) for link in links}
    stored = [serialize_row(a, ["id", "source_id", "target_id", "status", "basis"]) for a in links]
    suggestions = _cross_domain_suggestions(db, cases)
    return stored + [{"id": item["id"], "source_id": item["source"], "target_id": item["target"], "status": "suggested", "basis": item}
                     for item in suggestions if tuple(sorted((item["source"], item["target"]))) not in known_pairs]


def _cross_domain_suggestions(db, cases):
    """Calculate candidates only from authorized cases and their explicit coordinates."""
    if not cases:
        return []
    from services.analytics.pipeline import cross_domain_suggestions

    asset_ids = {case.asset_id for case in cases if case.asset_id}
    asset_rows = db.query(Asset).filter(Asset.id.in_(asset_ids)).all() if asset_ids else []
    coordinate_assets = []
    for asset in asset_rows:
        properties = asset.properties if isinstance(asset.properties, dict) else {}
        lat, lon = properties.get("lat"), properties.get("lon")
        if isinstance(lat, (int, float)) and not isinstance(lat, bool) and isinstance(lon, (int, float)) and not isinstance(lon, bool) and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            coordinate_assets.append({"id": asset.id, "lat": lat, "lon": lon})
    config = db.get(Configuration, "platform")
    config_value = config.value if config and isinstance(config.value, dict) else {}
    try:
        max_distance = float(config_value.get("cross_domain_max_distance_m", 500))
        max_hours = float(config_value.get("cross_domain_max_hours", 24))
        if not math.isfinite(max_distance) or not 0 <= max_distance <= 50000 or not math.isfinite(max_hours) or not 0 <= max_hours <= 720:
            raise ValueError
    except (TypeError, ValueError):
        max_distance, max_hours = 500., 24.
    rows = []
    for case in cases:
        evidence = case.evidence if isinstance(case.evidence, dict) else {}
        rows.append({"id": case.id, "domain": case.domain, "asset_id": case.asset_id, "start": evidence.get("start"), "created_at": case.created_at})
    candidates = cross_domain_suggestions(rows, coordinate_assets, max_distance_m=max_distance, max_hours=max_hours)
    return candidates


class AssociationBody(StrictModel):
    status: Literal["accepted", "rejected", "unlinked"]
    expected_status: Literal["suggested", "accepted", "rejected", "unlinked"] | None = None
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Enter at least five non-space characters for the review reason.")
        return value.strip()


@app.patch("/api/v1/associations/{association_id}")
def edit_association(association_id: str, body: AssociationBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    link = db.get(Association, association_id)
    if not link:
        visible = visible_cases(db, user)
        candidate = next((item for item in _cross_domain_suggestions(db, visible) if item["id"] == association_id), None)
        if not candidate:
            raise HTTPException(404, "Association not found or outside your authorized review scope.")
        link = Association(id=association_id, source_id=candidate["source"], target_id=candidate["target"], status="suggested", basis=candidate)
        db.add(link)
        db.flush()
    source, target = case_access(db, user, link.source_id), case_access(db, user, link.target_id)
    before = {"status": link.status}
    basis = link.basis if isinstance(link.basis, dict) else {}
    expected = body.expected_status if body.expected_status is not None else link.status
    changed = db.execute(update(Association).where(Association.id == link.id, Association.status == expected).values(status=body.status, basis={**basis, "review_reason": body.reason}), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This association changed since you opened it. Refresh before reviewing.")
    db.refresh(link)
    for case in (source, target):
        audit(db, user, case, "association_review", body.reason, before, {"status": link.status, "association_id": link.id})
    if body.status == "accepted" and before["status"] != "accepted":
        notify_case(db, source, "Cross-domain case link accepted for coordination", "association:" + link.id)
        notify_case(db, target, "Cross-domain case link accepted for coordination", "association:" + link.id)
    db.commit()
    return serialize_row(link, ["id", "source_id", "target_id", "status", "basis"])


@app.get("/api/v1/search")
def search(q: str = Query(min_length=2, max_length=100), user=Depends(current_user), db=Depends(get_db)):
    needle = q.casefold()
    return {"cases": [serialize_case(c) for c in visible_cases(db, user) if needle in (c.title + " " + c.summary + " " + c.id).casefold()][:30]}


@app.get("/api/v1/impact")
def impact(user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    from datetime import datetime
    allowed = visible_cases(db, user)
    ids = {c.id for c in allowed}
    resolved = [c for c in allowed if c.status == "resolved"]
    response_hours = []
    for case in allowed:
        decision = db.query(Audit).filter(Audit.case_id == case.id, Audit.action.in_(["assignment", "transition", "inspection"])).order_by(Audit.created_at).first()
        if decision:
            response_hours.append(max(0, (datetime.fromisoformat(decision.created_at) - datetime.fromisoformat(case.created_at)).total_seconds() / 3600))
    by_zone = [{"zone": z.name, "open_cases": sum(c.zone_id == z.id and c.status not in {"resolved", "closed"} for c in allowed), "inspected_cases": len({e.case_id for e in db.query(Evidence).filter(Evidence.case_id.in_(ids), Evidence.kind.in_(["inspection", "follow_up"])).all() if any(c.id == e.case_id and c.zone_id == z.id for c in allowed)}), "population_denominator": z.population, "interpretation": "Service disparity requiring investigation; counts alone are not comparable rates."} for z in db.query(Zone).all() if user.role == "admin" or z.id in user.zones]
    water = scope_analytics(latest_analytics(db, "water"), user, db) if user.role == "admin" or "water" in user.domains else {}
    excess = water.get("details", {}).get("estimated_excess")
    return {"estimated_water_excess_litres": excess, "estimated_water_excess_m3": excess / 1000 if isinstance(excess, (int, float)) else None, "human_reviewed_resolutions": len(resolved), "road_repair_cases_resolved": sum(c.domain == "roads" for c in resolved), "collection_cases_resolved": sum(c.domain == "waste" for c in resolved), "first_response_mean_hours": sum(response_hours) / len(response_hours) if response_hours else None, "response_sample_count": len(response_hours), "zones": by_zone, "limitations": ["Observed administrative completions are not independently certified repairs.", "Estimated excess is not verified savings; no causal or emissions impact is claimed.", "Supply-duration and verified-outage denominators are unavailable for this dataset."], "provenance": "Derived", "updated_at": now()}


class FollowupComparisonBody(StrictModel):
    asset_id: str = Field(min_length=1, max_length=100)
    before_start: datetime
    before_end: datetime
    after_start: datetime
    after_end: datetime

    @field_validator("before_start", "before_end", "after_start", "after_end")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Follow-up window timestamps must include a timezone.")
        return value


@app.post("/api/v1/impact/followup")
def compare_impact_followup(body: FollowupComparisonBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    asset = db.get(Asset, body.asset_id)
    if not asset or asset.domain != "water" or not in_scope(user, asset.domain, asset.zone_id):
        raise HTTPException(404, "Water meter not found in the authorized scope.")
    windows = [(body.before_start, body.before_end), (body.after_start, body.after_end)]
    normalized = [(start.astimezone(timezone.utc), end.astimezone(timezone.utc)) for start, end in windows]
    (before_start, before_end), (after_start, after_end) = normalized
    if any(start >= end for start, end in normalized):
        raise HTTPException(422, "Each follow-up window must have a positive duration.")
    if before_end - before_start != after_end - after_start:
        raise HTTPException(422, "Before and after windows must have equal duration for a comparable review.")
    if before_start < after_end and after_start < before_end:
        raise HTTPException(422, "Before and after windows must not overlap.")

    from services.analytics.pipeline import compare_followup
    before, after = [], []
    for reading in db.query(Reading).filter_by(asset_id=asset.id, domain="water").all():
        timestamp = datetime.fromisoformat(reading.timestamp.replace("Z", "+00:00"))
        target = before if before_start <= timestamp.astimezone(timezone.utc) < before_end else after if after_start <= timestamp.astimezone(timezone.utc) < after_end else None
        if target is not None:
            target.append({"active": (reading.original or {}).get("active", True), "asset_id": reading.asset_id, "timestamp": reading.timestamp, "quantity": reading.quantity, "interval_minutes": reading.interval_minutes, "unit": reading.unit, "quality_flag": reading.quality_flag})
    try:
        result = compare_followup(before, after)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result, "asset_id": asset.id, "zone_id": asset.zone_id, "domain": asset.domain, "windows_utc": {"before_start": before_start.isoformat(), "before_end_exclusive": before_end.isoformat(), "after_start": after_start.isoformat(), "after_end_exclusive": after_end.isoformat()}, "window_semantics": "Start inclusive, end exclusive; equal-length windows; valid hourly quantities only.", "provenance": "Derived"}


class ReportLinkBody(StrictModel):
    case_id: str
    reason: str = Field(min_length=5, max_length=2000)


@app.post("/api/v1/reports/{report_id}/link")
def corroborate_report(report_id: str, body: ReportLinkBody, user=Depends(current_user), db=Depends(get_db)):
    require_staff(user)
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    original = case_access(db, user, report.case_id)
    target = case_access(db, user, body.case_id)
    if target.domain != report.domain or target.zone_id != report.zone_id:
        raise HTTPException(422, "Direct corroboration requires the same domain and service zone; use a cross-domain association otherwise.")
    if report.case_id != target.id:
        previous = report.case_id
        report.case_id = target.id
        audit(db, user, original, "report_linked", body.reason, {"report_id": report.id}, {"target_case_id": target.id})
        audit(db, user, target, "report_corroboration", body.reason, {"previous_case_id": previous}, {"report_id": report.id})
        notify_case(db, target, "Citizen observation linked for review", "report:" + report.id)
        db.commit()
    return full_case(db, target, user)


@app.post("/api/v1/scenarios/{job_id}/reset")
def reset_scenario(job_id: str, user=Depends(current_user), db=Depends(get_db)):
    if not DEMO_MODE:
        raise HTTPException(403, "Synthetic reset is disabled outside demo mode.")
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id or job.kind != "scenario" or (job.demo_session_id and job.demo_session_id != getattr(user, "_demo_session_id", None)):
        raise HTTPException(404, "Your scenario run was not found.")
    if job.status != "succeeded":
        raise HTTPException(409, "Wait for this run to finish before resetting it.")
    closed, preserved = [], []
    for case in db.query(Case).filter(Case.event_key.like(f"scenario:{job.id}:%"), Case.demo_owner_id == user.id).all():
        if db.query(Evidence).filter_by(case_id=case.id).first() or db.query(Report).filter_by(case_id=case.id).first():
            preserved.append(case.id)
        elif case.status != "closed":
            mutate_case(db, user, case, case.version, "scenario_reset", "Reset selected synthetic run; baseline and user evidence preserved.", status="closed")
            closed.append(case.id)
    db.commit()
    return {"job_id": job.id, "closed_simulated_cases": closed, "preserved_evidence_cases": preserved, "note": "Only this owned run was reset. Run history, baseline inputs, reports and private evidence remain stored."}


@app.post("/api/v1/demo-session/reset")
def reset_demo_session(request: Request, user=Depends(current_user), db=Depends(get_db)):
    if not DEMO_MODE:
        raise HTTPException(403, "Demo-session reset is disabled outside local demo mode.")
    require_staff(user)
    if user.role != "admin" and not {zone.id for zone in db.query(Zone).all()}.issubset(set(user.zones)):
        raise HTTPException(403, "Resetting a demo session requires all-zone staff access.")
    demo_session_id = request.state.session.demo_session_id
    if not demo_session_id:
        raise HTTPException(409, "This sign-in has no isolated demo-session context. Sign in again from this browser.")
    jobs = db.query(Job).filter_by(kind="scenario", demo_session_id=demo_session_id).all()
    job_ids = [job.id for job in jobs]
    active_job = db.query(Job.id).filter(Job.id.in_(job_ids), Job.status.in_({"running", "pausing"})).first() if job_ids else None
    if active_job:
        raise HTTPException(409, "A scenario is still calculating. Pause or wait for it to finish, then reset this demo session.")
    cleared = db.query(Job).filter(Job.id.in_(job_ids), Job.status.in_({"queued", "paused", "succeeded", "failed"})).update(
        {"status": "reset", "error": "Scenario result cleared by reset of its isolated demo session.", "result": None, "claim_token": None, "lease_until": None, "checkpoint": None, "control_version": Job.control_version + 1, "updated_at": now()},
        synchronize_session=False,
    ) if job_ids else 0
    if job_ids and db.query(Job.id).filter(Job.id.in_(job_ids), Job.status.in_({"running", "pausing"})).first():
        db.rollback()
        raise HTTPException(409, "A scenario began calculating while reset was requested. Pause or wait for it to finish, then retry.")
    cases = db.query(Case).filter(Case.demo_session_id == demo_session_id, Case.event_key.like("scenario:%")).all()
    closed, preserved = [], []
    for case in cases:
        has_evidence = db.query(Evidence.id).filter_by(case_id=case.id).first() is not None
        has_report = db.query(Report.id).filter_by(case_id=case.id).first() is not None
        if has_evidence or has_report or case.status in {"closed", "resolved"}:
            preserved.append(case.id)
            continue
        before = {"status": case.status, "version": case.version}
        changed = db.execute(update(Case).where(Case.id == case.id, Case.version == case.version).values(status="closed", version=case.version + 1, updated_at=now()), execution_options={"synchronize_session": False})
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "A case changed during demo-session reset. Refresh and retry.")
        case.status, case.version, case.updated_at = "closed", case.version + 1, now()
        audit(db, user, case, "demo_session_reset", "Reset the current isolated synthetic demo session; case history and user evidence were preserved.", before=before, after={"status": "closed", "version": case.version})
        notify_case(db, case, f"{case.title}: closed by demo-session reset", f"demo-session-reset:{case.version}")
        closed.append(case.id)
    if job_ids:
        db.query(ScenarioRunPlayback).filter(ScenarioRunPlayback.job_id.in_(job_ids)).update(
            {"status": "paused", "cursor": 0, "last_tick_at": time.time(), "version": ScenarioRunPlayback.version + 1, "updated_at": now()},
            synchronize_session=False,
        )
    audit(db, user, None, "demo_session_reset", "Reset only the current isolated browser demo session.", before={"scenario_jobs": len(jobs)}, after={"cleared_scenario_results": cleared, "closed_cases": len(closed), "preserved_cases": len(preserved), "session_ref": demo_session_id[:12]})
    db.commit()
    return {"status": "reset", "scenario_jobs": len(jobs), "cleared_scenario_results": cleared, "closed_cases": closed, "preserved_cases": preserved, "note": "Only this browser's demo scenarios were reset. Reports, uploaded readings, private evidence, baseline data and unrelated records remain stored."}


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found.")
    dist = ROOT / "apps" / "web" / "dist"
    target = (dist / path).resolve()
    if target.is_relative_to(dist.resolve()) and target.is_file():
        return FileResponse(target)
    if (dist / "index.html").is_file():
        return FileResponse(dist / "index.html")
    return JSONResponse({"service": "CivicSignal 360", "detail": "API is ready. Build the frontend or run its development server.", "docs": "/docs"})
