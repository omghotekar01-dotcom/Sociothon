from datetime import datetime, timedelta, timezone

from services.analytics.pipeline import analyze_consumption


def readings(missing_timestamp=None):
    end = datetime(2026, 10, 8, tzinfo=timezone.utc)
    start = end - timedelta(days=7)
    rows = []
    for index in range(7 * 24):
        stamp = start + timedelta(hours=index)
        if stamp == missing_timestamp:
            continue
        rows.append({"id": f"energy-{index}", "asset_id": "electricity-market", "zone_id": "river",
                     "timestamp": stamp.isoformat(), "interval_minutes": 60, "quantity": 2.0,
                     "unit": "kWh", "source": "Uploaded", "quality_flag": "valid"})
    return rows, end


def test_load_profile_uses_weighted_kwh_and_complete_days_with_configured_tariff():
    rows, end = readings()
    result = analyze_consumption(rows, "electricity", observation_end=end.isoformat(), tariff=8)

    profile = result["details"]["load_profile"]
    midnight = next(row for row in profile["hourly_average_power"] if row["hour_ist"] == 5)
    full_day = next(row for row in profile["complete_daily_energy"] if row["coverage"] == 1)
    cost = result["details"]["energy_cost_estimate"]

    assert profile["timezone"] == "Asia/Kolkata"
    assert midnight["average_power_kw"] == 2
    assert midnight["coverage"] == 1
    assert full_day["complete_day_kwh"] == 48
    assert cost["observed_kwh"] == 336
    assert cost["coverage"] == 1
    assert cost["observed_interval_cost_inr"] == 2688
    assert "not a utility bill" in cost["basis"]


def test_missing_interval_reduces_coverage_and_never_fills_daily_total_or_cost():
    rows, end = readings(datetime(2026, 10, 6, 7, tzinfo=timezone.utc))
    result = analyze_consumption(rows, "electricity", observation_end=end.isoformat(), tariff=8)

    profile = result["details"]["load_profile"]
    missing_hour = next(row for row in profile["hourly_average_power"] if row["hour_ist"] == 12)
    day = next(row for row in profile["complete_daily_energy"] if row["date"] == "2026-10-06")
    cost = result["details"]["energy_cost_estimate"]

    assert abs(missing_hour["coverage"] - 6 / 7) < 1e-5
    assert abs(day["coverage"] - 23 / 24) < 1e-5
    assert day["complete_day_kwh"] is None
    assert cost["coverage"] < 1
    assert cost["observed_kwh"] == 334
    assert cost["observed_interval_cost_inr"] == 2672


def test_explicit_power_and_current_quality_are_independent_and_zero_is_measured():
    rows, end = readings()
    for row in rows:
        row.update({"power_kw": 2.4, "power_unit": "kW", "current_a": 8., "current_unit": "A"})
    rows[-1]["power_kw"] = 0.
    rows[-1]["current_a"] = 0.
    result = analyze_consumption(rows, "electricity", observation_end=end.isoformat())
    quality = result["quality"]["assets"][0]

    assert quality["power_kw"]["status"] == "ready"
    assert quality["current_a"]["status"] == "ready"
    assert quality["power_kw"]["missing"] == 0

    for row in rows[-3:]:
        row.pop("power_kw")
        row.pop("power_unit")
        row.pop("current_a")
        row.pop("current_unit")
    degraded = analyze_consumption(rows, "electricity", observation_end=end.isoformat())["quality"]["assets"][0]
    assert degraded["power_kw"]["status"] == "degraded"
    assert degraded["power_kw"]["missing"] == 3
    assert degraded["current_a"]["status"] == "degraded"


def test_blank_optional_csv_cells_are_missing_not_invalid_measurements():
    rows, end = readings()
    for row in rows:
        row.update({"voltage": "   ", "voltage_unit": "  ", "power_kw": "", "power_unit": "",
                    "current_a": "", "current_unit": ""})

    result = analyze_consumption(rows, "electricity", observation_end=end.isoformat())
    quality = result["quality"]["assets"][0]

    assert quality["voltage"]["status"] == "not_provided"
    assert quality["power_kw"]["status"] == "not_provided"
    assert quality["current_a"]["status"] == "not_provided"
