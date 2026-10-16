import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String(100), nullable=False)
    email = Column(String(254), unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="citizen")
    domains = Column(JSON, nullable=False, default=list)
    zones = Column(JSON, nullable=False, default=list)
    active = Column(Boolean, nullable=False, default=True)
    settings = Column(JSON, nullable=False, default=dict)
    created_at = Column(String, nullable=False, default=now)


class Session(Base):
    __tablename__ = "sessions"
    token_hash = Column(String, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    csrf = Column(String, nullable=False)
    expires_at = Column(Float, nullable=False)
    demo_session_id = Column(String, index=True)
    created_at = Column(String, default=now, nullable=False)


class DemoSession(Base):
    __tablename__ = "demo_sessions"
    id = Column(String, primary_key=True)
    created_at = Column(String, default=now, nullable=False)
    expires_at = Column(Float, nullable=False)


class Zone(Base):
    __tablename__ = "zones"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    population = Column(Integer)
    geometry = Column(JSON, nullable=False, default=dict)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False, index=True)
    zone_id = Column(ForeignKey("zones.id"), nullable=False)
    kind = Column(String, nullable=False)
    x = Column(Float, default=0)
    y = Column(Float, default=0)
    provenance = Column(String, default="Synthetic", nullable=False)
    properties = Column(JSON, default=dict, nullable=False)


class Connection(Base):
    __tablename__ = "asset_connections"
    id = Column(String, primary_key=True, default=uid)
    source = Column(ForeignKey("assets.id"), nullable=False)
    target = Column(ForeignKey("assets.id"), nullable=False)
    length_m = Column(Float, nullable=False, default=100)
    kind = Column(String, nullable=False, default="topology")
    __table_args__ = (UniqueConstraint("source", "target"),)


class Reading(Base):
    __tablename__ = "readings"
    id = Column(String, primary_key=True)
    asset_id = Column(ForeignKey("assets.id"), nullable=False, index=True)
    zone_id = Column(ForeignKey("zones.id"), nullable=False)
    domain = Column(String, nullable=False)
    timestamp = Column(String, nullable=False, index=True)
    interval_minutes = Column(Float, nullable=False)
    quantity = Column(Float)
    unit = Column(String, nullable=False)
    source = Column(String, nullable=False)
    quality_flag = Column(String, nullable=False)
    original = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("asset_id", "timestamp"),)


class ModelRun(Base):
    __tablename__ = "model_runs"
    id = Column(String, primary_key=True, default=uid)
    domain = Column(String, nullable=False, index=True)
    dataset_id = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    output = Column(JSON, nullable=False)
    created_at = Column(String, default=now, nullable=False)


class BaselineVersion(Base):
    __tablename__ = 'baseline_versions'
    id = Column(String, primary_key=True, default=uid)
    domain = Column(String, nullable=False, index=True)
    algorithm = Column(String, nullable=False)
    parent_id = Column(String)
    status = Column(String, nullable=False, default='pending')
    training = Column(JSON, nullable=False)
    checksum = Column(String, nullable=False)
    train_start = Column(String, nullable=False)
    train_end = Column(String, nullable=False)
    evaluation = Column(JSON, nullable=False, default=dict)
    exclusions = Column(JSON, nullable=False, default=dict)
    created_by = Column(ForeignKey('users.id'))
    reason = Column(Text, nullable=False)
    created_at = Column(String, nullable=False, default=now)


class BaselineDeployment(Base):
    __tablename__ = 'baseline_deployments'
    domain = Column(String, primary_key=True)
    active_id = Column(ForeignKey('baseline_versions.id'))
    version = Column(Integer, nullable=False, default=1)
    history = Column(JSON, nullable=False, default=list)


class Case(Base):
    __tablename__ = "cases"
    id = Column(String, primary_key=True, default=uid)
    event_key = Column(String, unique=True, nullable=False)
    title = Column(String(180), nullable=False)
    domain = Column(String, nullable=False, index=True)
    zone_id = Column(ForeignKey("zones.id"), nullable=False)
    asset_id = Column(ForeignKey("assets.id"))
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False, default="needs_review")
    summary = Column(Text, nullable=False)
    provenance = Column(String, nullable=False)
    priority = Column(Float, nullable=False, default=30)
    evidence = Column(JSON, nullable=False, default=dict)
    assigned_to = Column(ForeignKey("users.id"))
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(String, default=now, nullable=False)
    updated_at = Column(String, default=now, nullable=False)
    deadline_at = Column(String)
    demo_owner_id = Column(ForeignKey("users.id"))
    demo_session_id = Column(String, index=True)
    support_assignments = relationship("CaseInspector", cascade="all, delete-orphan", lazy="selectin")

    @property
    def secondary_assignees(self):
        return sorted(assignment.user_id for assignment in self.support_assignments)


class CaseInspector(Base):
    __tablename__ = "case_inspectors"
    case_id = Column(ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(ForeignKey("users.id"), primary_key=True, index=True)
    created_at = Column(String, default=now, nullable=False)


class Report(Base):
    __tablename__ = "reports"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    case_id = Column(ForeignKey("cases.id"), nullable=False)
    domain = Column(String, nullable=False)
    zone_id = Column(ForeignKey("zones.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    created_at = Column(String, default=now, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)


class Audit(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=uid)
    actor_id = Column(ForeignKey("users.id"))
    case_id = Column(ForeignKey("cases.id"), index=True)
    action = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    before = Column(JSON, nullable=False, default=dict)
    after = Column(JSON, nullable=False, default=dict)
    demo_session_id = Column(String, index=True)
    created_at = Column(String, default=now, nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True, default=uid)
    case_id = Column(ForeignKey("cases.id"), nullable=False, index=True)
    actor_id = Column(ForeignKey("users.id"), nullable=False)
    kind = Column(String, nullable=False)
    notes = Column(Text, nullable=False)
    filename = Column(String)
    mime = Column(String)
    content_hash = Column(String)
    idempotency_key = Column(String)
    checklist = Column(JSON, default=dict, nullable=False)
    observations = Column(JSON, default=dict, nullable=False)
    created_at = Column(String, default=now, nullable=False)
    __table_args__ = (Index("uq_evidence_submission", "case_id", "actor_id", "idempotency_key", unique=True),)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    case_id = Column(ForeignKey("cases.id"))
    dedupe_key = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(String, default=now, nullable=False)


class Configuration(Base):
    __tablename__ = "configuration"
    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)
    version = Column(Integer, default=1, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    demo_session_id = Column(String, index=True)
    kind = Column(String, nullable=False)
    parameters = Column(JSON, default=dict, nullable=False)
    dedupe_key = Column(String, unique=True, nullable=False)
    status = Column(String, default="queued", nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    lease_until = Column(Float)
    claim_token = Column(String)
    checkpoint = Column(JSON)
    control_version = Column(Integer, nullable=False, default=1)
    result = Column(JSON)
    error = Column(String)
    created_at = Column(String, default=now, nullable=False)
    updated_at = Column(String, default=now, nullable=False)


class ScenarioRunPlayback(Base):
    __tablename__ = "scenario_playbacks"
    job_id = Column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    frame_timestamps = Column(JSON, nullable=False, default=list)
    cursor = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="paused")
    speed = Column(Float, nullable=False, default=1.)
    last_tick_at = Column(Float)
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(String, default=now, nullable=False)


class Upload(Base):
    __tablename__ = "uploads"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    checksum = Column(String, nullable=False)
    rows = Column(JSON, nullable=False)
    errors = Column(JSON, nullable=False)
    status = Column(String, default="preview", nullable=False)
    created_at = Column(String, default=now, nullable=False)


class Association(Base):
    __tablename__ = "associations"
    id = Column(String, primary_key=True, default=uid)
    source_id = Column(ForeignKey("cases.id"), nullable=False)
    target_id = Column(ForeignKey("cases.id"), nullable=False)
    status = Column(String, default="suggested", nullable=False)
    basis = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("source_id", "target_id"),)
