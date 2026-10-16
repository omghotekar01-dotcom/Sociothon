from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from services.api.main import ConfigBody, admin_config
from services.analytics.pipeline import CLOCK, analyze_consumption, generate_consumption, run_scenario


@pytest.fixture(scope="module")
def electricity_meter():
    readings, _ = generate_consumption("electricity", seed=821, days=56, anomalies=False)
    return [row for row in readings if row["asset_id"] == "electricity-market"]


def voltage_findings(result):
    return [finding for finding in result["findings"] if "voltage_observation" in finding["reason_codes"]]


def test_voltage_out_of_range_requires_three_contiguous_explicit_measurements(electricity_meter):
    two = deepcopy(electricity_meter)
    for row in two[-2:]:
        row["voltage"] = 195
    assert voltage_findings(analyze_consumption(two, "electricity")) == []

    three = deepcopy(electricity_meter)
    for row in three[-3:]:
        row["voltage"] = 195
    result = analyze_consumption(three, "electricity")
    finding, = voltage_findings(result)
    assert finding["evidence"]["voltage_min_v"] == 195
    assert finding["evidence"]["configured_range_v"] == [207, 253]
    assert finding["evidence"]["intervals"] == 3
    assert finding["estimated_excess"] is None
    assert "Qualified utility inspection" in finding["evidence"]["next_action"]


def test_thresholds_are_configurable_and_invalid_bounds_are_rejected(electricity_meter):
    rows = deepcopy(electricity_meter)
    for row in rows[-3:]:
        row["voltage"] = 209
    assert voltage_findings(analyze_consumption(rows, "electricity")) == []
    result = analyze_consumption(rows, "electricity", voltage_lower_v=210, voltage_upper_v=250)
    finding, = voltage_findings(result)
    assert finding["evidence"]["configured_range_v"] == [210, 250]
    assert result["details"]["voltage_monitoring"]["thresholds"] == {
        "lower": 210, "upper": 250, "unit": "V",
        "basis": "Illustrative configurable observation thresholds, not regulatory certification",
    }
    with pytest.raises(ValueError, match="lower < upper"):
        analyze_consumption(rows, "electricity", voltage_lower_v=250, voltage_upper_v=210)


def test_admin_configuration_persists_thresholds_and_rejects_inversion(monkeypatch):
    config = SimpleNamespace(version=1, value={"voltage_lower_v": 207, "voltage_upper_v": 253, "streetlight_on_hour": 18, "streetlight_off_hour": 6})

    class Database:
        def get(self, model, key):
            assert key == "platform"
            return config

        def commit(self):
            pass

    monkeypatch.setattr("services.api.main.audit", lambda *_args, **_kwargs: None)
    admin = SimpleNamespace(role="admin")
    road_weights = {"severity": 50, "extent_m2": 15, "daily_exposure": 15, "repeat_count": 10, "vulnerable_location": 10}
    case_weights = {"severity": 40, "persistence": 15, "exposure": 10, "evidence_diversity": 15, "case_age": 10, "cross_domain_hazard": 10}
    saved = admin_config(ConfigBody(version=1, reason="Set illustrative voltage and priority bounds", voltage_lower_v=215, voltage_upper_v=245, streetlight_on_hour=17, streetlight_off_hour=7, cross_domain_max_distance_m=250, cross_domain_max_hours=3, road_priority_weights=road_weights, case_priority_weights=case_weights), admin, Database())
    assert saved["value"]["voltage_lower_v"] == 215
    assert saved["value"]["voltage_upper_v"] == 245
    assert saved["value"]["streetlight_on_hour"] == 17
    assert saved["value"]["streetlight_off_hour"] == 7
    assert saved["value"]["cross_domain_max_distance_m"] == 250
    assert saved["value"]["cross_domain_max_hours"] == 3
    assert saved["value"]["road_priority_weights"] == road_weights
    assert saved["value"]["case_priority_weights"] == case_weights
    assert saved["version"] == 2

    with pytest.raises(HTTPException) as invalid:
        admin_config(ConfigBody(version=2, reason="Set invalid voltage bounds", voltage_lower_v=250, voltage_upper_v=210), admin, Database())
    assert invalid.value.status_code == 422

    with pytest.raises(HTTPException) as invalid_schedule:
        admin_config(ConfigBody(version=2, reason="Set invalid lamp schedule", streetlight_on_hour=7, streetlight_off_hour=7), admin, Database())
    assert invalid_schedule.value.status_code == 422

    with pytest.raises(HTTPException) as invalid_weights:
        admin_config(ConfigBody(version=2, reason="Set invalid road priority weights", road_priority_weights={**road_weights, "severity": 49}), admin, Database())
    assert invalid_weights.value.status_code == 422

    with pytest.raises(HTTPException) as invalid_case_weights:
        admin_config(ConfigBody(version=2, reason="Set invalid shared priority weights", case_priority_weights={**case_weights, "severity": 39}), admin, Database())
    assert invalid_case_weights.value.status_code == 422


def test_missing_or_stale_voltage_is_quality_not_an_inferred_condition(electricity_meter):
    absent = deepcopy(electricity_meter)
    for row in absent:
        row.pop("voltage", None)
    no_voltage = analyze_consumption(absent, "electricity")
    assert no_voltage["details"]["voltage_monitoring"]["status"] == "not_provided"
    assert no_voltage["quality"]["assets"][0]["voltage"]["stale"] is None
    assert voltage_findings(no_voltage) == []

    stale = deepcopy(electricity_meter)
    for row in stale:
        if pd.Timestamp(row["timestamp"]) >= CLOCK - pd.Timedelta(hours=3):
            row.pop("voltage", None)
    result = analyze_consumption(stale, "electricity")
    quality = result["quality"]["assets"][0]["voltage"]
    assert quality["status"] == "degraded" and quality["stale"] is True
    assert quality["missing"] == 3
    assert voltage_findings(result) == []


def test_zero_energy_is_not_voltage_or_outage_evidence(electricity_meter):
    rows = deepcopy(electricity_meter)
    for row in rows[-3:]:
        row["quantity"] = 0
    result = analyze_consumption(rows, "electricity")
    assert voltage_findings(result) == []
    low = next(f for f in result["findings"] if "unexpected_low_flow" in f["reason_codes"])
    assert "within the illustrative configured band" in low["evidence"]["voltage_assessment"]
    assert "does not prove an outage" in low["evidence"]["explanation"]


def test_measured_zero_voltage_and_reported_outage_remain_distinct(electricity_meter):
    rows = deepcopy(electricity_meter)
    for row in rows[-3:]:
        row["voltage"] = 0
    result = analyze_consumption(rows, "electricity")
    finding, = voltage_findings(result)
    assert finding["evidence"]["voltage_min_v"] == 0

    fluctuation = run_scenario("electricity", "voltage_fluctuation", {"asset_id": "electricity-market", "seed": 821, "hours": 6})
    simulated, = voltage_findings(fluctuation)
    assert simulated["evidence"]["intervals"] == 6
    assert simulated["evidence"]["source"] == "Simulated"

    outage = run_scenario("electricity", "reported_outage", {"asset_id": "electricity-market", "seed": 821, "hours": 6})
    assert "unverified until inspection" in outage["details"]["outage_context"]
    assert not voltage_findings(outage)
    assert outage["details"]["voltage_monitoring"]["status"] == "ready"
