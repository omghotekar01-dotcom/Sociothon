from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.api.database import Base
from services.api.models import Association, Case, Configuration, Evidence, Report, User, Zone
from services.api.priorities import (
    DEFAULT_CASE_PRIORITY_WEIGHTS,
    case_priority_reviews,
    validate_case_priority_weights,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Zone(id="zone-a", name="Test zone", population=1000))
        session.add(Configuration(key="platform", value={"case_priority_weights": dict(DEFAULT_CASE_PRIORITY_WEIGHTS)}, version=4))
        session.commit()
        yield session
    engine.dispose()


def add_case(db, ident="case-a", *, domain="water", severity="high", evidence=None, created=None, status="needs_review", asset=None):
    created = created or datetime(2026, 10, 14, tzinfo=timezone.utc)
    stamp = created.isoformat()
    case = Case(
        id=ident, event_key=ident, title=ident, domain=domain, zone_id="zone-a", asset_id=asset,
        severity=severity, status=status, summary="Recorded observation", provenance="Reported",
        priority=0, evidence=evidence or {}, created_at=stamp, updated_at=stamp,
        deadline_at=(created + timedelta(hours=72)).isoformat(),
    )
    db.add(case)
    db.flush()
    return case


def add_user(db, ident):
    user = User(id=ident, name=ident, email=f"{ident}@example.test", password_hash="unused", role="citizen", domains=[], zones=[])
    db.add(user)
    db.flush()
    return user


def test_weight_validation_requires_exact_supported_keys_and_100_points():
    assert validate_case_priority_weights(dict(DEFAULT_CASE_PRIORITY_WEIGHTS)) == DEFAULT_CASE_PRIORITY_WEIGHTS
    with pytest.raises(ValueError):
        validate_case_priority_weights({**DEFAULT_CASE_PRIORITY_WEIGHTS, "extra": 0})
    with pytest.raises(ValueError):
        validate_case_priority_weights({**DEFAULT_CASE_PRIORITY_WEIGHTS, "severity": 49})


def test_review_explains_factors_counts_unique_reporters_and_keeps_urgency_separate(db):
    created = datetime(2026, 10, 14, tzinfo=timezone.utc)
    case = add_case(db, evidence={"start": created.isoformat(), "end": (created + timedelta(hours=72)).isoformat(), "inspection": {"daily_exposure": 5000}}, created=created)
    first = add_user(db, "reporter-a")
    second = add_user(db, "reporter-b")
    for actor, key in ((first, "one"), (first, "two"), (second, "three")):
        db.add(Report(user_id=actor.id, case_id=case.id, domain="water", zone_id="zone-a", title="Observation", description="Reported", location="zone-a", idempotency_key=key))
    inspector = add_user(db, "inspector-a")
    db.add(Evidence(case_id=case.id, actor_id=inspector.id, kind="inspection", notes="Field check"))
    db.add(Evidence(case_id=case.id, actor_id=inspector.id, kind="photograph", notes="Photo"))
    db.flush()

    review = case_priority_reviews(db, [case], at=datetime(2026, 10, 15, tzinfo=timezone.utc))[case.id]

    assert review["components"]["severity"]["value"] == 75
    assert review["components"]["persistence"]["value"] == 100
    assert review["components"]["exposure"]["value"] == 50
    assert review["components"]["evidence_diversity"]["value"] == pytest.approx(200 / 3, abs=0.01)
    assert review["evidence_quality"]["unique_reporters"] == 2
    assert review["urgency"]["score"] == 75
    assert review["configuration_version"] == 4
    assert review["score"] == pytest.approx(64.17, abs=0.01)
    assert "do not prove a physical fault" in review["evidence_quality"]["assessment"]


def test_missing_observations_are_listed_and_never_imputed(db):
    case = add_case(db, evidence={})
    review = case_priority_reviews(db, [case])[case.id]

    assert review["components"]["persistence"]["value"] is None
    assert review["components"]["exposure"]["value"] is None
    assert {"persistence", "exposure"}.issubset(review["missing"])
    assert review["components"]["persistence"]["contribution"] == 0


def test_closed_cases_stop_accruing_age_but_severity_urgency_remains_visible(db):
    case = add_case(db, severity="critical", status="resolved", evidence={})
    review = case_priority_reviews(db, [case], at=datetime(2030, 1, 1, tzinfo=timezone.utc))[case.id]
    assert review["components"]["case_age"]["value"] == 0
    assert review["urgency"] == {"severity": "critical", "score": 100, "review_required": False}


def test_only_visible_accepted_cross_domain_links_contribute(db):
    left = add_case(db, "water-case", domain="water", severity="high")
    right = add_case(db, "power-case", domain="electricity", severity="critical")
    db.add(Association(source_id=left.id, target_id=right.id, status="accepted", basis={"reason": "same service zone"}))
    db.flush()

    hidden = case_priority_reviews(db, [left], visible_case_ids={left.id})[left.id]
    visible = case_priority_reviews(db, [left, right], visible_case_ids={left.id, right.id})[left.id]

    assert hidden["components"]["cross_domain_hazard"]["value"] == 0
    assert visible["components"]["cross_domain_hazard"]["value"] == 50
    assert visible["components"]["cross_domain_hazard"]["contribution"] == 2.5


def test_priority_weights_are_frozen_per_case_when_admin_config_changes(db):
    frozen = {"severity": 100, "persistence": 0, "exposure": 0, "evidence_diversity": 0, "case_age": 0, "cross_domain_hazard": 0}
    case = add_case(db, severity="critical", evidence={"priority_configuration": {"weights": frozen, "version": 2}})
    config = db.get(Configuration, "platform")
    config.value = {"case_priority_weights": dict(DEFAULT_CASE_PRIORITY_WEIGHTS)}
    config.version = 9
    db.flush()
    review = case_priority_reviews(db, [case])[case.id]

    assert review["configuration_version"] == 2
    assert review["score"] == 100
    assert review["weights"] == frozen
