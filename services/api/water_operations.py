"""Versioned, zone-scoped water operations with explicit accounting boundaries."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .database import get_db
from .domain import audit, case_access, mutate_case
from .models import Asset, Configuration, Evidence, Reading, Zone, uid, now
from .security import current_user, in_scope, require_admin, require_staff
from services.analytics.water_operations import instant, schedule_review, water_balance
from services.analytics.water_history import historical_schedule_review, compare_meter_group

router = APIRouter(prefix="/api/v1/water")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(Strict):
    days: list[int] = Field(min_length=1, max_length=7)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=0, le=1440)
    label: str = Field(min_length=3, max_length=120)

    @model_validator(mode="after")
    def valid_window(self):
        if len(set(self.days)) != len(self.days) or any(d < 0 or d > 6 for d in self.days):
            raise ValueError("Days must be unique Monday=0 through Sunday=6.")
        if self.start_minute == self.end_minute:
            raise ValueError("Use 00:00–24:00 for an all-day window.")
        return self


class WaterConfiguration(Strict):
    version: int = Field(ge=0)
    timezone: Literal["Asia/Kolkata", "UTC"] = "Asia/Kolkata"
    supply_windows: list[Window] = Field(default_factory=list, max_length=21)
    exceptions: list[Window] = Field(default_factory=list, max_length=21)
    outside_rate_lph: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    inlet_ids: list[str] = Field(default_factory=list, max_length=100)
    outlet_ids: list[str] = Field(default_factory=list, max_length=100)
    consumption_ids: list[str] = Field(default_factory=list, max_length=100)
    meter_parents: dict[str, str] = Field(default_factory=dict, max_length=200)
    boundary_confirmed: bool = False
    reason: str = Field(min_length=5, max_length=2000)

    @model_validator(mode="after")
    def hierarchy(self):
        selected = self.inlet_ids + self.outlet_ids + self.consumption_ids
        if len(selected) != len(set(selected)):
            raise ValueError("Each meter may appear in one accounting role only.")
        for child in self.meter_parents:
            seen, node = {child}, child
            while node in self.meter_parents:
                node = self.meter_parents[node]
                if node in seen:
                    raise ValueError("Meter hierarchy must not contain cycles.")
                seen.add(node)
        # An inlet may be the ancestor of downstream consumption. Inside a summed
        # role, or between the two deducted roles, ancestors would double count.
        for group in (self.inlet_ids, self.outlet_ids + self.consumption_ids):
            for child in group:
                node = child
                while node in self.meter_parents:
                    node = self.meter_parents[node]
                    if node in group:
                        raise ValueError("Do not sum parent and child meters in the same accounting side.")
        if self.boundary_confirmed and not self.inlet_ids:
            raise ValueError("A confirmed boundary requires an inlet meter.")
        return self


def access(db, user, zone_id):
    require_staff(user)
    if not in_scope(user, "water", zone_id) or not db.get(Zone, zone_id):
        raise HTTPException(404, "Water service zone not available.")


def saved(db, zone_id):
    row = db.get(Configuration, "water-operations:" + zone_id)
    return {"version": row.version, **row.value} if row else WaterConfiguration(version=0, reason="Not configured").model_dump(exclude={"reason"})


@router.get("/zones/{zone_id}/operations")
def get_operations(zone_id: str, user=Depends(current_user), db=Depends(get_db)):
    access(db, user, zone_id)
    assets = db.query(Asset).filter_by(zone_id=zone_id, domain="water").all()
    ids = [a.id for a in assets]
    latest = db.query(Reading).filter(Reading.asset_id.in_(ids), Reading.domain == "water").order_by(Reading.timestamp.desc()).first()
    end = (instant(latest.timestamp) + timedelta(minutes=latest.interval_minutes)).isoformat() if latest else None
    return {"zone_id": zone_id, "configuration": saved(db, zone_id), "schedule_history": history(db, zone_id), "assets": [{"id": a.id, "name": a.name, "kind": a.kind, "provenance": a.provenance} for a in assets], "latest_end": end}


@router.put("/zones/{zone_id}/operations")
def save_operations(zone_id: str, body: WaterConfiguration, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    access(db, user, zone_id)
    ids = set(body.inlet_ids + body.outlet_ids + body.consumption_ids + list(body.meter_parents) + list(body.meter_parents.values()))
    for ident in ids:
        asset = db.get(Asset, ident)
        if not asset or asset.domain != "water" or asset.zone_id != zone_id or "meter" not in asset.kind.lower():
            raise HTTPException(422, "Use registered water meters in this service zone.")
    key = "water-operations:" + zone_id
    previous = db.get(Configuration, key)
    value = body.model_dump(exclude={"reason", "version"})
    before = saved(db, zone_id)
    if previous is None:
        if body.version != 0:
            raise HTTPException(409, "Configuration changed. Reload before saving.")
        db.add(Configuration(key=key, value=value, version=1))
    else:
        changed = db.execute(update(Configuration).where(Configuration.key == key, Configuration.version == body.version).values(value=value, version=body.version+1))
        if changed.rowcount != 1:
            raise HTTPException(409, "Configuration changed. Reload before saving.")
    audit(db, user, None, "water_operations_configured", body.reason, before=before, after={"zone_id": zone_id, "version": body.version+1, **value})
    db.commit()
    return saved(db, zone_id)


class ReviewInput(Strict):
    start: datetime
    end: datetime
    configuration_version: int = Field(ge=0)
    storage_change_l: float | None = Field(default=None, allow_inf_nan=False, ge=-1e12, le=1e12)
    authorized_unmetered_l: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1e12)
    accounting_note: str = Field(default="", max_length=2000)
    schedule_mode: Literal["current", "historical"] = "current"
    history_version: int | None = Field(default=None, ge=0)

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Every timestamp must include a timezone.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def window(self):
        if self.schedule_mode == "historical" and self.history_version is None:
            raise ValueError("Select the loaded schedule history version for historical review.")
        if not timedelta(0) < self.end-self.start <= timedelta(days=31):
            raise ValueError("Choose an ordered window of at most 31 days.")
        if (self.storage_change_l is not None or self.authorized_unmetered_l is not None) and len(self.accounting_note.strip()) < 5:
            raise ValueError("Explain the source of supplied storage and authorized-use values.")
        return self


@router.post("/zones/{zone_id}/review")
def review_operations(zone_id: str, body: ReviewInput, user=Depends(current_user), db=Depends(get_db)):
    access(db, user, zone_id)
    config = saved(db, zone_id)
    if body.configuration_version != config["version"]:
        raise HTTPException(409, "Configuration changed. Reload it before reviewing observations.")
    assets = db.query(Asset).filter_by(zone_id=zone_id, domain="water").all()
    meter_ids = [a.id for a in assets if "meter" in a.kind.lower()]
    # Query with a one-day margin; valid input intervals cannot exceed one day.
    readings = db.query(Reading).filter(Reading.asset_id.in_(meter_ids), Reading.domain == "water", Reading.timestamp >= (body.start-timedelta(days=1)).isoformat(), Reading.timestamp < body.end.isoformat()).order_by(Reading.timestamp, Reading.id).limit(10001).all()
    if len(readings) > 10000:
        raise HTTPException(422, "This review exceeds 10,000 input observations. Choose a shorter window.")
    rows = [{key: getattr(r, key) for key in ("id", "asset_id", "timestamp", "interval_minutes", "quantity", "unit", "source", "quality_flag")} for r in readings]
    selected = [r for r in rows if instant(r["timestamp"]) >= body.start]
    recorded = history(db, zone_id) if body.schedule_mode == "historical" else None
    if recorded is not None and recorded["version"] != body.history_version:
        raise HTTPException(409, "Schedule history changed. Reload before reviewing observations.")
    schedule = historical_schedule_review(selected, recorded["entries"]) if recorded is not None else schedule_review(selected, config)
    balance = water_balance(rows, config, body.start, body.end, body.storage_change_l, body.authorized_unmetered_l)
    result = {"schema": "water_operations_review_v1", "zone_id": zone_id, "configuration_version": config["version"], "window": {"start": body.start.isoformat(), "end_exclusive": body.end.isoformat()}, "schedule": schedule,
            "schedule_counts": {state: sum(r["status"] == state for r in schedule) for state in sorted({r["status"] for r in schedule})},
            "balance": balance, "accounting_input_provenance": "User-supplied; not independently verified", "accounting_note": body.accounting_note,
            "configuration_snapshot": config, "schedule_mode": body.schedule_mode, "schedule_history_snapshot": recorded,
            "schedule_provenance": "Administrator-recorded effective periods; not independently verified supply" if recorded is not None else "Current configuration; not evidence of the historical schedule",
            "accounting_boundary_provenance": "Current reviewed configuration; historical schedule selection does not change meter roles or storage inputs",
            "review_inputs": body.model_dump(mode="json"), "source_observations": rows, "requires_human_review": True}
    return {**result, "snapshot_hash": fingerprint(result)}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def history(db, zone_id):
    row = db.get(Configuration, "water-schedule-history:" + zone_id)
    return {"version": row.version, "entries": row.value["entries"]} if row else {"version": 0, "entries": []}


def save_history(db, user, zone_id, previous, entries, action, reason, record_id):
    key = "water-schedule-history:" + zone_id
    value = {"entries": entries}
    if previous["version"] == 0:
        db.add(Configuration(key=key, version=1, value=value))
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Schedule history changed. Reload before saving.") from exc
    else:
        changed = db.execute(update(Configuration).where(Configuration.key == key, Configuration.version == previous["version"]).values(value=value, version=previous["version"]+1))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Schedule history changed. Reload before saving.")
    audit(db, user, None, action, reason, before={"zone_id": zone_id, "history_version": previous["version"]}, after={"record_id": record_id, "history_version": previous["version"]+1})
    db.commit()
    return history(db, zone_id)


class HistoryInput(Strict):
    version: int = Field(ge=0)
    configuration_version: int = Field(ge=1)
    effective_from: datetime
    effective_until: datetime
    source_reference: str = Field(min_length=5, max_length=500)
    reason: str = Field(min_length=5, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("effective_from", "effective_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Effective dates require explicit timezones.")
        return value.astimezone(timezone.utc)

    @field_validator("source_reference", "reason")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Supply a meaningful source reference and reason.")
        return value.strip()

    @model_validator(mode="after")
    def ordered(self):
        if not timedelta(0) < self.effective_until-self.effective_from <= timedelta(days=3660):
            raise ValueError("Choose an ordered effective period of at most ten years.")
        return self


@router.post("/zones/{zone_id}/schedule-history")
def record_schedule(zone_id: str, body: HistoryInput, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    access(db, user, zone_id)
    previous = history(db, zone_id)
    request_hash = fingerprint(body.model_dump(mode="json"))
    for entry in previous["entries"]:
        if entry["actor_id"] == user.id and entry["idempotency_key"] == body.idempotency_key:
            if entry["request_hash"] != request_hash:
                raise HTTPException(409, "This submission identifier belongs to another schedule record.")
            return previous
    config = saved(db, zone_id)
    if previous["version"] != body.version or config["version"] != body.configuration_version:
        raise HTTPException(409, "Configuration or schedule history changed. Reload before saving.")
    if not config["supply_windows"]:
        raise HTTPException(422, "Save a supply schedule before recording its effective period.")
    if len(previous["entries"]) >= 200:
        raise HTTPException(422, "This prototype supports up to 200 retained history records per zone.")
    if any(not e.get("revoked_at") and instant(e["effective_from"]) < body.effective_until and instant(e["effective_until"]) > body.effective_from for e in previous["entries"]):
        raise HTTPException(409, "Effective periods must not overlap. Revoke an incorrect record before replacing it.")
    entry = {"id": uid(), **body.model_dump(mode="json", exclude={"version", "reason"}), "reason": body.reason,
             "actor_id": user.id, "recorded_at": now(), "request_hash": request_hash,
             "schedule": {key: config[key] for key in ("timezone", "supply_windows", "exceptions", "outside_rate_lph")}}
    return save_history(db, user, zone_id, previous, [*previous["entries"], entry], "water_schedule_recorded", body.reason, entry["id"])


class RevokeHistoryInput(Strict):
    version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Explain the correction.")
        return value.strip()


@router.post("/zones/{zone_id}/schedule-history/{record_id}/revoke")
def revoke_schedule(zone_id: str, record_id: str, body: RevokeHistoryInput, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    access(db, user, zone_id)
    previous = history(db, zone_id)
    entry = next((e for e in previous["entries"] if e["id"] == record_id), None)
    if not entry:
        raise HTTPException(404, "Schedule history record not found.")
    if previous["version"] != body.version:
        raise HTTPException(409, "Schedule history changed. Reload before correcting it.")
    if entry.get("revoked_at"):
        return previous
    entries = [{**e, "revoked_at": now(), "revoked_by": user.id, "revocation_reason": body.reason} if e["id"] == record_id else e for e in previous["entries"]]
    return save_history(db, user, zone_id, previous, entries, "water_schedule_revoked", body.reason, record_id)


class GroupComparisonInput(Strict):
    configuration_version: int = Field(ge=1)
    meter_ids: list[str] = Field(min_length=1, max_length=50)
    before_start: datetime
    before_end: datetime
    after_start: datetime
    after_end: datetime
    independent_meters_confirmed: Literal[True]
    context_note: str = Field(min_length=5, max_length=2000)

    @field_validator("before_start", "before_end", "after_start", "after_end")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Comparison boundaries require explicit timezones.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def valid(self):
        duration = self.before_end-self.before_start
        if not timedelta(0) < duration <= timedelta(days=31) or self.after_end-self.after_start != duration or self.after_start < self.before_end:
            raise ValueError("Choose equal, ordered, non-overlapping windows of at most 31 days each.")
        if len(set(self.meter_ids)) != len(self.meter_ids):
            raise ValueError("Select each meter once.")
        if len(self.context_note.strip()) < 5:
            raise ValueError("Document the comparison assumptions.")
        return self


@router.post("/zones/{zone_id}/impact-comparison")
def compare_group(zone_id: str, body: GroupComparisonInput, user=Depends(current_user), db=Depends(get_db)):
    access(db, user, zone_id)
    config = saved(db, zone_id)
    if body.configuration_version != config["version"]:
        raise HTTPException(409, "Configuration changed. Reload before comparing meters.")
    if not config["boundary_confirmed"]:
        raise HTTPException(422, "An administrator must confirm the accounting boundary first.")
    selected = set(body.meter_ids)
    roles = [role for role in ("inlet_ids", "outlet_ids", "consumption_ids") if selected <= set(config[role])]
    if len(roles) != 1:
        raise HTTPException(422, "Select meters from one accounting role; do not combine inlet, outlet and consumption volumes.")
    # Validate again against the current registry and hierarchy, including legacy config.
    WaterConfiguration(**config, reason="Validate comparison boundary")
    for ident in selected:
        asset = db.get(Asset, ident)
        if not asset or asset.domain != "water" or asset.zone_id != zone_id or "meter" not in asset.kind.lower():
            raise HTTPException(422, "Use registered water meters in this service zone.")
    windows = [(body.before_start, body.before_end), (body.after_start, body.after_end)]
    sources = []
    for start, end in windows:
        records = db.query(Reading).filter(Reading.asset_id.in_(selected), Reading.domain == "water", Reading.timestamp >= (start-timedelta(days=1)).isoformat(), Reading.timestamp < end.isoformat()).order_by(Reading.timestamp, Reading.id).limit(10001).all()
        if len(records) > 10000:
            raise HTTPException(422, "More than 10,000 input observations in a comparison window. Select fewer meters or a shorter window.")
        sources.append([{key: getattr(r, key) for key in ("id", "asset_id", "timestamp", "interval_minutes", "quantity", "unit", "source", "quality_flag")} for r in records])
    result = {**compare_meter_group(*sources, body.meter_ids, *windows[0], *windows[1]), "zone_id": zone_id, "role": roles[0],
              "configuration_snapshot": config, "inputs": body.model_dump(mode="json"), "source_observations": {"before": sources[0], "after": sources[1]},
              "schema": "water_meter_group_comparison_v1", "schedule_history_snapshot": history(db, zone_id),
              "provenance": "Derived from recorded observations; selected meter independence and operating context are user-confirmed, not independently verified"}
    return {**result, "snapshot_hash": fingerprint(result)}


class AttachReviewInput(Strict):
    review: ReviewInput
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Explain why this review is relevant to the case.")
        return value.strip()


@router.post("/zones/{zone_id}/cases/{case_id}/reviews")
def attach_review(zone_id: str, case_id: str, body: AttachReviewInput, user=Depends(current_user), db=Depends(get_db)):
    access(db, user, zone_id)
    case = case_access(db, user, case_id)
    if case.domain != "water" or case.zone_id != zone_id:
        raise HTTPException(422, "Choose a water case in this review's service zone.")
    request_hash = fingerprint(body.model_dump(mode="json"))
    previous = db.query(Evidence).filter_by(case_id=case_id, actor_id=user.id, idempotency_key=body.idempotency_key).first()
    if previous:
        if previous.kind != "water_review" or previous.content_hash != request_hash:
            raise HTTPException(409, "This submission identifier already belongs to different evidence.")
        return {"evidence_id": previous.id, "case_id": case.id, "case_version": case.version, "snapshot_hash": body.snapshot_hash, "duplicate": True}
    if case.status in {"resolved", "closed"}:
        raise HTTPException(409, "Reopen this case through human review before attaching new evidence.")
    if case.version != body.case_version:
        raise HTTPException(409, "This case changed. Refresh the case before attaching the review.")
    # Recompute on the server: never trust a browser-supplied analysis or silently
    # replace the reviewed result with newer readings/configuration.
    snapshot = review_operations(zone_id, body.review, user, db)
    if snapshot["snapshot_hash"] != body.snapshot_hash:
        raise HTTPException(409, "The source observations or configuration changed. Run and review the analysis again.")
    record = Evidence(id=uid(), case_id=case.id, actor_id=user.id, kind="water_review", notes=body.reason,
                      observations={"water_review": snapshot}, content_hash=request_hash, idempotency_key=body.idempotency_key)
    mutate_case(db, user, case, body.case_version, "water_review_attached", body.reason, evidence_ids=[record.id],
                audit_after={"snapshot_hash": snapshot["snapshot_hash"], "configuration_version": snapshot["configuration_version"], "window": snapshot["window"]})
    db.add(record)
    db.commit()
    return {"evidence_id": record.id, "case_id": case.id, "case_version": case.version, "snapshot_hash": snapshot["snapshot_hash"], "duplicate": False}
