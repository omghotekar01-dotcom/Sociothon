"""Repeatable seed: generate measurements, then persist actual model outputs."""
import os
from .database import SessionLocal, init_db
from .models import Asset, Association, Case, Configuration, Connection, ModelRun, Reading, User, Zone
from .security import DEMO_MODE, DOMAINS, hash_password
from .domain import create_finding_case


def ensure_supporting_demo_account(db):
    """Add the second inspector to demo databases without altering existing users."""
    if DEMO_MODE and not db.get(User, "demo-support") and not db.query(User).filter_by(email="support@civicsignal.local").first():
        db.add(User(id="demo-support", name="Kiran • Supporting inspector", email="support@civicsignal.local", password_hash=hash_password("CivicDemo!2026"), role="inspector", domains=DOMAINS, zones=[zone.id for zone in db.query(Zone).all()], settings={"language": "en", "timezone": "Asia/Kolkata", "notifications": True, "display": "dark"}))


def seed_database(db):
    from .baselines import initialize_baselines
    completed = db.get(Configuration, "seed_complete")
    if completed:
        seeded_demo = completed.value.get("mode") == "demo" or completed.value.get("provenance") == "Synthetic"
        if seeded_demo != DEMO_MODE:
            raise RuntimeError("Database mode differs from CIVIC_DEMO_MODE. Use a separate database; demo credentials/data must never be reused in non-demo mode.")
        ensure_supporting_demo_account(db)
        initialize_baselines(db)
        db.commit()
        return
    if not DEMO_MODE:
        admin_email = os.getenv("CIVIC_ADMIN_EMAIL")
        password = os.getenv("CIVIC_ADMIN_PASSWORD")
        if not admin_email or not password or len(password) < 14 or password == "CivicDemo!2026":
            raise RuntimeError("Non-demo setup requires CIVIC_ADMIN_EMAIL and a unique CIVIC_ADMIN_PASSWORD of at least 14 characters.")
        if not db.query(User).filter_by(email=admin_email).first():
            db.add(User(name="Administrator", email=admin_email, password_hash=hash_password(password), role="admin", domains=DOMAINS, zones=[]))
        db.add(Configuration(key="seed_complete", value={"mode": "empty-production"}))
        initialize_baselines(db)
        db.commit()
        return
    from services.analytics.pipeline import bootstrap_dataset
    data = bootstrap_dataset()
    for raw in data["zones"]:
        db.merge(Zone(id=raw["id"], name=raw["name"], population=raw.get("population"), geometry=raw.get("geometry", {k: raw[k] for k in ("x", "y", "polygon") if k in raw})))
    db.flush()
    zone_ids = [z["id"] for z in data["zones"]]
    for role in ("operator", "inspector", "citizen", "admin"):
        email = f"{role}@civicsignal.local"
        if not db.query(User).filter_by(email=email).first():
            db.add(User(id=f"demo-{role}", name={"operator": "Aditi • Operator", "inspector": "Rohan • Inspector", "citizen": "Mira • Citizen", "admin": "Civic Administrator"}[role], email=email, password_hash=hash_password("CivicDemo!2026"), role=role, domains=DOMAINS if role != "citizen" else [], zones=zone_ids if role != "citizen" else [], settings={"language": "en", "timezone": "Asia/Kolkata", "notifications": True, "display": "dark"}))
    ensure_supporting_demo_account(db)
    for raw in data["assets"]:
        db.merge(Asset(id=raw["id"], name=raw["name"], domain="general" if raw.get("domain") == "infrastructure" else raw.get("domain", "water"), zone_id=raw.get("zone_id") or zone_ids[0], kind=raw.get("type", raw.get("kind", "asset")), x=raw.get("x", 0), y=raw.get("y", 0), provenance=raw.get("source", "Synthetic"), properties={k: v for k, v in raw.items() if k not in {"id", "name", "domain", "zone_id", "type", "kind", "x", "y"}}))
    db.flush()
    readings = []
    for raw in data.get("readings", []):
        asset = db.get(Asset, raw["asset_id"])
        readings.append(Reading(id=raw["id"], asset_id=raw["asset_id"], zone_id=raw["zone_id"], domain=raw.get("domain", asset.domain), timestamp=raw["timestamp"], interval_minutes=raw.get("interval_minutes", 60), quantity=raw.get("quantity"), unit=raw["unit"], source=raw.get("source", "Synthetic"), quality_flag=raw.get("quality_flag", "valid"), original=raw))
    db.add_all(readings)
    db.flush()
    for domain, output in data["domains"].items():
        domain = "general" if domain == "infrastructure" else domain
        db.add(ModelRun(domain=domain, dataset_id=str(output.get("dataset_id", "synthetic-360")), model_version=str(output.get("model_version", "civic-analytics-v1")), output=output))
        for finding in output.get("findings", []):
            create_finding_case(db, {**finding, "domain": domain})
    for edge in data.get("network", {}).get("edges", []):
        source, target = edge.get("source"), edge.get("target")
        if db.get(Asset, source) and db.get(Asset, target):
            db.add(Connection(source=source, target=target, length_m=edge.get("length_m", edge.get("length", 100)), kind=edge.get("kind", "topology")))
    finding_cases = {case.evidence.get("finding_id"): case for case in db.query(Case).all()}
    for suggestion in data.get("suggestions", []):
        source, target = finding_cases.get(suggestion["source"]), finding_cases.get(suggestion["target"])
        if source and target:
            first, second = sorted([source.id, target.id])
            db.add(Association(source_id=first, target_id=second, status="suggested", basis=suggestion))
    db.add(Configuration(key="network", value=data.get("network", {})))
    db.add(Configuration(key="platform", value={"timezone": "Asia/Kolkata", "water_tariff_per_m3": None, "electricity_tariff_per_kwh": None, "voltage_lower_v": 207, "voltage_upper_v": 253, "streetlight_on_hour": 18, "streetlight_off_hour": 6, "review_hours": 72, "cross_domain_max_distance_m": 500, "cross_domain_max_hours": 24, "road_priority_weights": {"severity": 35, "extent_m2": 20, "daily_exposure": 20, "repeat_count": 15, "vulnerable_location": 10}, "case_priority_weights": {"severity": 50, "persistence": 10, "exposure": 10, "evidence_diversity": 15, "case_age": 10, "cross_domain_hazard": 5}, "version": "config-1"}))
    db.add(Configuration(key="seed_complete", value={"mode": "demo", "seed": 360, "provenance": "Synthetic"}))
    initialize_baselines(db)
    db.commit()


def main():
    init_db()
    with SessionLocal() as db:
        seed_database(db)


if __name__ == "__main__":
    main()
