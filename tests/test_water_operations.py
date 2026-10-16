from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from services.analytics.water_operations import meter_total, schedule_review, water_balance
from services.api.water_operations import ReviewInput, WaterConfiguration


START = datetime(2026, 10, 12, tzinfo=timezone.utc)


def reading(asset="inlet", hour=0, volume=100, **changes):
    return {"id": f"{asset}-{hour}", "asset_id": asset, "timestamp": (START+timedelta(hours=hour)).isoformat(), "interval_minutes": 60, "quantity": volume, "unit": "L", "source": "Synthetic", "quality_flag": "valid", **changes}


def configuration(**changes):
    return WaterConfiguration(version=0, reason="Test configuration", **changes).model_dump(exclude={"reason"})


def test_balance_uses_complete_aligned_intervals_and_storage_sign():
    rows = [reading(), reading("consumer", volume=.06, unit="m3")]
    config = configuration(inlet_ids=["inlet"], consumption_ids=["consumer"], meter_parents={"consumer":"inlet"}, boundary_confirmed=True)
    result = water_balance(rows, config, START, START+timedelta(hours=1), 10, 5)
    assert result["status"] == "ready" and result["unaccounted_l"] == 25
    assert result["closure_eligible"] is False
    result = water_balance(rows, config, START, START+timedelta(hours=1), -10, 5)
    assert result["unaccounted_l"] == 45
    assert water_balance(rows, config, START, START+timedelta(hours=1), 50, 5)["unaccounted_l"] == -15


@pytest.mark.parametrize("rows", [[], [reading(quantity=None)], [reading(quality_flag="invalid")], [reading(interval_minutes=30)], [reading(), reading(hour=.5)], [reading(hour=-.5)], [reading(unit="gallons")]])
def test_gaps_invalid_units_and_overlaps_never_produce_balance(rows):
    config = configuration(inlet_ids=["inlet"], boundary_confirmed=True)
    result = water_balance(rows, config, START, START+timedelta(hours=1), 0, 0)
    assert result["status"] == "insufficient_data" and result["unaccounted_l"] is None


def test_missing_storage_and_unconfirmed_boundary_remain_unknown():
    result = water_balance([reading()], configuration(inlet_ids=["inlet"]), START, START+timedelta(hours=1), None, None)
    assert len(result["issues"]) == 3 and result["unaccounted_l"] is None
    assert meter_total([reading(volume=0)], START, START+timedelta(hours=1))["total_l"] == 0


@pytest.mark.parametrize("values", [dict(inlet_ids=["a","a"]), dict(inlet_ids=["a"], consumption_ids=["a"]), dict(meter_parents={"a":"b","b":"a"}), dict(consumption_ids=["a","b"], meter_parents={"b":"a"}), dict(consumption_ids=["a"],outlet_ids=["b"],meter_parents={"b":"a"}), dict(boundary_confirmed=True)])
def test_invalid_meter_hierarchies_are_rejected(values):
    with pytest.raises(ValidationError):
        configuration(**values)


def test_schedule_uses_timezone_overnight_exceptions_and_partial_intervals():
    config = configuration(supply_windows=[{"days":[0],"start_minute":360,"end_minute":480,"label":"Morning supply"}], exceptions=[{"days":[0],"start_minute":480,"end_minute":540,"label":"Declared refill"}], outside_rate_lph=20)
    # UTC midnight is 05:30 IST and straddles the 06:00 start. No prorated volume.
    assert schedule_review([reading()], config)[0]["status"] == "straddles_window"
    assert schedule_review([reading(hour=1)], config)[0]["status"] == "within_window"
    assert schedule_review([reading(hour=2.5)], config)[0]["status"] == "within_window"
    assert schedule_review([reading(hour=4)], config)[0]["status"] == "review_outside_window"
    assert schedule_review([reading(hour=4,volume=0)], config)[0]["status"] == "below_review_threshold"
    assert schedule_review([reading(quantity=None)], config)[0]["status"] == "data_quality"
    overnight = configuration(timezone="UTC", supply_windows=[{"days":[6],"start_minute":1380,"end_minute":60,"label":"Sunday night"}])
    assert schedule_review([reading()], overnight)[0]["status"] == "within_window"
    assert schedule_review([reading()], configuration())[0]["status"] == "not_configured"


def test_review_requires_aware_times_order_and_accounting_source():
    with pytest.raises(ValidationError):
        ReviewInput(start=START.replace(tzinfo=None), end=START+timedelta(hours=1), configuration_version=0)
    with pytest.raises(ValidationError):
        ReviewInput(start=START, end=START+timedelta(days=32), configuration_version=0)
    with pytest.raises(ValidationError):
        ReviewInput(start=START, end=START+timedelta(hours=1), configuration_version=0, storage_change_l=0)


def test_scoped_persisted_configuration_and_review(login):
    admin, operator, citizen = login("admin"), login("operator"), login("citizen")
    path = "/api/v1/water/zones/river/operations"
    snapshot = admin.get(path).json()
    assert citizen.get(path).status_code == 403
    body = {**snapshot["configuration"], "reason":"Synthetic schedule validation", "supply_windows":[{"days":[0,1,2,3,4,5,6],"start_minute":360,"end_minute":480,"label":"Morning supply"}]}
    assert operator.put(path, json=body).status_code == 403
    response = admin.put(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == body["version"]+1
    assert admin.put(path, json=body).status_code == 409
    assert operator.get(path).json()["configuration"]["supply_windows"] == body["supply_windows"]
    end = datetime.fromisoformat(snapshot["latest_end"])
    review = {"start":(end-timedelta(days=1)).isoformat(),"end":end.isoformat(),"configuration_version":response.json()["version"]}
    result = operator.post("/api/v1/water/zones/river/review", json=review)
    assert result.status_code == 200, result.text
    assert result.json()["schedule"]
    assert result.json()["balance"]["unaccounted_l"] is None
    assert citizen.post("/api/v1/water/zones/river/review", json=review).status_code == 403
    assert operator.get("/api/v1/water/zones/missing/operations").status_code == 404
    review["configuration_version"] -= 1
    assert operator.post("/api/v1/water/zones/river/review", json=review).status_code == 409
    restore={**snapshot["configuration"],"version":response.json()["version"],"reason":"Restore previous test configuration"}
    assert admin.put(path,json=restore).status_code == 200
