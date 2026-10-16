from types import SimpleNamespace

from services.api.main import latest_analytics, scope_analytics
from services.api.baselines import registered_meters
from services.api.models import Asset, BaselineDeployment, ModelRun, Zone
from services.analytics.pipeline import analyze_consumption, generate_consumption


class Query:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def filter_by(self, **filters):
        self.rows = [row for row in self.rows if all(getattr(row, key, None) == value for key, value in filters.items())]
        return self

    def order_by(self, *_):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class Database:
    def __init__(self, zones=(), deployments=(), runs=(), assets=()):
        self.zones = list(zones)
        self.deployments = list(deployments)
        self.runs = list(runs)
        self.assets = list(assets)

    def get(self, model, _):
        if model is BaselineDeployment:
            return self.deployments[0] if self.deployments else None
        return None

    def query(self, model):
        if model is Zone:
            return Query(self.zones)
        if model is ModelRun:
            return Query(self.runs)
        if model is Asset:
            return Query(self.assets)
        raise AssertionError(f"Unexpected query model: {model}")


def test_missing_published_analysis_does_not_claim_freshness():
    output = latest_analytics(Database(), "water")
    assert output["quality"]["status"] == "not_evaluated"
    assert output["quality"]["coverage"] is None
    assert output["quality"]["stale"] is None
    assert output["evaluation"]["status"] == "not_evaluated"


def test_unpromoted_baseline_has_explicit_quality_state():
    deployment = SimpleNamespace(active_id=None)
    output = latest_analytics(Database(deployments=[deployment]), "water")
    assert output["quality"]["status"] == "not_evaluated"
    assert output["forecast"]["status"] == "insufficient_data"
    assert "promote a baseline" in output["evaluation"]["reason"]


def test_restricted_quality_aggregate_uses_authorized_zones_only():
    zones = [SimpleNamespace(id="river"), SimpleNamespace(id="market")]
    user = SimpleNamespace(role="operator", zones=["river"])
    source = {
        "domain": "water",
        "series": [],
        "findings": [],
        "quality": {
            "coverage": .4,
            "assets": [
                {"zone_id": "river", "coverage": .4, "missing": 14.4, "invalid": 1, "inactive": 1, "stale": True, "status": "degraded", "notes": ["river-only warning"]},
                {"zone_id": "market", "coverage": 1., "missing": 0, "invalid": 0, "inactive": 0, "stale": False, "status": "ready", "notes": ["market-only note"]},
            ],
        },
    }
    output = scope_analytics(source, user, Database(zones=zones))
    quality = output["quality"]
    assert quality["status"] == "degraded"
    assert quality["coverage"] == .4
    assert quality["invalid"] == quality["inactive"] == 1
    assert quality["stale"] is True
    assert quality["assets"] == source["quality"]["assets"][:1]
    assert "river-only warning" in quality["notes"]
    assert "market-only note" not in quality["notes"]


def test_registered_meter_with_no_rows_is_reported_without_guessing_staleness():
    assets = [
        SimpleNamespace(id="water-river", domain="water", zone_id="river", kind="District meter", properties={"unit": "L"}),
        SimpleNamespace(id="water-unknown", domain="water", zone_id="market", kind="District meter", properties={"unit": "L"}),
        SimpleNamespace(id="water-valve", domain="water", zone_id="market", kind="Valve", properties={}),
    ]
    db = Database(assets=assets)
    expected = registered_meters(db, "water")
    assert {asset["id"] for asset in expected} == {"water-river", "water-unknown"}

    readings = generate_consumption("water", seed=927, anomalies=False)[0]
    result = analyze_consumption(readings, "water", expected_assets=expected)
    status = next(asset for asset in result["quality"]["assets"] if asset["asset_id"] == "water-unknown")
    finding = next(finding for finding in result["findings"] if finding["asset_id"] == "water-unknown")
    assert status["no_readings"] and status["coverage"] == 0 and status["missing"] == 24
    assert status["status"] == "degraded" and status["stale"] is None
    assert status["analysis_status"] == "insufficient_data"
    assert result["quality"]["status"] == "degraded" and result["quality"]["stale"] is None
    assert finding["reason_codes"] == ["sensor_quality"] and finding["estimated_excess"] is None
    assert "last-seen time are unknown" in finding["evidence"]["explanation"]
