from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api.main import FollowupComparisonBody, compare_impact_followup
from services.analytics.pipeline import CLOCK


class Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter_by(self, **filters):
        self.rows = [row for row in self.rows if all(getattr(row, key) == value for key, value in filters.items())]
        return self

    def all(self):
        return self.rows


class Database:
    def __init__(self, asset, readings):
        self.asset = asset
        self.readings = readings

    def get(self, model, ident):
        return self.asset if ident == self.asset.id else None

    def query(self, model):
        return Query(self.readings)


def windows():
    before_start = CLOCK - timedelta(days=14)
    before_end = before_start + timedelta(hours=24)
    after_start = CLOCK - timedelta(days=7)
    after_end = after_start + timedelta(hours=24)
    return before_start, before_end, after_start, after_end


def test_scoped_followup_uses_equal_length_windows_and_never_claims_savings():
    asset = SimpleNamespace(id="water-river", domain="water", zone_id="river")
    before_start, before_end, after_start, after_end = windows()
    readings = []
    for start, quantity in ((before_start, 100), (after_start, 70)):
        for hour in range(24):
            readings.append(SimpleNamespace(id=f"{start.date()}-{hour}", asset_id=asset.id, domain="water", timestamp=(start + timedelta(hours=hour)).isoformat(), quantity=quantity, interval_minutes=60, unit="L", quality_flag="valid", original={}))
    body = FollowupComparisonBody(asset_id=asset.id, before_start=before_start, before_end=before_end, after_start=after_start, after_end=after_end)
    user = SimpleNamespace(role="operator", domains=["water"], zones=["river"])

    result = compare_impact_followup(body, user, Database(asset, readings))

    assert result["status"] == "comparison_available"
    assert result["paired_hours"] == 24
    assert result["coverage"] == 1
    assert result["observed_change"] == 720
    assert result["closure_eligible"] is False and result["requires_human_review"] is True
    assert "not causally proven savings" in result["interpretation"]
    assert result["provenance"] == "Derived"
    windows_utc = result["windows_utc"]
    assert datetime.fromisoformat(windows_utc["before_end_exclusive"]) - datetime.fromisoformat(windows_utc["before_start"]) == timedelta(hours=24)
    assert datetime.fromisoformat(windows_utc["after_end_exclusive"]) - datetime.fromisoformat(windows_utc["after_start"]) == timedelta(hours=24)


def test_followup_rejects_out_of_scope_assets_and_noncomparable_windows():
    asset = SimpleNamespace(id="water-river", domain="water", zone_id="river")
    before_start, before_end, after_start, after_end = windows()
    body = FollowupComparisonBody(asset_id=asset.id, before_start=before_start, before_end=before_end, after_start=after_start, after_end=after_end)
    unauthorized = SimpleNamespace(role="operator", domains=["water"], zones=["market"])
    with pytest.raises(HTTPException) as denied:
        compare_impact_followup(body, unauthorized, Database(asset, []))
    assert denied.value.status_code == 404

    overlap = FollowupComparisonBody(asset_id=asset.id, before_start=before_start, before_end=before_end, after_start=before_start + timedelta(hours=12), after_end=before_start + timedelta(hours=36))
    authorized = SimpleNamespace(role="operator", domains=["water"], zones=["river"])
    with pytest.raises(HTTPException) as invalid:
        compare_impact_followup(overlap, authorized, Database(asset, []))
    assert invalid.value.status_code == 422


def test_followup_requires_timezone_in_every_window():
    aware = windows()
    values = dict(zip(("before_start", "before_end", "after_start", "after_end"), aware))
    values["after_end"] = values["after_end"].replace(tzinfo=None)
    with pytest.raises(ValueError, match="include a timezone"):
        FollowupComparisonBody(asset_id="water-river", **values)
