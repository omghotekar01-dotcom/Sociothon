from copy import deepcopy
from datetime import timedelta
import json
import pandas as pd
import pytest
from services.analytics.pipeline import (CLOCK, SCENARIOS, analyze_consumption, analyze_streetlights, bootstrap_dataset, compare_followup, forecast_consumption, generate_consumption, generate_domain_inputs, group_events, network_data, network_path, normalize_readings, plan_road_budget, plan_waste_collection, road_priority, run_scenario, simulate_drainage, simulate_tank, streetlight_expected, time_to_capacity)

@pytest.fixture(scope="module")
def healthy_water():
    return generate_consumption("water", seed=927, anomalies=False)[0]

def test_units_missing_zero_and_timezone(healthy_water):
    rows = deepcopy(healthy_water[:3])
    rows[0].update(quantity=1.2, unit="m3")
    rows[1].update(quantity=None, quality_flag="missing")
    rows[2].update(quantity=0, quality_flag="valid")
    frame = normalize_readings(rows, "water")
    assert frame.iloc[0]["quantity"] == 1200
    assert str(frame.iloc[0]["timestamp"].tz) == "UTC"
    assert pd.isna(frame.iloc[1]["quantity"])
    assert frame.iloc[2]["quantity"] == 0 and frame.iloc[2]["valid"]
    empty = analyze_consumption([], "water")
    assert empty["quality"]["status"] == "insufficient_data"
    assert empty["quality"]["coverage"] is None and empty["quality"]["stale"] is None
    rows[0]["timestamp"] = "2026-10-01T00:00:00"
    with pytest.raises(ValueError): normalize_readings(rows, "water")

def test_cumulative_counters_are_rejected_with_interval_guidance(healthy_water):
    counter = deepcopy(healthy_water[0])
    counter["format"] = "cumulative"
    with pytest.raises(ValueError, match="Cumulative counters are unsupported; supply interval quantities"):
        normalize_readings([counter], "water")

def test_future_observations_do_not_change_fitted_baseline(healthy_water):
    original = analyze_consumption(healthy_water, "water")
    modified = deepcopy(healthy_water)
    for row in modified:
        if pd.Timestamp(row["timestamp"]) >= CLOCK - timedelta(hours=6):
            row["quantity"] += 900
    changed = analyze_consumption(modified, "water", tariff=2.5)
    earlier = {r["id"]:r for r in original["_rows"]}
    assert all(r["expected"] == earlier[r["id"]]["expected"] for r in changed["_rows"])
    assert not [f for f in original["findings"] if "sensor_quality" not in f["reason_codes"]]
    assert any(f["estimated_excess"] for f in changed["findings"])
    assert changed["details"]["estimated_excess"] == pytest.approx(sum(f["estimated_excess"] or 0 for f in changed["findings"]))
    assert changed["details"]["estimated_excess_m3"] == pytest.approx(changed["details"]["estimated_excess"] / 1000)
    assert changed["details"]["estimated_cost"] == pytest.approx(changed["details"]["estimated_excess_m3"] * 2.5)
    assert changed["details"]["cost_status"] == "Configured tariff estimate"
    assert original["details"]["estimated_cost"] is None
    assert original["details"]["cost_status"] == "No tariff configured"

def test_missing_rows_reduce_coverage_and_are_not_leaks(healthy_water):
    sparse = [r for r in healthy_water if not (r["asset_id"] == "water-river" and pd.Timestamp(r["timestamp"]) >= CLOCK-timedelta(hours=18))]
    result = analyze_consumption(sparse, "water", observation_end=CLOCK.isoformat())
    asset = next(r for r in result["quality"]["assets"] if r["asset_id"] == "water-river")
    assert asset["coverage"] <= .25 and asset["stale"]
    assert any("sensor_quality" in f["reason_codes"] for f in result["findings"])

def test_one_inactive_reading_is_explicit_even_above_coverage_threshold(healthy_water):
    rows = deepcopy(healthy_water)
    target = next(row for row in reversed(rows) if row["asset_id"] == "water-river")
    target["active"] = False
    result = analyze_consumption(rows, "water", observation_end=CLOCK.isoformat())
    status = next(row for row in result["quality"]["assets"] if row["asset_id"] == "water-river")
    assert status["coverage"] > .8 and not status["stale"]
    assert status["inactive"] == 1
    assert status["status"] == result["quality"]["status"] == "degraded"
    assert "inactive reading(s)" in " ".join(status["notes"])
    assert result["quality"]["inactive"] == 1
    assert any(f["asset_id"] == "water-river" and "sensor_quality" in f["reason_codes"] for f in result["findings"])

def test_irregular_sampling_is_reported_as_quality_not_consumption_fault(healthy_water):
    rows = deepcopy(healthy_water)
    target = next(row for row in reversed(rows) if row["asset_id"] == "water-river")
    target["interval_minutes"] = 30
    result = analyze_consumption(rows, "water", observation_end=CLOCK.isoformat())
    status = next(row for row in result["quality"]["assets"] if row["asset_id"] == "water-river")
    assert status["irregular_sampling"]
    assert status["status"] == "degraded"
    quality_findings = [f for f in result["findings"] if f["asset_id"] == "water-river" and "sensor_quality" in f["reason_codes"]]
    assert quality_findings
    assert all(f["estimated_excess"] is None for f in quality_findings)

def test_good_recent_coverage_does_not_hide_insufficient_model_history(healthy_water):
    cutoff = CLOCK - timedelta(days=10)
    rows = [row for row in healthy_water if row["asset_id"] == "water-river" and pd.Timestamp(row["timestamp"]) >= cutoff]
    result = analyze_consumption(rows, "water", observation_end=CLOCK.isoformat())
    status = result["quality"]["assets"][0]
    assert status["coverage"] >= .8 and status["status"] == "ready"
    assert status["analysis_status"] == "insufficient_data"
    assert "14 days" in status["analysis_reason"]

def test_grouping_is_contiguous_idempotent_and_counts_interval_volume_once():
    rows = [{"id":str(i),"asset_id":"water-river","zone_id":"river","timestamp":(CLOCK+timedelta(hours=i)).isoformat(),"interval_minutes":60,"actual":200,"expected":100,"threshold":20,"flag":True,"robust_flag":True,"isolation_flag":False,"reason":"sustained_excess","unit":"L"} for i in range(4)]
    events = group_events(rows, "water")
    assert events == group_events(rows, "water")
    assert len(events) == 1 and events[0]["estimated_excess"] == 400
    rows[1]["actual"], rows[1]["flag"] = None, False
    assert not group_events(rows, "water")

@pytest.mark.parametrize("params", [dict(capacity_l=100,initial_l=20,inflow_lph=0,outflow_lph=30,hours=3),dict(capacity_l=100,initial_l=90,inflow_lph=50,outflow_lph=0,hours=3),dict(hours=3.5,dt_hours=.7)])
def test_tank_conservation_and_capacity(params):
    out = simulate_tank(**params)
    assert abs(out["conservation_error_l"]) < 1e-6
    assert 0 <= out["final_l"] <= out["capacity_l"]
    assert all(0 <= row["level_l"] <= out["capacity_l"] for row in out["series"])
    if params.get("outflow_lph") == 0: assert out["depletion_hours"] is None and out["spilled_l"] > 0
    if params.get("inflow_lph") == 0: assert out["unmet_demand_l"] > 0

def test_drainage_conservation_and_missing_input():
    out = simulate_drainage(rainfall_mmph=70, blockage=.9)
    assert abs(out["conservation_error_m3"]) < 1e-6 and out["overflow_m3"] > 0
    assert simulate_drainage(rainfall_mmph=None)["status"] == "insufficient_data"
    with pytest.raises(ValueError): simulate_drainage(blockage=1.1)

def test_road_budget_and_missing_cost_are_explicit():
    rows = generate_domain_inputs()["roads"]
    rows[0]["cost"] = None
    result = plan_road_budget(rows, budget=65000)
    assert result["spent"] <= 65000
    assert sum(r["cost"] for r in result["selected"]) == result["spent"]
    assert any(r["reason"] == "No configured cost estimate" for r in result["excluded"])
    assert "extent_m2" in road_priority({"id":"incomplete","severity":4})["missing_inputs"]

def test_road_priority_weights_are_validated_and_replayed():
    weights = {"severity": 60, "extent_m2": 10, "daily_exposure": 10, "repeat_count": 10, "vulnerable_location": 10}
    row = generate_domain_inputs()["roads"][0]
    default_score = road_priority(row)["score"]
    configured = road_priority(row, weights)
    assert configured["weights"] == weights
    assert configured["score"] != default_score
    replay = run_scenario("roads", "pothole", {"seed": 721, "priority_weights": weights, "priority_weights_version": 7})
    assert replay["metadata"]["parameters"]["priority_weights"] == weights
    assert replay["metadata"]["parameters"]["priority_weights_version"] == 7
    assert replay["baseline"]["details"]["priorities"][0]["weights"] == weights
    with pytest.raises(ValueError, match="total 100"):
        road_priority(row, {**weights, "severity": 59})

def test_waste_capacity_constraints_and_nonincreasing_fill():
    result = plan_waste_collection(generate_domain_inputs()["waste"], vehicle_capacity_l=900)
    assert any("exceeds" in r["reason"] for r in result["excluded"])
    assert all(trip["load_l"] <= 900 for trip in result["trips"])
    result = time_to_capacity([{"timestamp":CLOCK.isoformat(),"volume_l":500},{"timestamp":(CLOCK+timedelta(hours=1)).isoformat(),"volume_l":200}],1000)
    assert result.get("hours_to_capacity") is None

def test_streetlight_local_schedule():
    assert streetlight_expected("2026-10-13T15:00:00Z")
    assert not streetlight_expected("2026-10-13T06:00:00Z")

def test_streetlight_recurrence_counts_separate_schedule_mismatch_episodes():
    rows = []
    for day in (14, 15):
        for hour, on in ((18, False), (19, False), (20, False), (21, True)):
            stamp = f"2026-10-{day:02d}T{hour:02d}:00:00+05:30"
            rows.append({"asset_id": "lamp-river-1", "zone_id": "river", "timestamp": stamp,
                         "on": on, "source": "Synthetic"})

    result = analyze_streetlights(rows)
    events = [finding for finding in result["findings"] if "suspected_nighttime_failure" in finding["reason_codes"]]

    assert len(events) == 2
    assert all("recurring_pattern" in event["reason_codes"] for event in events)
    assert all(event["evidence"]["recurrence_episode_count"] == 2 for event in events)
    assert all(event["evidence"]["recurring"] for event in events)

def test_streetlight_flicker_pattern_requires_explicit_rapid_state_changes():
    start = pd.Timestamp("2026-10-15T19:00:00+05:30")
    rows = [{"asset_id": "lamp-river-1", "zone_id": "river",
             "timestamp": (start + pd.Timedelta(minutes=5 * index)).isoformat(),
             "on": state, "source": "Uploaded"}
            for index, state in enumerate((True, False, True, False))]

    result = analyze_streetlights(rows)
    flicker = [finding for finding in result["findings"] if "suspected_flicker_pattern" in finding["reason_codes"]]

    assert len(flicker) == 1
    assert flicker[0]["evidence"]["state_transitions"] == 3
    assert flicker[0]["evidence"]["source"] == "Uploaded"
    assert "does not establish" in flicker[0]["evidence"]["next_action"]

    hourly = [{**row, "timestamp": (start + pd.Timedelta(hours=index)).isoformat()}
              for index, row in enumerate(rows)]
    assert not [finding for finding in analyze_streetlights(hourly)["findings"]
                if "suspected_flicker_pattern" in finding["reason_codes"]]

def test_streetlight_scenario_uses_the_configured_schedule():
    result = run_scenario("streetlights", "failed_lamp", {"seed": 721, "on_hour": 17, "off_hour": 7})

    assert result["baseline"]["details"]["on_hour"] == 17
    assert result["baseline"]["details"]["off_hour"] == 7
    assert result["metadata"]["parameters"]["on_hour"] == 17

def test_streetlight_staleness_uses_observation_age_separately_from_missing_state():
    end = pd.Timestamp(CLOCK)
    old_rows = [{"asset_id": "lamp-river-1", "zone_id": "river",
                 "timestamp": (end - pd.Timedelta(hours=hours)).isoformat(),
                 "on": streetlight_expected((end - pd.Timedelta(hours=hours)).isoformat())}
                for hours in (4, 3)]
    stale = analyze_streetlights(old_rows, observation_end=end.isoformat())
    assert stale["quality"]["stale"] is True
    assert stale["quality"]["assets"][0]["observation_age_hours"] == 3
    assert any("stale_observation" in row["reason_codes"] for row in stale["findings"])

    recent_rows = [{"asset_id": "lamp-river-1", "zone_id": "river",
                    "timestamp": (end - pd.Timedelta(hours=hours)).isoformat(),
                    "on": None if hours == 1 else streetlight_expected((end - pd.Timedelta(hours=hours)).isoformat())}
                   for hours in (3, 2, 1)]
    fresh_but_missing = analyze_streetlights(recent_rows, observation_end=end.isoformat())
    assert fresh_but_missing["quality"]["stale"] is False
    assert fresh_but_missing["quality"]["assets"][0]["missing_state_intervals_24h"] == 1
    assert any("missing_state" in row["reason_codes"] for row in fresh_but_missing["findings"])

    with pytest.raises(ValueError, match="observation_end requires timezone"):
        analyze_streetlights(recent_rows, observation_end="2026-10-13T00:00:00")

def test_topology_closure_and_hydraulic_boundary():
    network = network_data()
    first = network["edges"][0]
    original = network_path(first["source"], first["target"])
    assert original["connected"] and original["hydraulic_result"] == "Hydraulic result unavailable"
    changed = network_path(first["source"], first["target"], [e["id"] for e in network["edges"]])
    assert not changed["connected"]

def test_forecast_backtest_and_insufficient_history(healthy_water):
    # The forecast explicitly supports a single meter, avoiding duplicate
    # timestamps and accidental aggregation of meter hierarchies.
    assert forecast_consumption(healthy_water,"water")["status"] == "insufficient_data"
    meter_rows = [r for r in healthy_water if r["asset_id"] == "water-river"]
    result = forecast_consumption(meter_rows,"water",horizon=72)
    assert result["status"] == "ready"
    assert result["method"] == "Weekly seasonal naive (same hour seven days earlier)"
    assert result["metrics"]["mae"] >= 0
    assert result["metrics"]["rmse"] >= result["metrics"]["mae"]
    assert 0 <= result["metrics"]["interval_coverage"] <= 1
    assert result["metrics"]["calibration_samples"] == 168
    assert result["metrics"]["test_samples"] == 168
    assert result["splits"]["calibration_start"] < result["splits"]["calibration_end_exclusive"]
    assert result["splits"]["calibration_end_exclusive"] == result["splits"]["test_start"]
    assert result["splits"]["test_start"] < result["splits"]["test_end_exclusive"]
    assert len(result["points"]) == 72
    assert len(result["daily"]) == 3
    assert result["daily"][0]["expected"] == pytest.approx(sum(point["expected"] for point in result["points"][:24]))
    assert result["daily_metrics"]["test_days"] == 7
    assert result["daily_metrics"]["calibration_days"] == 7
    assert 0 <= result["daily_metrics"]["interval_coverage"] <= 1
    assert result["weekly_comparison"]["previous_week_total"] is not None
    assert result["weekly_comparison"]["latest_week_total"] is not None
    assert result["weekly_comparison"]["coverage"] == 1
    assert result["enhanced_model"]["status"] == "computed"
    assert result["enhanced_model"]["fit_rows"] >= 28 * 24
    assert result["enhanced_model"]["calibration_rows"] == 168
    assert result["enhanced_model"]["test_rows"] == 168
    assert result["enhanced_model"]["metrics"]["baseline_mae_same_rows"] >= 0
    assert "Comparison only" in result["enhanced_model"]["selection"]
    shorter = forecast_consumption(meter_rows[:40 * 24],"water")
    assert shorter["status"] == "ready"
    assert shorter["enhanced_model"]["status"] == "not_evaluated"
    assert forecast_consumption(healthy_water[:24],"water")["status"] == "insufficient_data"

def test_forecast_holdout_does_not_calibrate_its_own_interval(healthy_water):
    rows = deepcopy([r for r in healthy_water if r["asset_id"] == "water-river"])
    reference = forecast_consumption(rows,"water")
    holdout_start = pd.Timestamp(reference["splits"]["test_start"])
    for row in rows:
        if pd.Timestamp(row["timestamp"]) >= holdout_start:
            row["quantity"] += 10000
    shifted = forecast_consumption(rows,"water")
    assert shifted["splits"]["calibration_end_exclusive"] == shifted["splits"]["test_start"]
    assert shifted["prediction_interval_radius"] == reference["prediction_interval_radius"]
    assert shifted["metrics"]["interval_coverage"] < reference["metrics"]["interval_coverage"]

def test_scenario_replay_is_deterministic_and_counterfactual():
    one = run_scenario("roads","budget",{"seed":721,"budget":65000})
    two = run_scenario("roads","budget",{"seed":721,"budget":65000})
    assert one == two
    assert one["metadata"]["provenance"] == "Simulated"
    json.dumps(one,allow_nan=False)

@pytest.mark.parametrize("domain,scenario",[(domain,scenario) for domain,scenarios in SCENARIOS.items() if domain not in {"water","electricity"} for scenario in scenarios])
def test_secondary_domain_scenarios_compute_strict_json(domain,scenario):
    result = run_scenario(domain,scenario)
    assert "comparison" in result and "baseline" in result
    json.dumps(result,allow_nan=False)

def test_followup_never_claims_automatic_closure():
    before = [{"timestamp":(CLOCK-timedelta(days=14)+timedelta(hours=i)).isoformat(),"quantity":100,"interval_minutes":60} for i in range(48)]
    after = [{"timestamp":(CLOCK-timedelta(days=7)+timedelta(hours=i)).isoformat(),"quantity":70,"interval_minutes":60} for i in range(48)]
    result = compare_followup(before,after)
    assert result["closure_eligible"] is False
    assert result.get("observed_change",0)>0
    assert compare_followup(before[::6],after[::6])["status"] == "insufficient_followup"
