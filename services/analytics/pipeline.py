"""CivicSignal 360 analytics: historical-fit detection and bounded planning models.

Timestamps are UTC interval starts. Consumption is an interval quantity, never a
cumulative counter. Ground truth is returned separately by the synthetic generator
and is never passed to the detector. Synthetic results are investigation support.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

MODEL_VERSION = "seasonal-mad-iforest-1.1"
CONFIG_VERSION = "civic-rules-1.1"
ROAD_PRIORITY_WEIGHTS = {"severity": 35, "extent_m2": 20, "daily_exposure": 20, "repeat_count": 15, "vulnerable_location": 10}
SEED = 360
CLOCK = datetime(2026, 10, 13, 0, tzinfo=timezone.utc)
DOMAINS = ("water", "electricity", "roads", "drainage", "waste", "streetlights", "general")
ZONES = [
    {"id": "river", "name": "River Ward", "x": 28, "y": 38, "lat": 18.526, "lon": 73.852, "households": 420, "source": "Synthetic"},
    {"id": "market", "name": "Market Ward", "x": 63, "y": 47, "lat": 18.523, "lon": 73.858, "households": 680, "source": "Synthetic"},
    {"id": "hill", "name": "Hill Ward", "x": 48, "y": 76, "lat": 18.517, "lon": 73.855, "households": 310, "source": "Synthetic"},
]


def safe(value: Any) -> Any:
    """Convert NumPy/Pandas values and non-finite values to strict JSON types."""
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [safe(v) for v in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return round(float(value), 5) if math.isfinite(value) else None
    return value


def identity(*parts: Any) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


def asset_registry() -> list[dict]:
    asset_types = {"water": "District meter", "electricity": "Feeder meter", "roads": "Road segment", "drainage": "Catchment drain", "waste": "Collection bin", "streetlights": "Lighting circuit", "general": "Public facility"}
    units = {"water": "L", "electricity": "kWh", "roads": "score", "drainage": "m³", "waste": "L", "streetlights": "state", "general": "score"}
    result = []
    for d, domain in enumerate(DOMAINS):
        for zone in ZONES:
            result.append({"id": f"{domain}-{zone['id']}", "name": f"{zone['name']} {asset_types[domain].lower()}", "domain": domain, "zone_id": zone["id"], "type": asset_types[domain], "x": zone["x"] + (d % 3 - 1) * 5, "y": zone["y"] + (d // 3 - 1) * 5, "lat": zone["lat"] + d * .00012, "lon": zone["lon"] + d * .00012, "source": "Synthetic", "unit": units[domain], "department": domain, "active": True})
    return result


def generate_consumption(domain: str, seed: int = SEED, days: int = 56,
                         anomalies: bool = True) -> tuple[list[dict], list[dict]]:
    """Fixed-seed hourly data. Labels are a separate return value, never a column.

    Daily/weekly demand plus independent Gaussian variation; actual faults only
    appear in the final seven-day evaluation block. Declared scheduled demand
    changes are legitimate input context, not hidden anomaly labels.
    """
    if domain not in ("water", "electricity") or days < 1 or days > 365:
        raise ValueError("Expected water/electricity and 1–365 days")
    rng = np.random.default_rng(seed + (101 if domain == "electricity" else 0))
    count = days * 24
    start = CLOCK - timedelta(hours=count)
    readings, labels = [], []
    for z, zone in enumerate(ZONES):
        for i in range(count):
            stamp = start + timedelta(hours=i)
            # Local clock is explicit; timestamps remain UTC.
            local = stamp + timedelta(hours=5, minutes=30)
            hour = local.hour
            base = (190 + z * 55) if domain == "water" else (3.1 + z * .8)
            profile = .52 + .62 * math.exp(-((hour - 8) / 2.6) ** 2) + .8 * math.exp(-((hour - 19) / 3.5) ** 2)
            week = 1.12 if local.weekday() >= 5 else 1.0
            quantity = max(0, base * profile * week + rng.normal(0, base * .035))
            multiplier = 1.0
            # Publicly declared market operating window: expected demand scales.
            if z == 1 and count - 38 <= i < count - 35:
                multiplier = 1.65
                quantity *= multiplier
            truth, reason = False, None
            if anomalies:
                if domain == "water" and z == 0 and i >= count - 12:
                    quantity += 270
                    truth, reason = True, "overnight_excess"
                elif domain == "electricity" and z == 1 and i >= count - 9:
                    quantity += 3.4
                    truth, reason = True, "sustained_excess"
                elif z == 2 and count - 50 <= i < count - 45:
                    quantity = 0
                    truth, reason = True, "unexpected_low_flow"
            missing = anomalies and z == 2 and i >= count - 5
            reading_id = identity(domain, zone["id"], stamp.isoformat())
            reading = {"id": reading_id, "asset_id": f"{domain}-{zone['id']}", "meter_id": f"{domain}-{zone['id']}", "domain": domain, "zone_id": zone["id"], "timestamp": safe(stamp), "interval_minutes": 60, "quantity": None if missing else round(quantity, 4), "unit": "L" if domain == "water" else "kWh", "source": "Synthetic", "quality_flag": "missing" if missing else "valid", "expected_multiplier": multiplier, "active": True}
            if domain == "electricity":
                reading["voltage"] = round(230 + rng.normal(0, 1.8), 2)
                reading["voltage_unit"] = "V"
            readings.append(reading)
            labels.append({"reading_id": reading_id, "anomaly": bool(truth and not missing), "reason": reason, "quality_failure": missing})
    return readings, labels


def normalize_readings(readings: list[dict], domain: str) -> pd.DataFrame:
    """Validate without coercing missing or invalid observations into zero."""
    if domain not in ("water", "electricity"):
        raise ValueError("Consumption analysis supports water or electricity")
    rows = []
    unit_factors = {"L": 1., "litres": 1., "m3": 1000., "m³": 1000.} if domain == "water" else {"kWh": 1., "Wh": .001}
    for index, original in enumerate(readings):
        item = dict(original)
        # CSV rows retain optional telemetry columns even when the cells are
        # blank. Normalize those blanks to missing observations so they do not
        # become false invalid measurements during quality assessment.
        for field in ("voltage", "power_kw", "current_a"):
            value = item.get(field)
            if isinstance(value, str) and not value.strip():
                item[field] = np.nan
        for field in ("voltage_unit", "power_unit", "current_unit"):
            value = item.get(field)
            if isinstance(value, str):
                item[field] = value.strip() or None
        if not item.get("asset_id") or not item.get("zone_id"):
            raise ValueError(f"Reading {index}: asset_id and zone_id are required")
        if item.get("format", "interval") != "interval":
            raise ValueError("Cumulative counters are unsupported; supply interval quantities")
        raw_stamp = item.get("timestamp")
        try:
            stamp = pd.Timestamp(raw_stamp)
            if pd.isna(stamp) or stamp.tzinfo is None:
                raise ValueError()
            stamp = stamp.tz_convert("UTC")
        except (ValueError, TypeError):
            raise ValueError(f"Reading {index}: timestamp requires an explicit timezone") from None
        interval = float(item.get("interval_minutes", 0))
        if not math.isfinite(interval) or interval <= 0 or interval > 1440:
            raise ValueError(f"Reading {index}: interval must be greater than zero and at most 1440 minutes")
        unit = item.get("unit")
        if unit not in unit_factors:
            raise ValueError(f"Reading {index}: unsupported unit {unit!r}")
        raw = item.get("quantity")
        invalid = False
        if raw is None or raw == "":
            quantity = np.nan
        else:
            try:
                quantity = float(raw) * unit_factors[unit]
                invalid = not math.isfinite(quantity) or quantity < 0
            except (ValueError, TypeError):
                quantity, invalid = np.nan, True
        if invalid or item.get("quality_flag") in ("invalid", "missing"):
            quantity = np.nan
        inactive = item.get("active", True) is False
        if inactive:
            quantity = np.nan
        local = stamp.tz_convert("Asia/Kolkata")
        multiplier = float(item.get("expected_multiplier", 1.0))
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("Expected multiplier must be positive and finite")
        rows.append({**item, "timestamp": stamp, "quantity": quantity, "rate": quantity * 60 / interval, "interval_minutes": interval, "hour": local.hour, "weekday": local.dayofweek, "slot": local.dayofweek * 24 + local.hour, "expected_multiplier": multiplier, "invalid": invalid or item.get("quality_flag") == "invalid", "inactive": inactive, "valid": bool(math.isfinite(quantity)), "supply_expected": bool(item.get("supply_expected", True)), "id": item.get("id", identity(item.get("asset_id"), stamp.isoformat()))})
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values(["asset_id", "timestamp"]).reset_index(drop=True)
    if frame.duplicated(["asset_id", "timestamp"]).any():
        raise ValueError("Duplicate asset timestamps; deduplicate before analysis")
    for _, group in frame.groupby("asset_id"):
        ends = group["timestamp"] + pd.to_timedelta(group["interval_minutes"], unit="m")
        if (group["timestamp"].iloc[1:].reset_index(drop=True) < ends.iloc[:-1].reset_index(drop=True)).any():
            raise ValueError("Overlapping reading intervals are unsupported")
    return frame


def _features(group: pd.DataFrame, expected: np.ndarray, scale: np.ndarray) -> np.ndarray:
    rate = group["rate"].to_numpy(dtype=float)
    adjusted = rate / group["expected_multiplier"].to_numpy()
    residual = (adjusted - expected) / scale
    lag = np.r_[adjusted[0], adjusted[:-1]]
    return np.nan_to_num(np.column_stack((adjusted / np.maximum(expected, .01), residual, (adjusted - lag) / scale, np.sin(2 * np.pi * group["hour"] / 24), np.cos(2 * np.pi * group["hour"] / 24), group["weekday"] / 6.)), nan=0., posinf=0., neginf=0.)


def group_events(rows: list[dict], domain: str, min_intervals: int = 3,
                 gap_tolerance: int = 0, min_duration_hours: float = 3) -> list[dict]:
    """Three consecutive qualifying hourly intervals; one valid recovery closes.

    Missing readings always break an event. Default gap tolerance is zero;
    timestamps must also be contiguous, so absent rows cannot bridge faults.
    Event IDs do not depend on analysis run ID, preserving retry idempotency.
    """
    if min_intervals < 1 or gap_tolerance < 0 or min_duration_hours < 0:
        raise ValueError("Invalid event grouping parameters")
    result, current, gaps = [], [], 0

    def finish() -> None:
        qualifying = [r for r in current if r.get("flag")]
        duration = sum(r["interval_minutes"] for r in qualifying) / 60
        if len(qualifying) < min_intervals or duration < min_duration_hours:
            return
        first, last = qualifying[0], qualifying[-1]
        excess = sum(max((r["actual"] or 0) - (r["expected"] or 0), 0) for r in qualifying)
        low = all(r.get("reason") == "unexpected_low_flow" for r in qualifying)
        reasons = sorted({r.get("reason", "sustained_excess") for r in qualifying})
        observed = sum(r["actual"] for r in qualifying)
        expected = sum(r["expected"] for r in qualifying)
        evidence = {"observed": observed, "expected": expected, "excess": excess, "interval_count": len(qualifying), "duration_hours": duration, "threshold": first["threshold"], "robust_intervals": sum(r["robust_flag"] for r in qualifying), "isolation_forest_intervals": sum(r["isolation_flag"] for r in qualifying), "source": first.get("source", "Derived"), "model_version": MODEL_VERSION, "explanation": "Observed interval quantities exceed their historical time-of-week baseline for a persistent window." if not low else "Consumption is below its expected operating baseline. A zero reading alone does not prove an outage.", "alternative_explanations": ["Changed operating schedule", "Authorized demand change", "Meter or telemetry issue"], "next_action": "Inspection recommended; verify operating context before classifying a fault."}
        if domain == "electricity":
            voltage_values = [float(r["voltage"]) for r in qualifying if r.get("voltage") is not None and math.isfinite(float(r["voltage"]))]
            lower_v, upper_v = first.get("voltage_lower_v", 207.), first.get("voltage_upper_v", 253.)
            evidence["voltage_assessment"] = "No valid voltage measurement; voltage condition is unknown." if not voltage_values else ("Measured voltage outside the illustrative configured band; qualified inspection is recommended." if any(v < lower_v or v > upper_v for v in voltage_values) else "Measured voltage was within the illustrative configured band; this does not certify service or prove an outage.")
            evidence["voltage_observed_v"] = {"minimum": min(voltage_values), "maximum": max(voltage_values), "intervals": len(voltage_values)} if voltage_values else None
        result.append({"id": identity(domain, first["asset_id"], first["timestamp"], reasons[0]), "asset_id": first["asset_id"], "zone_id": first["zone_id"], "domain": domain, "title": "Unexpected low consumption · verify supply" if low else ("Suspected abnormal overnight usage" if "overnight_excess" in reasons else "Sustained abnormal consumption"), "severity": "high" if duration >= 6 else "medium", "start": first["timestamp"], "end": last["timestamp"], "reason_codes": reasons, "estimated_excess": excess, "unit": first["unit"], "duration_hours": duration, "evidence": evidence})

    for row in sorted(rows, key=lambda r: (r["asset_id"], r["timestamp"])):
        contiguous = not current or (row["asset_id"] == current[-1]["asset_id"] and pd.Timestamp(row["timestamp"]) == pd.Timestamp(current[-1]["timestamp"]) + pd.Timedelta(minutes=current[-1]["interval_minutes"]))
        same_direction = not current or not row.get("flag") or row.get("reason") == current[-1].get("reason") or {row.get("reason"), current[-1].get("reason")} <= {"sustained_excess", "overnight_excess"}
        if not contiguous or not same_direction or row["actual"] is None:
            finish()
            current, gaps = [], 0
        if row.get("flag"):
            current.append(row)
            gaps = 0
        elif current and row["actual"] is not None and gaps < gap_tolerance:
            current.append(row)
            gaps += 1
        elif current:
            finish()
            current, gaps = [], 0
    finish()
    return safe(result)


def _window_coverage(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Observed valid duration / elapsed window; omitted rows stay missing."""
    duration = (end - start).total_seconds()
    if duration <= 0 or frame.empty:
        return 0.
    covered = 0.
    for row in frame[frame["valid"]].itertuples():
        stop = row.timestamp + pd.Timedelta(minutes=row.interval_minutes)
        covered += max(0., (min(stop, end) - max(row.timestamp, start)).total_seconds())
    return min(1., covered / duration)


def _electricity_load_profile(frame: pd.DataFrame, end: pd.Timestamp) -> dict:
    """Summarize only observed kWh as weighted kW and complete daily totals."""
    timezone_name = "Asia/Kolkata"
    start = end - pd.Timedelta(days=7)
    recent = frame[(frame["timestamp"] >= start) & (frame["timestamp"] < end)].copy()
    recent["local_timestamp"] = recent["timestamp"].dt.tz_convert(timezone_name)
    hourly = []
    for hour in range(24):
        bucket = recent[recent["local_timestamp"].dt.hour == hour]
        valid = bucket[bucket["valid"]]
        hours_observed = float(valid["interval_minutes"].sum() / 60)
        energy = float(valid["quantity"].sum()) if not valid.empty else None
        hourly.append({"hour_ist": hour, "average_power_kw": energy / hours_observed if energy is not None and hours_observed else None,
                       "observed_kwh": energy, "valid_intervals": int(len(valid)),
                       "coverage": min(1., hours_observed / 7)})

    local_end = end.tz_convert(timezone_name)
    last_complete_day = local_end.normalize() - pd.Timedelta(days=1)
    days = pd.date_range(end=last_complete_day, periods=14, freq="D")
    daily = []
    for day in days:
        local_start = day
        local_stop = day + pd.Timedelta(days=1)
        day_start, day_stop = local_start.tz_convert("UTC"), local_stop.tz_convert("UTC")
        bucket = frame[(frame["timestamp"] >= day_start) & (frame["timestamp"] < day_stop)]
        valid = bucket[bucket["valid"]]
        coverage = min(1., float(valid["interval_minutes"].sum() / 1440))
        observed = float(valid["quantity"].sum()) if not valid.empty else None
        daily.append({"date": day.strftime("%Y-%m-%d"), "observed_kwh": observed,
                      "coverage": coverage, "valid_intervals": int(len(valid)),
                      "complete_day_kwh": observed if coverage >= .999 else None})
    return {"status": "ready", "timezone": timezone_name,
            "method": "Weighted kWh per observed interval-hour; daily totals are reported as complete only at 99.9% interval-duration coverage.",
            "hourly_average_power": hourly, "complete_daily_energy": daily,
            "limitations": ["Missing intervals are not filled or counted as zero", "No voltage or current is inferred from kWh"]}


def _optional_measurement_quality(group: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                                  field: str, unit_field: str, canonical_unit: str,
                                  aliases: set[str], maximum: float) -> dict:
    if field not in group or not group[field].notna().any():
        return {"status": "not_provided", "coverage": None, "stale": None, "last_valid": None,
                "missing": 0, "invalid": 0, "unit": canonical_unit,
                "notes": [f"Optional {field} telemetry was not supplied; it is unknown, not zero."]}
    values = pd.to_numeric(group[field], errors="coerce")
    units = group[unit_field] if unit_field in group else pd.Series("", index=group.index)
    units = units.fillna("").astype(str).str.casefold()
    valid = values.notna() & np.isfinite(values) & (values >= 0) & (values <= maximum) & units.isin(aliases)
    recent = (group["timestamp"] >= start) & (group["timestamp"] < end)
    recent_rows = group[recent]
    missing = int(recent_rows[field].isna().sum()) if len(recent_rows) else 0
    invalid = int((recent & group[field].notna() & ~valid).sum())
    duration = max(0., (end - start).total_seconds())
    covered = 0.
    for index in group.index[valid]:
        row = group.loc[index]
        stop = row["timestamp"] + pd.Timedelta(minutes=row["interval_minutes"])
        covered += max(0., (min(stop, end) - max(row["timestamp"], start)).total_seconds())
    coverage = min(1., covered / duration) if duration else None
    valid_rows = group[valid]
    last_valid = None
    stale = None
    if not valid_rows.empty:
        last_index = valid_rows["timestamp"].idxmax()
        last_end = group.loc[last_index, "timestamp"] + pd.Timedelta(minutes=group.loc[last_index, "interval_minutes"])
        last_valid = safe(last_end)
        stale = (end - last_end).total_seconds() >= 7200
    status = "degraded" if stale is True or missing > 0 or invalid > 0 or coverage is None or coverage < .8 else "ready"
    notes = []
    if missing:
        notes.append(f"{missing} missing {field} interval(s) in the latest 24 hours; missing is not zero.")
    if invalid:
        notes.append(f"{invalid} invalid {field} interval(s); check numeric values and explicit {canonical_unit} units.")
    if stale:
        notes.append(f"The last valid {field} measurement is at least two hours old.")
    return {"status": status, "coverage": coverage, "stale": stale, "last_valid": last_valid,
            "missing": missing, "invalid": invalid, "unit": canonical_unit, "notes": notes}


def _voltage_quality_and_findings(group: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                                  lower_v: float, upper_v: float) -> tuple[dict, list[dict]]:
    """Assess only explicit voltage measurements; never infer voltage from kWh."""
    if "voltage" not in group or not group["voltage"].notna().any():
        return {"status": "not_provided", "coverage": None, "stale": None, "last_valid": None,
                "missing": 0, "invalid": 0, "out_of_range": 0,
                "notes": ["Voltage telemetry was not supplied; voltage condition is unknown."]}, []

    values = pd.to_numeric(group["voltage"], errors="coerce")
    units = group["voltage_unit"] if "voltage_unit" in group else pd.Series("V", index=group.index)
    units = units.fillna("V").astype(str).str.casefold()
    valid = values.notna() & np.isfinite(values) & (values >= 0) & (values <= 1000) & units.isin({"v", "volt", "volts"})
    recent = (group["timestamp"] >= start) & (group["timestamp"] < end)
    recent_rows = group[recent]
    recent_valid = valid[recent]
    missing = int((recent_rows["voltage"].isna()).sum()) if len(recent_rows) else 0
    invalid = int((recent & group["voltage"].notna() & ~valid).sum())
    duration = max(0., (end - start).total_seconds())
    covered = 0.
    for index in group.index[valid]:
        row = group.loc[index]
        stop = row["timestamp"] + pd.Timedelta(minutes=row["interval_minutes"])
        covered += max(0., (min(stop, end) - max(row["timestamp"], start)).total_seconds())
    coverage = min(1., covered / duration) if duration else None
    valid_rows = group[valid]
    last_valid = None
    stale = None
    if not valid_rows.empty:
        last_index = valid_rows["timestamp"].idxmax()
        last_end = group.loc[last_index, "timestamp"] + pd.Timedelta(minutes=group.loc[last_index, "interval_minutes"])
        last_valid = safe(last_end)
        stale = (end - last_end).total_seconds() >= 7200

    status = "degraded" if stale is True or missing > 0 or invalid > 0 or coverage is None or coverage < .8 else "ready"
    notes = []
    if missing:
        notes.append(f"{missing} missing voltage interval(s) in the latest 24 hours; missing is not zero volts.")
    if invalid:
        notes.append(f"{invalid} invalid voltage interval(s) in the latest 24 hours; check numeric values and V units.")
    if stale:
        notes.append("The last valid voltage measurement is at least two hours old.")
    quality = {"status": status, "coverage": coverage, "stale": stale, "last_valid": last_valid,
               "missing": missing, "invalid": invalid, "out_of_range": int((valid & ((values < lower_v) | (values > upper_v))).sum()),
               "notes": notes}

    findings = []
    if status == "degraded":
        title = "Voltage telemetry is stale" if stale else "Voltage telemetry quality requires review"
        findings.append({"id": identity("electricity", group.iloc[0]["asset_id"], "voltage-quality", safe(start)),
                         "asset_id": group.iloc[0]["asset_id"], "zone_id": group.iloc[0]["zone_id"], "domain": "electricity",
                         "title": title, "severity": "medium", "start": safe(start), "end": safe(end),
                         "reason_codes": ["voltage_quality"], "estimated_excess": None, "unit": "V",
                         "evidence": {**quality, "source": "Derived", "explanation": "Voltage freshness and coverage are evaluated separately from energy consumption; missing voltage is not interpreted as zero.",
                                      "next_action": "Check the voltage telemetry source and timestamp continuity; use qualified utility staff for electrical assessment."}})

    sequence: list[int] = []
    sequence_side = 0

    def finish_sequence() -> None:
        if len(sequence) < 3:
            return
        rows = group.loc[sequence]
        measured = values.loc[sequence]
        findings.append({"id": identity("electricity", rows.iloc[0]["asset_id"], "voltage", safe(rows.iloc[0]["timestamp"])),
                         "asset_id": rows.iloc[0]["asset_id"], "zone_id": rows.iloc[0]["zone_id"], "domain": "electricity",
                         "title": "Sustained measured voltage outside illustrative range", "severity": "high",
                         "start": safe(rows.iloc[0]["timestamp"]), "end": safe(rows.iloc[-1]["timestamp"]),
                         "reason_codes": ["voltage_observation"], "estimated_excess": None, "unit": "V",
                         "duration_hours": float(rows["interval_minutes"].sum() / 60),
                         "evidence": {"voltage_min_v": float(measured.min()), "voltage_max_v": float(measured.max()),
                                      "configured_range_v": [lower_v, upper_v], "intervals": len(rows),
                                      "source": str(rows["source"].iloc[0]), "provenance": "Measured telemetry",
                                      "explanation": "At least three contiguous explicit voltage measurements are outside the illustrative configured band. Energy readings alone do not support a voltage conclusion.",
                                      "alternative_explanations": ["Voltage sensor or unit issue", "Temporary operating condition", "Supply-side variation"],
                                      "next_action": "Qualified utility inspection; keep away from suspected electrical hazards and do not touch or test energized equipment."}})

    previous_index = None
    for index in group.index:
        value = values.loc[index]
        side = -1 if valid.loc[index] and value < lower_v else 1 if valid.loc[index] and value > upper_v else 0
        contiguous = previous_index is not None and group.loc[index, "timestamp"] == group.loc[previous_index, "timestamp"] + pd.Timedelta(minutes=group.loc[previous_index, "interval_minutes"])
        if side and contiguous and side == sequence_side:
            sequence.append(index)
        else:
            finish_sequence()
            sequence = [index] if side else []
            sequence_side = side
        previous_index = index
    finish_sequence()
    return quality, findings


def analyze_consumption(readings: list[dict], domain: str, train_end: str | None = None,
                        min_coverage: float = .8, tariff: float | None = None,
                        observation_end: str | None = None,
                        training_readings: list[dict] | None = None,
                        expected_assets: list[dict] | None = None,
                        voltage_lower_v: float = 207., voltage_upper_v: float = 253.) -> dict:
    if not 0 < min_coverage <= 1:
        raise ValueError("Coverage threshold must be in (0, 1]")
    if tariff is not None:
        _nonnegative(tariff=tariff)
    if not math.isfinite(voltage_lower_v) or not math.isfinite(voltage_upper_v) or not 0 <= voltage_lower_v < voltage_upper_v <= 1000:
        raise ValueError("Illustrative voltage thresholds must satisfy 0 <= lower < upper <= 1000 V")
    frame = normalize_readings(readings, domain)
    frozen = normalize_readings(training_readings, domain) if training_readings is not None else None
    unit = "L" if domain == "water" else "kWh"
    if frame.empty:
        empty_assets = [{"asset_id": asset.get("id") or asset.get("asset_id"), "zone_id": asset.get("zone_id"), "coverage": None, "missing": None, "missing_unit": "uncovered hours", "invalid": 0, "inactive": 0, "stale": None, "irregular_sampling": None, "last_valid": None, "no_readings": True, "status": "insufficient_data", "analysis_status": "insufficient_data", "notes": ["No reading rows supplied; asset freshness cannot be assessed."]} for asset in (expected_assets or []) if asset.get("id") or asset.get("asset_id")]
        return {"domain": domain, "series": [], "findings": [], "forecast": {"status": "insufficient_data"}, "evaluation": {"status": "not_evaluated", "reason": "No readings were supplied."}, "quality": {"status": "insufficient_data", "coverage": None, "missing": None, "invalid": 0, "inactive": 0, "stale": None, "assets": empty_assets, "notes": ["No readings supplied; coverage and freshness cannot be evaluated."]}, "details": {"unit": unit, "model_version": MODEL_VERSION}}
    cutoff = pd.Timestamp(train_end) if train_end else frame["timestamp"].min() + pd.Timedelta(days=42)
    if cutoff.tzinfo is None:
        raise ValueError("Training cutoff must include a timezone")
    end = pd.Timestamp(observation_end) if observation_end else (frame["timestamp"] + pd.to_timedelta(frame["interval_minutes"], unit="m")).max()
    if end.tzinfo is None:
        raise ValueError("Observation end must include a timezone")
    recent_start = end - pd.Timedelta(hours=24)
    all_rows, findings, health, drift = [], [], [], []
    for asset_id, group in frame.groupby("asset_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        interval_ends = group["timestamp"] + pd.to_timedelta(group["interval_minutes"], unit="m")
        train_mask = (interval_ends <= cutoff) & group["valid"]
        train = group[train_mask].copy()
        if frozen is not None:
            train = frozen[(frozen['asset_id'] == asset_id) & frozen['valid'] & ((frozen['timestamp'] + pd.to_timedelta(frozen['interval_minutes'], unit='m')) <= cutoff)].copy() if not frozen.empty else group.iloc[:0].copy()
        target = group[group["timestamp"] >= cutoff]
        recent = group[(interval_ends > recent_start) & (group["timestamp"] < end)]
        coverage = _window_coverage(group, recent_start, end)
        last_valid = interval_ends[group["valid"]].max()
        stale = pd.isna(last_valid) or (end - last_valid).total_seconds() >= 7200
        irregular = bool((recent["interval_minutes"] != 60).any()) or bool((recent["timestamp"].diff().dropna() != pd.Timedelta(hours=1)).any())
        status = {"asset_id": asset_id, "zone_id": group.iloc[0]["zone_id"], "coverage": coverage, "missing": max(0, round(24 * (1 - coverage), 3)), "missing_unit": "uncovered hours", "coverage_window_start": safe(recent_start), "coverage_window_end_exclusive": safe(end), "invalid": int(recent["invalid"].sum()), "inactive": int(recent["inactive"].sum()), "stale": stale, "irregular_sampling": irregular, "reporting_interval_minutes": 60, "last_valid": safe(last_valid) if not pd.isna(last_valid) else None, "analysis_status": "pending", "notes": []}
        if domain == "electricity":
            group["voltage_numeric"] = pd.to_numeric(group["voltage"], errors="coerce") if "voltage" in group else np.nan
            voltage_quality, voltage_findings = _voltage_quality_and_findings(group, recent_start, end, voltage_lower_v, voltage_upper_v)
            status["voltage"] = voltage_quality
            findings.extend(voltage_findings)
            if voltage_quality["status"] == "degraded":
                status["status"] = "degraded"
                status["notes"].extend(voltage_quality["notes"])
            for field, unit_field, canonical_unit, aliases, maximum in (
                ("power_kw", "power_unit", "kW", {"kw", "kilowatt", "kilowatts"}, 100000.),
                ("current_a", "current_unit", "A", {"a", "amp", "amps", "ampere", "amperes"}, 1000000.),
            ):
                group[field + "_numeric"] = pd.to_numeric(group[field], errors="coerce") if field in group else np.nan
                measurement_quality = _optional_measurement_quality(group, recent_start, end, field, unit_field, canonical_unit, aliases, maximum)
                status[field] = measurement_quality
                if measurement_quality["status"] == "degraded":
                    status["status"] = "degraded"
                    status["notes"].extend(measurement_quality["notes"])
        if coverage < min_coverage:
            status["notes"].append(f"Coverage below {min_coverage:.0%}; consumption findings suppressed for latest 24 hours")
        if irregular:
            status["notes"].append("Irregular intervals normalized to rates; exact seasonal forecast requires hourly input")
        if status["inactive"]:
            status["notes"].append(f"{status['inactive']} inactive reading(s) in the latest 24 hours; excluded from consumption analysis")
        degraded = coverage < min_coverage or stale or status["invalid"] > 0 or status["inactive"] > 0 or irregular or any(status.get(field, {}).get("status") == "degraded" for field in ("voltage", "power_kw", "current_a"))
        status["status"] = "degraded" if degraded else "ready"
        if degraded:
            findings.append({"id": identity(domain, asset_id, "quality", safe(recent_start)), "asset_id": asset_id, "zone_id": status["zone_id"], "domain": domain, "title": "Telemetry quality requires review", "severity": "medium", "start": safe(recent_start), "end": safe(end), "reason_codes": ["sensor_quality"], "estimated_excess": None, "unit": unit, "evidence": {**status, "source": "Derived", "explanation": "Missing/invalid/stale telemetry is a data-quality incident, not evidence of a physical leak or outage.", "next_action": "Check meter communication and timestamp continuity."}})
        if train["interval_minutes"].sum() < 24 * 14 * 60 or len(train) < 168:
            status["analysis_status"] = "insufficient_data"
            status["analysis_reason"] = "At least 14 days of valid hourly observations are required."
            status["notes"].append("Insufficient historical data: at least 14 days of valid hourly observations required")
            health.append(status)
            continue
        status["analysis_status"] = "ready"
        train["adjusted"] = train["rate"] / train["expected_multiplier"]
        slot_median = train.groupby("slot")["adjusted"].median()
        hour_median = train.groupby("hour")["adjusted"].median()
        expected = np.asarray([slot_median.get(s, hour_median.get(h, train["adjusted"].median())) for s, h in zip(group["slot"], group["hour"])], float)
        deviations = abs(train["adjusted"] - train["slot"].map(slot_median))
        slot_mad = deviations.groupby(train["slot"]).median()
        mad = np.asarray([slot_mad.get(s, deviations.median()) for s in group["slot"]], float)
        scale = np.maximum(1.4826 * mad, np.maximum(expected * .055, 1. if domain == "water" else .025))
        features = _features(group, expected, scale)
        model = IsolationForest(n_estimators=80, contamination=.02, max_samples=512, random_state=SEED, n_jobs=1)
        fit_features = features[train_mask]
        if frozen is not None:
            fit_expected = np.asarray([slot_median.get(s, hour_median.get(h, train['adjusted'].median())) for s, h in zip(train['slot'], train['hour'])], float)
            fit_mad = np.asarray([slot_mad.get(s, deviations.median()) for s in train['slot']], float)
            fit_scale = np.maximum(1.4826 * fit_mad, np.maximum(fit_expected * .055, 1. if domain == 'water' else .025))
            fit_features = _features(train, fit_expected, fit_scale)
        model.fit(fit_features)
        scores = -model.decision_function(features)
        isolation = scores > 0
        expected = expected * group["expected_multiplier"].to_numpy()
        threshold = np.maximum(4.5 * scale, np.maximum(expected * .25, 15. if domain == "water" else .4))
        residual = group["rate"].to_numpy() - expected
        robust = (abs(residual) > threshold) & group["valid"].to_numpy() & ((residual >= 0) | group["supply_expected"].to_numpy())
        rows = []
        for i, row in group.iterrows():
            monitored = row["timestamp"] >= cutoff
            supported = coverage >= min_coverage or row["timestamp"] < recent_start
            flag = bool(robust[i] and monitored and supported)
            reason = "unexpected_low_flow" if residual[i] < 0 else ("overnight_excess" if 0 <= row["hour"] < 6 else "sustained_excess")
            factor = row["interval_minutes"] / 60
            rows.append(safe({"id": row["id"], "timestamp": row["timestamp"], "actual": row["quantity"], "expected": expected[i] * factor, "lower": max(0., expected[i] - threshold[i]) * factor, "upper": (expected[i] + threshold[i]) * factor, "threshold": threshold[i] * factor, "residual": residual[i] * factor, "flag": flag, "robust_flag": bool(robust[i] and monitored and supported), "isolation_flag": bool(isolation[i] and monitored and row["valid"] and supported), "isolation_score": scores[i], "reason": reason if flag else None, "asset_id": asset_id, "zone_id": row["zone_id"], "interval_minutes": row["interval_minutes"], "unit": unit, "source": row.get("source", "Uploaded"), "voltage": row.get("voltage_numeric") if domain == "electricity" else None, "voltage_unit": (row.get("voltage_unit") or "V") if domain == "electricity" and pd.notna(row.get("voltage_numeric")) else None, "power_kw": row.get("power_kw_numeric") if domain == "electricity" else None, "current_a": row.get("current_a_numeric") if domain == "electricity" else None, "voltage_lower_v": voltage_lower_v if domain == "electricity" else None, "voltage_upper_v": voltage_upper_v if domain == "electricity" else None, "valid": row["valid"], "training": not monitored}))
        all_rows.extend(rows)
        findings.extend(group_events(rows, domain))
        target_valid = (group["timestamp"] >= cutoff) & group["valid"]
        if target_valid.sum() >= 24:
            train_resid = fit_features[:, 1]
            recent_resid = features[target_valid, 1][-168:]
            shift = float(np.median(recent_resid) - np.median(train_resid))
            historical_rolling = float(train["adjusted"].tail(168).median())
            recent_rolling = float((group.loc[target_valid, "rate"] / group.loc[target_valid, "expected_multiplier"]).tail(168).median())
            drift.append({"asset_id": asset_id, "method": "Median standardized residual shift", "value": shift, "warning": abs(shift) > 2, "threshold": 2, "historical_trailing_median_rate": historical_rolling, "latest_trailing_median_rate": recent_rolling, "rolling_window": "Last 168 valid observations; trailing only, no centered/future windows", "interpretation": "Distribution shift merits investigation; not proof of model failure. No automatic retraining."})
        health.append(status)
    observed_assets = set(frame["asset_id"].astype(str))
    missing_assets = {}
    for asset in expected_assets or []:
        asset_id = str(asset.get("id") or asset.get("asset_id") or "")
        if not asset_id or asset_id in observed_assets or asset_id in missing_assets:
            continue
        zone_id = asset.get("zone_id") or "unknown"
        status = {"asset_id": asset_id, "zone_id": zone_id, "coverage": 0., "missing": 24., "missing_unit": "uncovered hours", "coverage_window_start": safe(recent_start), "coverage_window_end_exclusive": safe(end), "invalid": 0, "inactive": 0, "stale": None, "irregular_sampling": None, "reporting_interval_minutes": asset.get("reporting_interval_minutes", 60), "last_valid": None, "no_readings": True, "status": "degraded", "analysis_status": "insufficient_data", "notes": ["No readings exist for this registered telemetry asset in the latest observation window; freshness is unknown."]}
        missing_assets[asset_id] = status
    for status in missing_assets.values():
        health.append(status)
        findings.append({"id": identity(domain, status["asset_id"], "quality", safe(recent_start)), "asset_id": status["asset_id"], "zone_id": status["zone_id"], "domain": domain, "title": "Registered meter has no readings", "severity": "medium", "start": safe(recent_start), "end": safe(end), "reason_codes": ["sensor_quality"], "estimated_excess": None, "unit": unit, "evidence": {**status, "source": "Derived", "explanation": "No interval rows exist for this registered telemetry asset. Missing coverage is visible; the cause and last-seen time are unknown.", "next_action": "Confirm meter registration and obtain current telemetry before drawing a consumption conclusion."}})
    primary = f"{domain}-{'market' if domain == 'electricity' else 'river'}"
    if primary not in set(frame["asset_id"]):
        primary = str(frame.iloc[0]["asset_id"])
    primary_rows = [r for r in all_rows if r["asset_id"] == primary]
    excess = sum(f.get("estimated_excess") or 0 for f in findings)
    stale_values = [h["stale"] for h in health]
    stale_state = True if any(value is True for value in stale_values) else (False if stale_values and all(value is False for value in stale_values) else None)
    voltage_assets = [{"asset_id": h["asset_id"], "zone_id": h["zone_id"], **h["voltage"]} for h in health if "voltage" in h]
    voltage_state_values = [a["status"] for a in voltage_assets]
    voltage_state = "not_applicable" if domain != "electricity" else ("not_provided" if not voltage_state_values or all(value == "not_provided" for value in voltage_state_values) else ("degraded" if any(value == "degraded" for value in voltage_state_values) else "ready"))
    load_profile = _electricity_load_profile(frame, end) if domain == "electricity" else None
    energy_cost_estimate = None
    if domain == "electricity":
        cost_start = end - pd.Timedelta(days=7)
        observed_window = frame[(frame["timestamp"] >= cost_start) & (frame["timestamp"] < end)]
        valid_window = observed_window[observed_window["valid"]]
        observed_kwh = float(valid_window["quantity"].sum()) if not valid_window.empty else 0.
        energy_cost_estimate = {"status": "configured_tariff_estimate" if tariff is not None else "tariff_not_configured",
                                "window_start": safe(cost_start), "window_end_exclusive": safe(end),
                                "observed_kwh": observed_kwh, "coverage": _window_coverage(frame, cost_start, end),
                                "observed_interval_cost_inr": observed_kwh * tariff if tariff is not None else None,
                                "tariff_inr_per_kwh": tariff,
                                "basis": "Observed valid interval kWh multiplied by the configured tariff. Partial coverage is not extrapolated; this is not a utility bill."}
    result = {"domain": domain, "series": primary_rows[-72:], "findings": findings, "forecast": forecast_consumption([r for r in readings if r["asset_id"] == primary], domain), "evaluation": {"status": "not_evaluated", "reason": "No ground truth supplied to deployed detector"}, "quality": {"status": "degraded" if any(h["status"] == "degraded" for h in health) else "ready", "coverage": float(np.mean([h["coverage"] for h in health])) if health else None, "missing": sum(h["missing"] for h in health), "invalid": sum(h["invalid"] for h in health), "inactive": sum(h["inactive"] for h in health), "stale": stale_state, "assets": health, "notes": [note for h in health for note in h["notes"]]}, "details": {"unit": unit, "provenance": "Derived", "input_provenance": sorted({r.get("source", "Uploaded") for r in readings}), "model_version": MODEL_VERSION, "config_version": CONFIG_VERSION, "train_end_exclusive": safe(cutoff), "training_rows": int(((frame["timestamp"] < cutoff) & frame["valid"]).sum()), "total_rows": len(frame), "method": "Time-of-week historical median; MAD threshold; three consecutive qualifying intervals. Isolation Forest is independently fit on the same historical window and shown as corroboration, not a calibrated probability.", "event_rule": {"minimum_intervals": 3, "gap_tolerance": 0, "recovery_intervals": 1, "cooldown_hours": 0, "scope": "Non-overlapping synthetic district meters; do not aggregate parent-child meter hierarchies"}, "estimated_excess": excess, "estimated_excess_m3": excess / 1000 if domain == "water" else None, "estimated_cost": excess * tariff / (1000 if domain == "water" else 1) if tariff is not None else None, "tariff": tariff, "tariff_unit": "INR/m³" if domain == "water" else "INR/kWh", "cost_status": "Configured tariff estimate" if tariff is not None else "No tariff configured", "load_profile": load_profile, "energy_cost_estimate": energy_cost_estimate, "voltage_monitoring": {"status": voltage_state, "thresholds": {"lower": voltage_lower_v, "upper": voltage_upper_v, "unit": "V", "basis": "Illustrative configurable observation thresholds, not regulatory certification"} if domain == "electricity" else None, "assets": voltage_assets, "method": "Uses explicit measured voltage only; no voltage is inferred from energy consumption." if domain == "electricity" else "Not applicable."}, "drift": drift, "recommendations": [{"evidence_id": f["id"], "action": f["evidence"].get("next_action", "Inspect and confirm operating context"), "reason": f["title"]} for f in findings], "limitations": ["Synthetic benchmark does not establish real-world accuracy", "No physical fault location or verified repair is inferred", "Robust baseline is the default; Isolation Forest is corroborating evidence", "Anomaly thresholds are fixed before held-out evaluation"]}, "_rows": all_rows}
    if frozen is not None:
        result['details']['training_rows'] = len(frozen)
        result['details']['training_source'] = 'Immutable reviewed baseline snapshot'
    return safe(result)


def forecast_consumption(readings: list[dict], domain: str, horizon: int = 24) -> dict:
    if not isinstance(horizon, int) or not 1 <= horizon <= 168:
        raise ValueError("Forecast horizon must be an integer from 1 to 168 hours")
    frame = normalize_readings(readings, domain)
    if frame.empty or len(frame) < 24 * 28 or frame["asset_id"].nunique() != 1:
        return {"status": "insufficient_data", "reason": "28 days of a single hourly meter are required", "points": [], "metrics": None}
    frame = frame.sort_values("timestamp")
    if (frame["interval_minutes"] != 60).any() or (frame["timestamp"].diff().dropna() != pd.Timedelta(hours=1)).any():
        return {"status": "insufficient_data", "reason": "Exact hourly interval continuity is required for seasonal-naive forecasts", "points": [], "metrics": None}
    values = frame["quantity"].to_numpy(float)
    lag = 168
    predicted = np.r_[np.full(lag, np.nan), values[:-lag]]
    errors = values - predicted
    calibration_raw = errors[-336:-168]
    calibration = calibration_raw.copy()
    calibration = calibration[np.isfinite(calibration)]
    test = errors[-168:]
    test = test[np.isfinite(test)]
    if len(calibration) < 120 or len(test) < 120:
        return {"status": "insufficient_data", "reason": "Calibration and holdout each require at least 120 valid paired intervals", "points": [], "metrics": None}
    # Separate chronological calibration, never use holdout errors to set bounds.
    radius = float(np.quantile(abs(calibration), .9, method="higher"))
    points = []
    for i in range(min(horizon, 168)):
        expected = values[-168 + i]
        points.append({"timestamp": safe(frame["timestamp"].iloc[-1] + pd.Timedelta(hours=i + 1)), "expected": expected, "lower": max(0., expected - radius), "upper": expected + radius, "unit": "L" if domain == "water" else "kWh"})
    calibration_daily = [sum(calibration_raw[i:i+24]) for i in range(0, len(calibration_raw) - 23, 24) if np.all(np.isfinite(calibration_raw[i:i+24]))]
    daily_radius = float(np.quantile(np.abs(calibration_daily), .9, method="higher")) if len(calibration_daily) >= 5 else None
    test_daily = [sum(errors[-168:][i:i+24]) for i in range(0, 168, 24) if np.all(np.isfinite(errors[-168:][i:i+24]))]
    daily = []
    for offset in range(0, len(points) - 23, 24):
        day = points[offset:offset + 24]
        if all(math.isfinite(p["expected"]) for p in day):
            daily_expected = sum(p["expected"] for p in day)
            daily.append({"date": day[0]["timestamp"][:10], "start": day[0]["timestamp"], "period_hours": 24, "expected": daily_expected, "lower": max(0., daily_expected - daily_radius) if daily_radius is not None else None, "upper": daily_expected + daily_radius if daily_radius is not None else None, "unit": day[0]["unit"]})
    daily_history = frame.assign(date=frame["timestamp"].dt.strftime("%Y-%m-%d")).groupby("date").agg(actual=("quantity", lambda x: x.sum(min_count=24)), valid=("valid", "sum")).tail(14).reset_index().to_dict("records")
    previous_week, latest_week = values[-336:-168], values[-168:]
    enhanced = _evaluate_enhanced_forecast(frame)
    return safe({"status": "ready", "method": "Weekly seasonal naive (same hour seven days earlier)", "horizon_hours": len(points), "points": points, "daily": daily, "daily_history": daily_history, "interval_method": "90th percentile absolute errors in separate preceding 7-day calibration block; empirical marginal intervals", "prediction_interval_radius": radius, "nominal_coverage": .9, "metrics": {"mae": np.mean(abs(test)), "rmse": np.sqrt(np.mean(test ** 2)), "interval_coverage": np.mean(abs(test) <= radius), "test_samples": len(test), "calibration_samples": len(calibration)}, "daily_metrics": {"mae": np.mean(np.abs(test_daily)) if test_daily else None, "rmse": np.sqrt(np.mean(np.square(test_daily))) if test_daily else None, "interval_coverage": np.mean(np.abs(test_daily) <= daily_radius) if test_daily and daily_radius is not None else None, "test_days": len(test_daily), "calibration_days": len(calibration_daily)}, "splits": {"calibration_start": safe(frame["timestamp"].iloc[-336]), "calibration_end_exclusive": safe(frame["timestamp"].iloc[-168]), "test_start": safe(frame["timestamp"].iloc[-168]), "test_end_exclusive": safe(frame["timestamp"].iloc[-1] + pd.Timedelta(hours=1))}, "weekly_comparison": {"previous_week_total": np.sum(previous_week) if np.all(np.isfinite(previous_week)) else None, "latest_week_total": np.sum(latest_week) if np.all(np.isfinite(latest_week)) else None, "coverage": float(np.mean(np.isfinite(latest_week)))}, "enhanced_model": enhanced, "limitations": ["Intervals reflect synthetic historical errors and can miss regime changes", "No percentage error metric is used near zero demand", "Daily forecast periods are successive 24-hour windows from the forecast origin", "Daily interval calibration uses complete calibration days only", "Operational forecast remains seasonal naive; enhanced backtest does not silently switch the deployed method"]})


def _evaluate_enhanced_forecast(frame: pd.DataFrame) -> dict:
    """Fixed chronological fit/calibration/holdout; lag features are causal.

    Evaluates one-step rolling origins using available past actuals. This is not
    a multi-day closed-loop backtest and is labeled separately from the deployed
    weekly seasonal-naive forecast.
    """
    if len(frame) < 56 * 24:
        return {"status": "not_evaluated", "reason": "56 hourly days required for gradient boosting fit, calibration and holdout"}
    values = frame["quantity"].reset_index(drop=True)
    features = np.column_stack((frame["hour"], frame["weekday"], values.shift(24), values.shift(168), values.shift(1).rolling(24, min_periods=24).mean()))
    n = len(values)
    fit_end, test_start = n - 336, n - 168
    eligible = np.isfinite(features).all(axis=1) & np.isfinite(values)
    train = eligible & (np.arange(n) < fit_end)
    calibration = eligible & (np.arange(n) >= fit_end) & (np.arange(n) < test_start)
    test = eligible & (np.arange(n) >= test_start)
    if train.sum() < 28 * 24 or calibration.sum() < 120 or test.sum() < 120:
        return {"status": "not_evaluated", "reason": "Insufficient valid causal lag features in fit, calibration or holdout"}
    model = HistGradientBoostingRegressor(max_iter=80, max_leaf_nodes=12, l2_regularization=1, learning_rate=.08, random_state=SEED, early_stopping=False)
    model.fit(features[train], values[train])
    calibration_errors = values[calibration].to_numpy() - model.predict(features[calibration])
    test_errors = values[test].to_numpy() - model.predict(features[test])
    baseline_errors = values[test].to_numpy() - values.shift(168)[test].to_numpy()
    radius = float(np.quantile(abs(calibration_errors), .9, method="higher"))
    return safe({"status": "computed", "method": "Histogram gradient boosting, fixed hyperparameters", "protocol": "One-hour rolling origin; lag-24, lag-168 and trailing-24 mean use only past observations", "features": ["local hour", "local weekday", "lag 24h", "lag 168h", "trailing 24h mean"], "fit_rows": train.sum(), "calibration_rows": calibration.sum(), "test_rows": test.sum(), "fit_end_exclusive": frame["timestamp"].iloc[fit_end], "calibration_end_exclusive": frame["timestamp"].iloc[test_start], "metrics": {"mae": np.mean(abs(test_errors)), "rmse": np.sqrt(np.mean(test_errors ** 2)), "interval_coverage": np.mean(abs(test_errors) <= radius), "baseline_mae_same_rows": np.mean(abs(baseline_errors)), "baseline_rmse_same_rows": np.sqrt(np.mean(baseline_errors ** 2))}, "interval_radius": radius, "interval_method": "90th percentile absolute errors from separate prior calibration block", "selection": "Comparison only; deployment retains seasonal naive pending validation-led model selection"})


def evaluate_consumption(domain: str, seed: int = 37031, days: int = 56) -> dict:
    readings, truth = generate_consumption(domain, seed=seed, days=days, anomalies=True)
    analysis = analyze_consumption(readings, domain)
    labels = {r["reading_id"]: r["anomaly"] for r in truth}
    cutoff = CLOCK - timedelta(days=7)
    rows = [r for r in analysis["_rows"] if pd.Timestamp(r["timestamp"]) >= cutoff and r["actual"] is not None]
    if not rows:
        return {"status": "not_evaluated", "reason": "No valid held-out observations"}
    actual = [labels[r["id"]] for r in rows]
    models = {}
    for name, key in (("robust_baseline", "robust_flag"), ("isolation_forest", "isolation_flag")):
        predicted = [r[key] for r in rows]
        p, r, f, _ = precision_recall_fscore_support(actual, predicted, average="binary", zero_division=0)
        tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[False, True]).ravel()
        models[name] = {"precision": float(p) if tp + fp else None, "recall": float(r) if tp + fn else None, "f1": float(f) if tp + fp + fn else None, "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}, "false_flagged_intervals_per_zone_day": int(fp) / 21}
    predicted_events = group_events(rows, domain)
    truth_rows = [{**r, "flag": labels[r["id"]], "reason": "sustained_excess" if (r["actual"] or 0) > (r["expected"] or 0) else "unexpected_low_flow"} for r in rows]
    truth_events = group_events(truth_rows, domain)
    matched, delays = set(), []
    unmatched = 0
    for event in predicted_events:
        match = next((t for t in truth_events if t["id"] not in matched and t["asset_id"] == event["asset_id"] and pd.Timestamp(event["start"]) <= pd.Timestamp(t["end"]) + pd.Timedelta(hours=1) and pd.Timestamp(event["end"]) >= pd.Timestamp(t["start"]) - pd.Timedelta(hours=1)), None)
        if match:
            matched.add(match["id"])
            # Detection is available only at the end of the third interval.
            delays.append(max(0, (pd.Timestamp(event["start"]) + pd.Timedelta(hours=3) - pd.Timestamp(match["start"])).total_seconds() / 3600))
        else:
            unmatched += 1
    return safe({"status": "computed", "dataset_id": f"synthetic-{domain}-{seed}-{days}d-v1", "seed": seed, "development_seed": SEED, "validation_seed": 7301, "split": {"train_days": 42, "validation_days": 7, "heldout_days": 7, "heldout_start": safe(cutoff)}, "samples": len(rows), "coverage": len(rows) / (7 * 24 * 3), "models": models, "event_metrics": {"predicted_events": len(predicted_events), "ground_truth_events": len(truth_events), "matched_events": len(matched), "precision": len(matched) / len(predicted_events) if predicted_events else None, "recall": len(matched) / len(truth_events) if truth_events else None, "mean_detection_delay_hours": np.mean(delays) if delays else None, "false_alerts_per_zone_day": unmatched / 21, "matching_rule": "Same meter and overlapping interval window with ±1 hour tolerance; one-to-one greedy chronological match"}, "model_version": MODEL_VERSION, "thresholds": {"mad_scale": 4.5, "relative_floor": .25, "isolation_contamination": .02, "minimum_persistence": 3}, "limitations": ["Computed on synthetic held-out data, not real-world accuracy", "Fixed thresholds; no held-out tuning", "Interval metrics include quality-suppressed intervals as negatives; coverage is valid-input coverage", "Ground truth is generated separately and excluded from detector input", "Validation seed is reserved for future model selection; thresholds are predefined"]})


def _nonnegative(**values: float) -> None:
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values.values()):
        raise ValueError("All model quantities must be finite and nonnegative")


def simulate_tank(capacity_l: float = 50000, initial_l: float = 28000,
                  inflow_lph: float = 1100, outflow_lph: float = 1800,
                  hours: float = 24, dt_hours: float = 1) -> dict:
    """Discrete mass balance; capacity, unmet demand, and spill are explicit."""
    _nonnegative(capacity_l=capacity_l, initial_l=initial_l, inflow_lph=inflow_lph, outflow_lph=outflow_lph, hours=hours, dt_hours=dt_hours)
    if capacity_l <= 0 or initial_l > capacity_l or dt_hours <= 0 or hours > 168:
        raise ValueError("Tank requires positive capacity/time step, valid initial level, horizon ≤168h")
    storage, supplied, spilled, total_in, unmet, elapsed = initial_l, 0., 0., 0., 0., 0.
    levels = [{"hour": 0., "level_l": storage, "fill_fraction": storage / capacity_l, "inflow_l": 0., "outflow_l": 0., "spilled_l": 0., "unmet_l": 0.}]
    while elapsed < hours - 1e-9:
        step = min(dt_hours, hours - elapsed)
        inflow, demand = inflow_lph * step, outflow_lph * step
        delivered = min(storage + inflow, demand)
        spill = max(storage + inflow - delivered - capacity_l, 0.)
        storage += inflow - delivered - spill
        elapsed += step
        supplied += delivered
        spilled += spill
        total_in += inflow
        unmet += demand - delivered
        levels.append({"hour": elapsed, "level_l": storage, "fill_fraction": storage / capacity_l, "inflow_l": inflow, "outflow_l": delivered, "spilled_l": spill, "unmet_l": demand - delivered})
    depletion = initial_l / (outflow_lph - inflow_lph) if outflow_lph > inflow_lph else None
    return safe({"capacity_l": capacity_l, "initial_l": initial_l, "final_l": storage, "total_inflow_l": total_in, "delivered_l": supplied, "unmet_demand_l": unmet, "spilled_l": spilled, "conservation_error_l": initial_l + total_in - supplied - spilled - storage, "depletion_hours": depletion, "depletion_note": "No finite depletion under constant-flow assumption" if depletion is None else "Constant rates assumed; actual operations may change", "low_threshold_l": .2 * capacity_l, "low_level": storage < .2 * capacity_l, "series": levels, "source": "Simulated", "method": "Storage[t+1] = storage[t] + inflow − delivered demand − spill; storage bounded [0, capacity]"})


def simulate_drainage(rainfall_mmph: float | None = 32, area_m2: float = 12000,
                       runoff_coefficient: float = .7, discharge_m3ph: float = 190,
                       storage_capacity_m3: float = 400, initial_m3: float = 40,
                       blockage: float = .65, hours: float = 6, dt_hours: float = .25) -> dict:
    if rainfall_mmph is None:
        return {"status": "insufficient_data", "series": [], "reason": "Rainfall input is missing; rainfall-runoff calculation unavailable", "source": "Simulated"}
    _nonnegative(rainfall_mmph=rainfall_mmph, area_m2=area_m2, runoff_coefficient=runoff_coefficient, discharge_m3ph=discharge_m3ph, storage_capacity_m3=storage_capacity_m3, initial_m3=initial_m3, blockage=blockage, hours=hours, dt_hours=dt_hours)
    if not 0 <= blockage <= 1 or not 0 <= runoff_coefficient <= 1 or storage_capacity_m3 <= 0 or initial_m3 > storage_capacity_m3 or dt_hours <= 0 or hours > 168:
        raise ValueError("Drainage fractions, capacities, initial storage, or time step are invalid")
    inflow = rainfall_mmph / 1000 * area_m2 * runoff_coefficient
    discharge = discharge_m3ph * (1 - blockage)
    tank = simulate_tank(storage_capacity_m3 * 1000, initial_m3 * 1000, inflow * 1000, discharge * 1000, hours, dt_hours)
    series = [{"hour": r["hour"], "storage_m3": r["level_l"] / 1000, "level_fraction": r["fill_fraction"], "inflow_m3": r["inflow_l"] / 1000, "discharge_m3": r["outflow_l"] / 1000, "overflow_m3": r["spilled_l"] / 1000} for r in tank["series"]]
    return safe({"status": "ready", "source": "Simulated", "rainfall_mmph": rainfall_mmph, "area_m2": area_m2, "runoff_coefficient": runoff_coefficient, "blockage_fraction": blockage, "inflow_m3ph": inflow, "effective_discharge_m3ph": discharge, "capacity_m3": storage_capacity_m3, "initial_m3": initial_m3, "final_storage_m3": tank["final_l"] / 1000, "total_inflow_m3": tank["total_inflow_l"] / 1000, "total_discharge_m3": tank["delivered_l"] / 1000, "overflow_m3": tank["spilled_l"] / 1000, "conservation_error_m3": tank["conservation_error_l"] / 1000, "series": series, "assumptions": ["Uniform rainfall and runoff coefficient", "Constant capacity reduced linearly by recorded blockage", "Overflow is removed to a separately counted surface volume; no flood depth or evacuation prediction", "No hydraulic routing or terrain model"]})


def road_priority(observation: dict, priority_weights: dict | None = None) -> dict:
    """Deterministic score in [0,100], with components and missing inputs."""
    weights = dict(priority_weights or ROAD_PRIORITY_WEIGHTS)
    if set(weights) != set(ROAD_PRIORITY_WEIGHTS):
        raise ValueError("Road priority weights must define every supported component exactly once")
    _nonnegative(**weights)
    if abs(sum(weights.values()) - 100) > 1e-6:
        raise ValueError("Road priority weights must total 100 points")
    caps = {"severity": 5., "extent_m2": 8., "daily_exposure": 10000., "repeat_count": 5., "vulnerable_location": 1.}
    components, missing = {}, []
    for key, weight in weights.items():
        value = observation.get(key)
        if value is None:
            missing.append(key)
            components[key] = 0.
        else:
            _nonnegative(**{key: value})
            components[key] = min(1., value / caps[key]) * weight
    score = sum(components.values())
    return safe({**observation, "score": score, "components": components, "weights": weights, "missing_inputs": missing, "evidence_status": "Synthetic inspection" if observation.get("source") == "Synthetic" else ("Inspector recorded" if observation.get("inspected") else "Unverified report; review required"), "recommended_treatment": "Engineering inspection to select patching/resurfacing" if score >= 60 else "Condition survey and localized maintenance assessment", "config_version": CONFIG_VERSION, "method": "Weighted capped input components; not a learned model or failure probability"})


def plan_road_budget(observations: list[dict], budget: float = 100000, priority_weights: dict | None = None) -> dict:
    _nonnegative(budget=budget)
    ordered = sorted((road_priority(o, priority_weights) for o in observations), key=lambda x: (-x["score"], x["id"]))
    selected, excluded, spent = [], [], 0.
    for item in ordered:
        cost = item.get("cost")
        if cost is None:
            excluded.append({**item, "reason": "No configured cost estimate"})
        elif not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise ValueError("Repair costs must be nonnegative finite values")
        elif spent + cost <= budget:
            selected.append(item)
            spent += cost
        else:
            excluded.append({**item, "reason": "Exceeds remaining budget"})
    return safe({"budget": budget, "spent": spent, "remaining": budget - spent, "currency": "INR", "selected": selected, "excluded": excluded, "priorities": ordered, "method": "Priority-first greedy selection, tie broken by ID; planning aid, not an optimal engineering plan", "source": "Simulated"})


def plan_waste_collection(bins: list[dict], vehicle_capacity_l: float = 1600,
                           depot: tuple[float, float] = (0, 0)) -> dict:
    _nonnegative(vehicle_capacity_l=vehicle_capacity_l)
    if vehicle_capacity_l <= 0:
        raise ValueError("Vehicle capacity must be positive")
    pending, excluded = [], []
    for original in bins:
        item = dict(original)
        volume = item.get("estimated_volume_l")
        if volume is None:
            excluded.append({**item, "reason": "Missing estimated volume"})
            continue
        _nonnegative(estimated_volume_l=volume)
        if volume > vehicle_capacity_l:
            excluded.append({**item, "reason": "Single stop exceeds vehicle capacity; split service or larger vehicle required", "minimum_partial_trips": math.ceil(volume / vehicle_capacity_l)})
        elif volume > 0 and (item.get("fill_fraction", 0) >= .7 or item.get("overdue", False)):
            pending.append(item)
        else:
            excluded.append({**item, "reason": "Below planning trigger and collection not overdue"})
    trips = []
    while pending:
        position = depot
        stops, load, distance = [], 0., 0.
        while True:
            feasible = [b for b in pending if load + b["estimated_volume_l"] <= vehicle_capacity_l]
            if not feasible:
                break
            chosen = min(feasible, key=lambda b: (math.dist(position, (b["x_km"], b["y_km"])), b["id"]))
            distance += math.dist(position, (chosen["x_km"], chosen["y_km"]))
            position = (chosen["x_km"], chosen["y_km"])
            stops.append(chosen)
            load += chosen["estimated_volume_l"]
            pending.remove(chosen)
        distance += math.dist(position, depot)
        trips.append({"trip": len(trips) + 1, "stops": stops, "load_l": load, "remaining_capacity_l": vehicle_capacity_l - load, "distance_km": distance, "returns_to_depot": True})
    return safe({"trips": trips, "trips_needed": len(trips), "excluded": excluded, "vehicle_capacity_l": vehicle_capacity_l, "total_collected_estimate_l": sum(t["load_l"] for t in trips), "distance_km": sum(t["distance_km"] for t in trips), "method": "Nearest-neighbor with capacity-constrained trips and depot return", "distance_basis": "Straight-line synthetic coordinates; not navigable routes or travel times", "source": "Simulated"})


def time_to_capacity(observations: list[dict], capacity: float) -> dict:
    _nonnegative(capacity=capacity)
    valid = sorted([o for o in observations if o.get("volume_l") is not None], key=lambda o: o["timestamp"])
    if len(valid) < 2:
        return {"hours": None, "reason": "At least two valid observations required"}
    first, last = valid[-2:]
    elapsed = (pd.Timestamp(last["timestamp"]) - pd.Timestamp(first["timestamp"])).total_seconds() / 3600
    if elapsed <= 0:
        return {"hours": None, "reason": "Observation times must differ"}
    rate = (last["volume_l"] - first["volume_l"]) / elapsed
    if rate <= 0:
        return {"hours": None, "rate_lph": rate, "reason": "No finite estimate while fill is steady or decreasing"}
    return safe({"hours": max(capacity - last["volume_l"], 0) / rate, "rate_lph": rate, "reason": "Linear extrapolation of the two most recent valid observations; collection resets the trend"})


def streetlight_expected(timestamp: str, on_hour: int = 18, off_hour: int = 6) -> bool:
    if not 0 <= on_hour < 24 or not 0 <= off_hour < 24 or on_hour == off_hour:
        raise ValueError("Distinct scheduled hours in 0–23 required")
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        raise ValueError("Streetlight timestamp requires timezone")
    hour = stamp.tz_convert("Asia/Kolkata").hour
    return (hour >= on_hour or hour < off_hour) if on_hour > off_hour else (on_hour <= hour < off_hour)


def analyze_streetlights(observations: list[dict], on_hour: int = 18,
                          off_hour: int = 6, persistence: int = 3,
                          observation_end: str | None = None) -> dict:
    if persistence < 1:
        raise ValueError("Persistence must be at least one interval")
    as_of = pd.Timestamp(observation_end or CLOCK.isoformat())
    if as_of.tzinfo is None:
        raise ValueError("Streetlight observation_end requires timezone")
    as_of = as_of.tz_convert("UTC")
    series, findings, current = [], [], []
    asset_quality = []
    grouped = defaultdict(list)
    for row in observations:
        grouped[row["asset_id"]].append(row)
    for asset_id, values in grouped.items():
        current = []
        values = sorted(values, key=lambda x: x["timestamp"])

        def emit() -> None:
            if len(current) >= persistence:
                first, last = current[0], current[-1]
                kind = "suspected_nighttime_failure" if first["expected"] else "daytime_energy_waste"
                findings.append({"id": identity("streetlights", asset_id, first["timestamp"], kind), "asset_id": asset_id, "zone_id": first["zone_id"], "domain": "streetlights", "title": "Suspected lamp failure during scheduled on period" if first["expected"] else "Lamp observed on during scheduled off period", "severity": "medium", "start": first["timestamp"], "end": last["timestamp"], "reason_codes": [kind], "estimated_excess": None, "unit": "state", "duration_hours": len(current), "evidence": {"interval_count": len(current), "persistence_required": persistence, "expected_on": first["expected"], "observed_on": first["actual"], "source": "Synthetic", "explanation": f"Schedule mismatch persists for {len(current)} hourly observations.", "alternative_explanations": ["Schedule override", "Status sensor fault", "Maintenance isolation"], "next_action": "Qualified inspection; on/off telemetry does not identify wiring or voltage faults."}})

        for row in values:
            expected = streetlight_expected(row["timestamp"], on_hour, off_hour)
            actual = row.get("on")
            mismatch = actual is not None and bool(actual) != expected
            point = {"timestamp": row["timestamp"], "actual": None if actual is None else int(bool(actual)), "expected": int(expected), "lower": int(expected), "upper": int(expected), "flag": mismatch, "asset_id": asset_id, "zone_id": row["zone_id"], "unit": "state"}
            if current and (not mismatch or expected != bool(current[-1]["expected"]) or pd.Timestamp(row["timestamp"]) - pd.Timestamp(current[-1]["timestamp"]) != pd.Timedelta(hours=1)):
                emit()
                current = []
            if mismatch:
                current.append(point)
            series.append(point)
        emit()
        last_observation = max(pd.Timestamp(row["timestamp"]).tz_convert("UTC") for row in values)
        observation_age_hours = max(0., (as_of - last_observation).total_seconds() / 3600)
        stale = observation_age_hours >= 2
        recent_start = as_of - pd.Timedelta(hours=24)
        recent_rows = [row for row in values if recent_start <= pd.Timestamp(row["timestamp"]).tz_convert("UTC") < as_of]
        missing = sum(row.get("on") is None for row in recent_rows)
        asset_quality.append({"asset_id": asset_id, "zone_id": values[-1]["zone_id"],
                              "last_observation": safe(last_observation),
                              "observation_age_hours": observation_age_hours,
                              "stale": stale, "missing_state_intervals_24h": missing,
                              "stale_after_hours": 2})
        if missing:
            findings.append({"id": identity("streetlights", asset_id, "missing-state", safe(recent_start)), "asset_id": asset_id, "zone_id": values[-1]["zone_id"], "domain": "streetlights", "title": "Missing lamp state readings", "severity": "medium", "start": safe(recent_start), "end": safe(as_of), "reason_codes": ["sensor_quality", "missing_state"], "estimated_excess": None, "unit": "state", "evidence": {"missing_intervals_24h": missing, "last_observation": safe(last_observation), "source": "Derived", "explanation": "Missing lamp state is not interpreted as switched off; a recorded sample can still have a fresh observation timestamp.", "next_action": "Check state values and the reporting device separately."}})
        if stale:
            findings.append({"id": identity("streetlights", asset_id, "stale-observation", safe(last_observation)), "asset_id": asset_id, "zone_id": values[-1]["zone_id"], "domain": "streetlights", "title": "Streetlight observations are stale", "severity": "medium", "start": safe(last_observation), "end": safe(as_of), "reason_codes": ["sensor_quality", "stale_observation"], "estimated_excess": None, "unit": "state", "evidence": {"last_observation": safe(last_observation), "age_hours": observation_age_hours, "stale_after_hours": 2, "source": "Derived", "explanation": "The latest recorded observation is at least two hours old; this does not establish the lamp state or a service outage.", "next_action": "Check the telemetry connection and obtain a current observation."}})
        # Only high-frequency, explicit state samples can support a flicker-like
        # switching pattern. Hourly scheduled observations never qualify.
        flicker_windows = []
        for start_index in range(max(0, len(values) - 3)):
            window = values[start_index:start_index + 4]
            states = [row.get("on") for row in window]
            stamps = [pd.Timestamp(row["timestamp"]) for row in window]
            gaps = [(stamps[i] - stamps[i - 1]).total_seconds() for i in range(1, len(stamps))]
            transitions = sum(bool(states[i]) != bool(states[i - 1]) for i in range(1, len(states)))
            if (all(state is not None for state in states) and transitions >= 3
                    and all(0 < gap <= 300 for gap in gaps)
                    and (stamps[-1] - stamps[0]).total_seconds() <= 900):
                start, end = window[0]["timestamp"], window[-1]["timestamp"]
                if flicker_windows and pd.Timestamp(start) <= pd.Timestamp(flicker_windows[-1]["end"]):
                    flicker_windows[-1]["end"] = end
                    flicker_windows[-1]["transitions"] += 1
                else:
                    flicker_windows.append({"start": start, "end": end, "transitions": transitions,
                                            "source": window[0].get("source", "Observed telemetry")})
        for episode in flicker_windows:
            findings.append({"id": identity("streetlights", asset_id, episode["start"], "flicker-pattern"),
                             "asset_id": asset_id, "zone_id": values[0]["zone_id"], "domain": "streetlights",
                             "title": "Rapid lamp state switching pattern", "severity": "medium",
                             "start": episode["start"], "end": episode["end"],
                             "reason_codes": ["suspected_flicker_pattern"], "estimated_excess": None,
                             "unit": "state", "evidence": {"state_transitions": episode["transitions"],
                             "maximum_sample_gap_seconds": 300, "maximum_window_seconds": 900,
                             "source": episode["source"],
                             "explanation": "Four explicit state samples changed at least three times within 15 minutes.",
                             "alternative_explanations": ["Status sensor bounce", "Switching-control fault", "Intermittent lamp behavior"],
                             "next_action": "Review the telemetry and arrange an on-site check; this pattern does not establish a wiring or voltage fault."}})

    recurrence_groups = defaultdict(list)
    for finding in findings:
        codes = finding.get("reason_codes", [])
        if codes and codes[0] in {"suspected_nighttime_failure", "daytime_energy_waste", "suspected_flicker_pattern"}:
            recurrence_groups[(finding["asset_id"], codes[0])].append(finding)
    for episodes in recurrence_groups.values():
        episode_count = len(episodes)
        for finding in episodes:
            finding["evidence"]["recurrence_episode_count"] = episode_count
            finding["evidence"]["recurring"] = episode_count > 1
            if episode_count > 1:
                finding["reason_codes"].append("recurring_pattern")
                finding["title"] = "Recurring: " + finding["title"]
    missing = sum(r["actual"] is None for r in series)
    stale = any(asset["stale"] for asset in asset_quality)
    return safe({"domain": "streetlights", "series": [r for r in series if r["asset_id"] == (next(iter(grouped)) if grouped else "")][-48:], "findings": findings, "forecast": {"status": "not_applicable", "reason": "Schedule comparison, no predictive demand model"}, "evaluation": {"status": "rule_based", "method": "Schedule and persistence boundary tests; no AI accuracy claim"}, "quality": {"coverage": (len(series) - missing) / len(series) if series else 0, "missing": missing, "invalid": 0, "stale": stale, "assets": asset_quality, "notes": ["Freshness uses the latest recorded observation timestamp; no independent heartbeat stream is available."]}, "details": {"on_hour": on_hour, "off_hour": off_hour, "timezone": "Asia/Kolkata", "observation_end": safe(as_of), "persistence_intervals": persistence, "method": "Configured schedule against observed state, with three-hour persistence and recovery on first normal observation", "source": "Synthetic", "limitations": ["Status cannot establish voltage, electrical safety, or physical fault cause", "Freshness is based on recorded observation timestamps, not an independent device heartbeat"], "observations": observations}})


def network_data() -> dict:
    water_assets = [a for a in asset_registry() if a["domain"] == "water"]
    nodes = [{"id": "reservoir-main", "name": "Civic reservoir", "type": "Reservoir", "domain": "water", "zone_id": "river", "x": 13, "y": 18, "lat": 18.529, "lon": 73.848, "source": "Synthetic"}, {"id": "tank-central", "name": "Central balancing tank", "type": "Tank", "domain": "water", "zone_id": "river", "x": 42, "y": 20, "lat": 18.528, "lon": 73.853, "capacity_l": 50000, "source": "Synthetic"}, {"id": "junction-east", "name": "East distribution junction", "type": "Junction", "domain": "water", "zone_id": "market", "x": 69, "y": 28, "lat": 18.526, "lon": 73.86, "source": "Synthetic"}, *water_assets]
    edges = [{"id": "pipe-01", "source": "reservoir-main", "target": "tank-central", "length_m": 620, "open": True}, {"id": "pipe-02", "source": "tank-central", "target": "water-river", "length_m": 450, "open": True}, {"id": "pipe-03", "source": "tank-central", "target": "junction-east", "length_m": 750, "open": True}, {"id": "pipe-04", "source": "junction-east", "target": "water-market", "length_m": 330, "open": True}, {"id": "pipe-05", "source": "junction-east", "target": "water-hill", "length_m": 880, "open": True}, {"id": "pipe-06", "source": "tank-central", "target": "water-hill", "length_m": 1030, "open": True}]
    return {"nodes": nodes, "edges": edges, "source": "Synthetic schematic", "method": "Directed topology with illustrative configured pipe lengths", "hydraulic_result": "Hydraulic result unavailable", "limitations": ["Graph connectivity cannot establish pressure, volume delivered, fault location, or customers affected"]}


def network_path(source: str, target: str, closed_edges: list[str] | None = None,
                 data: dict | None = None) -> dict:
    data = network_data() if data is None else data
    graph = nx.DiGraph()
    graph.add_nodes_from(n["id"] for n in data["nodes"])
    closed = set(closed_edges or [])
    unknown = closed - {e["id"] for e in data["edges"]}
    if unknown:
        raise ValueError("Unknown pipe ID")
    closed.update(e["id"] for e in data["edges"] if not e.get("open", True))
    for edge in data["edges"]:
        if edge["source"] not in graph or edge["target"] not in graph:
            raise ValueError("Pipe endpoint missing from network")
        if not math.isfinite(edge["length_m"]) or edge["length_m"] < 0:
            raise ValueError("Pipe length must be finite and nonnegative")
        if edge["id"] not in closed:
            graph.add_edge(edge["source"], edge["target"], weight=edge["length_m"], id=edge["id"])
    if source not in graph or target not in graph:
        raise ValueError("Unknown network node")
    connected = nx.has_path(graph, source, target)
    path = nx.shortest_path(graph, source, target, weight="weight") if connected else []
    reachable = sorted(nx.descendants(graph, source))
    return {"source": source, "target": target, "connected": connected, "path": path,
            "path_edges": [graph[a][b]["id"] for a, b in zip(path, path[1:])],
            "distance_m": nx.path_weight(graph, path, "weight") if path else None,
            "reachable": reachable, "unreachable": sorted(set(graph) - set(reachable) - {source}),
            "closed_edges": sorted(closed), "hydraulic_result": "Hydraulic result unavailable",
            "explanation": "Shortest directed path by configured pipe length; reachable nodes indicate topology only"}


def cross_domain_suggestions(cases: list[dict], assets: list[dict] | None = None,
                              max_distance_m: float = 500, max_hours: float = 24) -> list[dict]:
    """Co-located compatible cases suggest coordination, never causal linkage."""
    _nonnegative(max_distance_m=max_distance_m, max_hours=max_hours)
    # An explicitly empty asset list means that the caller has no recorded
    # coordinates to offer. Only omitted assets use the standalone seed data.
    asset_lookup = {}
    for asset in (asset_registry() if assets is None else assets):
        lat, lon = asset.get("lat"), asset.get("lon")
        if (isinstance(lat, (int, float)) and not isinstance(lat, bool)
                and isinstance(lon, (int, float)) and not isinstance(lon, bool)
                and math.isfinite(lat) and math.isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            asset_lookup[asset["id"]] = asset
    compatible = {frozenset(("water", "electricity")), frozenset(("water", "roads")), frozenset(("drainage", "waste")), frozenset(("drainage", "roads"))}
    suggestions, seen = [], set()
    for i, left in enumerate(cases):
        for right in cases[i + 1:]:
            if frozenset((left.get("domain"), right.get("domain"))) not in compatible:
                continue
            a, b = asset_lookup.get(left.get("asset_id")), asset_lookup.get(right.get("asset_id"))
            if not a or not b:
                continue
            lat = math.radians((a["lat"] + b["lat"]) / 2)
            distance = math.hypot((a["lat"] - b["lat"]) * 111320, (a["lon"] - b["lon"]) * 111320 * math.cos(lat))
            def timestamp(case):
                for value in (case.get("start"), case.get("created_at")):
                    if not value:
                        continue
                    try:
                        parsed = pd.Timestamp(value)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if not pd.isna(parsed) and parsed.tzinfo is not None:
                        return parsed
                return None

            left_time, right_time = timestamp(left), timestamp(right)
            if left_time is None or right_time is None:
                continue
            offset = abs((left_time - right_time).total_seconds()) / 3600
            if distance <= max_distance_m and offset <= max_hours:
                first, second = sorted([left["id"], right["id"]])
                if first == second or (first, second) in seen:
                    continue
                seen.add((first, second))
                same_asset = bool(left.get("asset_id") and left.get("asset_id") == right.get("asset_id"))
                suggestions.append({"id": identity(first, second), "source": first, "target": second, "status": "suggested", "distance_m": round(distance, 2), "time_offset_hours": round(offset, 2), "relationship": "shared_asset" if same_asset else "shared_location", "same_asset": same_asset, "reason": f"Compatible {left['domain']} / {right['domain']} observations within {max_distance_m:g} m and {max_hours:g} h; operator review required", "provenance": "Derived", "limitation": "Correlation is not causation; independent case histories are preserved"})
    return suggestions


def compare_followup(before: list[dict], after: list[dict], min_hours: int = 24) -> dict:
    """Compare like local hour/weekday quantities; omitted rows reduce coverage.

    Only hourly input is eligible. The inferred windows span first interval start
    to last interval end, with a minimum of min_hours. Missing interior intervals
    are counted even if the same hours are missing from both windows.
    """
    if min_hours < 1:
        raise ValueError("Minimum follow-up duration must be positive")

    def by_slot(values: list[dict]) -> tuple[dict, float, float]:
        result = defaultdict(list)
        timestamps = []
        valid_hours = 0
        for row in sorted(values, key=lambda r: r["timestamp"]):
            timestamp = pd.Timestamp(row["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError("Follow-up timestamps require explicit timezone")
            if row.get("interval_minutes", 60) != 60:
                raise ValueError("Comparable follow-up currently requires hourly interval quantities")
            if timestamps and timestamp < timestamps[-1] + pd.Timedelta(hours=1):
                raise ValueError("Duplicate or overlapping follow-up intervals are unsupported")
            timestamps.append(timestamp)
            quantity = row.get("quantity")
            if quantity is not None and isinstance(quantity, (int, float)) and math.isfinite(quantity) and quantity >= 0 and row.get("quality_flag", "valid") == "valid" and row.get("active", True):
                timestamp = timestamp.tz_convert("Asia/Kolkata")
                result[(timestamp.weekday(), timestamp.hour)].append(quantity)
                valid_hours += 1
        span = max(min_hours, (timestamps[-1] - timestamps[0]).total_seconds() / 3600 + 1) if timestamps else min_hours
        return result, valid_hours / span, span

    assets = {r.get("asset_id") for r in before + after if r.get("asset_id")}
    units = {r.get("unit") for r in before + after if r.get("unit")}
    if len(assets) > 1 or len(units) > 1:
        raise ValueError("Follow-up compares a single asset and a single normalized unit")
    left, left_coverage, left_span = by_slot(before)
    right, right_coverage, right_span = by_slot(after)
    pairs = [(np.mean(left[k]), np.mean(right[k])) for k in left.keys() & right.keys()]
    expected_pairs = min(168, max(left_span, right_span))
    coverage = min(left_coverage, right_coverage, len(pairs) / expected_pairs)
    diagnostics = {"before_coverage": left_coverage, "after_coverage": right_coverage, "before_window_hours": left_span, "after_window_hours": right_span, "coverage_method": "Valid hourly duration / elapsed window, plus matched hour-of-week coverage; absent rows are missing", "unit": next(iter(units)) if units else "supplied interval quantity"}
    if len(pairs) < min_hours or coverage < .8:
        return safe({"status": "insufficient_followup", "paired_hours": len(pairs), "coverage": coverage, "closure_eligible": False, "reason": f"At least {min_hours} comparable hour-of-week observations and 80% coverage required; missing data never counts as improvement", **diagnostics})
    observed_change = float(sum(a - b for a, b in pairs))
    return safe({"status": "comparison_available", "paired_hours": len(pairs), "coverage": coverage, "observed_change": observed_change, "closure_eligible": False, "requires_human_review": True, "interpretation": "Observed difference in comparable windows; not causally proven savings or evidence of verified repair", **diagnostics})


def _finding(domain: str, zone: str, title: str, severity: str,
             reasons: list[str], evidence: dict) -> dict:
    start = safe(CLOCK - timedelta(hours=3))
    return {"id": identity(domain, zone, title, start), "asset_id": f"{domain}-{zone}", "zone_id": zone, "domain": domain, "title": title, "severity": severity, "start": start, "end": safe(CLOCK), "reason_codes": reasons, "estimated_excess": None, "unit": None, "evidence": {"source": "Synthetic", "config_version": CONFIG_VERSION, **evidence}}


def generate_domain_inputs(seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    roads = [{"id": f"roads-{z['id']}", "asset_id": f"roads-{z['id']}", "zone_id": z["id"], "name": f"{z['name']} road", "severity": [4, 3, 5][i], "extent_m2": [3.8, 1.4, 6.2][i], "daily_exposure": [6500, 9200, 2800][i], "repeat_count": [2, 1, 4][i], "vulnerable_location": [1, 0, 1][i], "cost": [42000, 28000, 61000][i], "category": "pothole" if i != 1 else "surface_cracking", "inspected": True, "source": "Synthetic", "observed_at": safe(CLOCK - timedelta(hours=3))} for i, z in enumerate(ZONES)]
    bins = [{"id": f"waste-{z['id']}", "asset_id": f"waste-{z['id']}", "zone_id": z["id"], "name": f"{z['name']} collection point", "capacity_l": 1000, "estimated_volume_l": [920, 840, 680][i], "fill_fraction": [.92, .84, .68][i], "overdue": i == 2, "hours_since_collection": [28, 23, 52][i], "x_km": [1.2, 2.4, 1.8][i], "y_km": [1.1, 1.5, 2.6][i], "source": "Synthetic"} for i, z in enumerate(ZONES)]
    lights = []
    for z, zone in enumerate(ZONES):
        for h in range(48):
            stamp = safe(CLOCK - timedelta(hours=48 - h))
            on = streetlight_expected(stamp)
            if z == 0 and h >= 41:
                on = False
            if z == 1 and 26 <= h <= 29:
                on = True
            lights.append({"id": identity("streetlights", zone["id"], stamp), "asset_id": f"streetlights-{zone['id']}", "zone_id": zone["id"], "timestamp": stamp, "on": None if z == 2 and h >= 45 else on, "source": "Synthetic"})
    facilities = [{"id": f"general-{z['id']}", "zone_id": z["id"], "name": f"{z['name']} public facility", "category": ["damaged_bench", "unsafe_public_space", "sanitation_issue"][i], "severity": [2, 4, 3][i], "exposure": [35, 75, 50][i], "repeat_count": [0, 2, 1][i], "source": "Synthetic", "inspected": True, "condition_index": round(float(rng.uniform(35, 70)), 1)} for i, z in enumerate(ZONES)]
    return {"roads": roads, "waste": bins, "streetlights": lights, "general": facilities}


def _base_result(domain: str, method: str) -> dict:
    return {"domain": domain, "series": [], "findings": [], "forecast": {"status": "not_applicable", "reason": "Domain uses an explicit rule or scenario model"}, "evaluation": {"status": "rule_based", "method": "Deterministic analytical rules; verified with boundary and conservation tests", "accuracy": None}, "quality": {"coverage": 1., "missing": 0, "invalid": 0, "stale": False, "notes": ["Synthetic observations; no live utility connection"]}, "details": {"method": method, "source": "Synthetic", "config_version": CONFIG_VERSION}}


def analyze_roads(observations: list[dict], budget: float = 100000, priority_weights: dict | None = None) -> dict:
    plan = plan_road_budget(observations, budget, priority_weights)
    result = _base_result("roads", plan["method"])
    result["details"].update({"plan": plan, "priorities": plan["priorities"], "budget": budget, "unit": "priority / 100", "limitations": ["Inspection inputs and configured costs are synthetic", "No image-derived measurements or engineering certification", "Missing components contribute zero; inspect missing inputs before ranking"]})
    for item in plan["priorities"]:
        if item["score"] >= 40:
            result["findings"].append(_finding("roads", item["zone_id"], "Road condition requires repair review", "high" if item["score"] >= 65 else "medium", ["road_condition", "recurrence" if item["repeat_count"] else "damage_observed"], {"priority": item["score"], "components": item["components"], "missing_inputs": item["missing_inputs"], "inspection": item, "explanation": "Priority combines recorded damage, exposure, repeat history, and vulnerable-location context.", "next_action": item["recommended_treatment"]}))
    return safe(result)


def analyze_drainage(parameters: dict | None = None) -> dict:
    p = parameters or {}
    simulation = simulate_drainage(**{k: v for k, v in p.items() if k in ("rainfall_mmph", "area_m2", "runoff_coefficient", "discharge_m3ph", "storage_capacity_m3", "initial_m3", "blockage", "hours", "dt_hours")})
    result = _base_result("drainage", "Transparent rainfall-runoff storage screening; constant-rate bounded mass balance")
    result["details"].update({"simulation": simulation, "unit": "m³", "limitations": ["Scenario model, not a validated flood forecast or evacuation tool", "Connected drains indicate potentially relevant inspection areas, not proven hydraulic propagation"]})
    if simulation["status"] != "ready":
        result["quality"].update({"coverage": 0., "missing": 1, "notes": [simulation["reason"]]})
        result["findings"] = [_finding("drainage", "river", "Rainfall input missing; screening limited", "medium", ["sensor_quality"], {"explanation": simulation["reason"], "next_action": "Obtain a documented rainfall input or inspect recorded blockage separately."})]
        return result
    for row in simulation["series"]:
        result["series"].append({"timestamp": safe(CLOCK + timedelta(hours=row["hour"])), "actual": row["storage_m3"], "expected": simulation["capacity_m3"], "lower": 0, "upper": simulation["capacity_m3"], "flag": row["overflow_m3"] > 0, "asset_id": "drainage-river", "zone_id": "river", "unit": "m³", "source": "Simulated"})
    if simulation["overflow_m3"] > 0 or simulation["blockage_fraction"] >= .5:
        result["findings"].append(_finding("drainage", "river", "Drainage capacity constraint in modeled rainfall", "high" if simulation["overflow_m3"] > 0 else "medium", ["recorded_blockage", "modeled_overflow"], {"rainfall_mmph": simulation["rainfall_mmph"], "blockage_fraction": simulation["blockage_fraction"], "modeled_overflow_m3": simulation["overflow_m3"], "source": "Simulated", "explanation": "Configured runoff exceeds blockage-adjusted discharge/storage in this scenario; this is not a measured flood.", "next_action": "Inspect the recorded blockage and consider clearance; verify with follow-up observations."}))
    return safe(result)


def analyze_waste(bins: list[dict], capacity: float = 1600) -> dict:
    plan = plan_waste_collection(bins, capacity)
    result = _base_result("waste", plan["method"])
    observations = []
    for bin in bins:
        volume = bin.get("estimated_volume_l")
        if volume is not None:
            history = [{"timestamp": safe(CLOCK - timedelta(hours=24 - h * 4)), "volume_l": max(0., volume - (6 - h) * 78)} for h in range(7)]
            bin["time_to_capacity"] = time_to_capacity(history, bin["capacity_l"])
            observations.extend([{**r, "asset_id": bin["id"]} for r in history])
            if bin["fill_fraction"] >= .8 or bin.get("overdue"):
                result["findings"].append(_finding("waste", bin["zone_id"], "Collection overdue" if bin.get("overdue") else "Collection point approaching capacity", "high" if bin["fill_fraction"] >= 1 else "medium", ["missed_collection" if bin.get("overdue") else "high_fill"], {"estimated_volume_l": volume, "capacity_l": bin["capacity_l"], "fill_fraction": bin["fill_fraction"], "time_to_capacity": bin["time_to_capacity"], "explanation": "Synthetic fill observations cross the 80% trigger or the configured collection schedule is overdue.", "next_action": "Assign a collection trip; record completion and a new fill observation."}))
    primary = bins[0]["id"] if bins else None
    result["series"] = [{"timestamp": r["timestamp"], "actual": r["volume_l"], "expected": 800, "lower": 0, "upper": 1000, "flag": r["volume_l"] >= 800, "asset_id": r["asset_id"], "zone_id": bins[0]["zone_id"], "unit": "L"} for r in observations if r["asset_id"] == primary]
    result["details"].update({"plan": plan, "bins": bins, "observations": observations, "unit": "L", "limitations": ["Fill values are synthetic observations", "Straight-line planning distance is not a navigable route or exact travel time", "Capacity assumes homogeneous volume; compaction and weight are unmodeled"]})
    return safe(result)


def analyze_general(facilities: list[dict]) -> dict:
    result = _base_result("general", "Inspection-based service priority and department routing; not predictive AI")
    priorities = []
    for item in facilities:
        score = min(100, item["severity"] / 5 * 60 + item["exposure"] / 100 * 25 + min(item["repeat_count"], 3) / 3 * 15)
        priorities.append({**item, "score": score, "components": {"severity": item["severity"] / 5 * 60, "exposure": item["exposure"] / 100 * 25, "recurrence": min(item["repeat_count"], 3) / 3 * 15}})
        if score >= 35:
            result["findings"].append(_finding("general", item["zone_id"], item["category"].replace("_", " ").capitalize() + " · inspection follow-up", "high" if score >= 65 else "medium", [item["category"]], {"priority": score, "observation": item, "explanation": "Recorded synthetic inspection severity, public exposure, and recurrence determine the service priority.", "next_action": "Assign facilities inspection; record intervention, follow-up evidence, and operator review."}))
    result["details"].update({"priorities": priorities, "unit": "priority / 100", "checklist": ["Confirm asset and category", "Record observed condition", "Assess public exposure without certifying safety", "Document intervention", "Obtain follow-up inspection", "Operator reviews closure"], "limitations": ["General work orders are an accountable workflow, not predictive AI"]})
    return safe(result)


def _public_analysis(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}


def analyze_readings(domain: str, readings: list[dict], **parameters: Any) -> dict:
    """Stable worker entry point; stored readings are analyzed without truth labels."""
    result = _public_analysis(analyze_consumption(readings, domain, **parameters))
    result["dataset_id"] = f"stored-{domain}-{identity(json.dumps(safe(readings), sort_keys=True))}"
    result["model_version"] = MODEL_VERSION
    return result


@lru_cache(maxsize=4)
def _evaluations() -> dict:
    return {d: evaluate_consumption(d) for d in ("water", "electricity")}


def bootstrap_dataset(seed: int = SEED, days: int = 56) -> dict:
    """Generate observations and run actual analytics; caller persists all data.

    Evaluation uses independent seed 37031 and a held-out final week. No hidden
    truth is exposed as a detector feature or mixed into stored meter readings.
    """
    domains, all_readings = {}, []
    for domain in ("water", "electricity"):
        readings, _truth = generate_consumption(domain, seed=seed, days=days)
        all_readings.extend(readings)
        domains[domain] = _public_analysis(analyze_consumption(readings, domain))
        domains[domain]["evaluation"] = _evaluations()[domain]
    inputs = generate_domain_inputs(seed)
    domains["water"]["details"]["tank"] = simulate_tank()
    domains["electricity"]["details"].update({"voltage_status": "Synthetic voltage telemetry available", "voltage_thresholds": {"lower": 207, "upper": 253, "unit": "V", "basis": "Illustrative configured demonstration thresholds, not regulatory certification"}, "voltage_observations": [{"timestamp": r["timestamp"], "voltage": r["voltage"], "asset_id": r["asset_id"]} for r in all_readings if r["domain"] == "electricity" and r["asset_id"] == "electricity-market"][-48:], "safety": "Keep away from suspected electrical hazards and use verified local emergency or utility channels. Do not touch, test, or repair energized equipment."})
    domains["roads"] = analyze_roads(inputs["roads"])
    domains["drainage"] = analyze_drainage()
    domains["waste"] = analyze_waste(inputs["waste"])
    domains["streetlights"] = analyze_streetlights(inputs["streetlights"])
    domains["general"] = analyze_general(inputs["general"])
    network = network_data()
    assets = asset_registry() + [n for n in network["nodes"] if n["id"] not in {a["id"] for a in asset_registry()}]
    findings = [f for d in domains.values() for f in d["findings"]]
    return safe({"zones": ZONES, "assets": assets, "readings": all_readings, "domains": domains, "network": network, "suggestions": cross_domain_suggestions(findings, assets), "metadata": {"dataset_id": f"civicsignal-synthetic-{seed}-{days}d-v1", "seed": seed, "days": days, "rows": len(all_readings), "clock": safe(CLOCK), "interval_convention": "UTC interval start; interval quantities, not counters", "checksum": identity(json.dumps(all_readings, sort_keys=True)), "model_version": MODEL_VERSION, "config_version": CONFIG_VERSION, "provenance": "Synthetic", "limitations": "Independent hackathon prototype; synthetic district meters do not represent real infrastructure"}})


SCENARIOS = {
    "water": ["normal", "overnight_leak", "sustained_excess", "legitimate_spike", "sensor_failure", "supply_interruption", "intervention"],
    "electricity": ["normal", "sustained_excess", "legitimate_spike", "voltage_fluctuation", "reported_outage", "sensor_failure", "intervention"],
    "roads": ["pothole", "recurring_damage", "budget", "repair"],
    "drainage": ["blockage", "rainfall", "sensor_failure", "maintenance"],
    "waste": ["capacity", "missed_pickup", "overflow", "collection"],
    "streetlights": ["normal", "failed_lamp", "stuck_on", "sensor_failure", "repair"],
    "general": ["damage", "repair"],
}


def run_scenario(domain: str, scenario: str, parameters: dict | None = None) -> dict:
    """Recompute a branch from the same deterministic observations.

    API persists the returned result and scenario parameters/clock for replay.
    Counterfactual interventions modify modeled observations; they never imply
    completed real work, prove savings, or authorize case closure.
    """
    if domain == "infrastructure":
        domain = "general"
    if domain not in DOMAINS:
        raise ValueError("Unknown civic domain")
    p = dict(parameters or {})
    seed = int(p.get("seed", SEED))
    name = scenario.lower().replace("-", "_").replace(" ", "_")
    name = {"leak": "overnight_leak", "overnight_excess": "overnight_leak", "sensor": "sensor_failure", "stale_meter": "sensor_failure", "stale": "sensor_failure", "recovery": "intervention", "repaired_lamp": "repair", "completed_pickup": "collection", "cleared": "maintenance", "new_pothole": "pothole", "constrained_collection": "capacity", "blocked_drain": "blockage", "increased_rainfall": "rainfall", "repair_recorded": "repair"}.get(name, name)
    if name not in SCENARIOS[domain]:
        raise ValueError(f"Unknown scenario for {domain}; choose: {', '.join(SCENARIOS[domain])}")
    if domain in ("water", "electricity"):
        # Baseline is one deterministic healthy history; branch alters only the
        # specified final observations and context, never baseline fit history.
        records, _ = generate_consumption(domain, seed=seed, anomalies=False)
        baseline = analyze_consumption(records, domain)
        modified = [dict(r) for r in records]
        target = p.get("asset_id", f"{domain}-{'market' if domain == 'electricity' else 'river'}")
        if target not in {r["asset_id"] for r in modified}:
            raise ValueError("Scenario asset is not in the generated dataset")
        hours = int(p.get("hours", 12))
        if hours < 1 or hours > 48:
            raise ValueError("Consumption scenario duration must be 1–48 hours")
        cutoff = CLOCK - timedelta(hours=hours)
        magnitude = float(p.get("magnitude", p.get("excess", 270 if domain == "water" else 3.4)))
        _nonnegative(magnitude=magnitude)
        for row in modified:
            if row["asset_id"] != target or pd.Timestamp(row["timestamp"]) < cutoff:
                continue
            if name in ("overnight_leak", "sustained_excess"):
                row["quantity"] += magnitude
            elif name == "legitimate_spike":
                row["quantity"] *= 1.8
                row["expected_multiplier"] *= 1.8
            elif name == "sensor_failure":
                row["quantity"], row["quality_flag"] = None, "missing"
            elif name in ("supply_interruption", "reported_outage"):
                row["quantity"] = 0.
            elif name == "voltage_fluctuation":
                row["voltage"] = float(p.get("voltage", 195))
            elif name == "intervention":
                if pd.Timestamp(row["timestamp"]) < CLOCK - timedelta(hours=max(3, hours // 2)):
                    row["quantity"] += magnitude
            row["source"] = "Simulated"
        result = analyze_consumption(modified, domain, tariff=p.get("tariff"), voltage_lower_v=float(p.get("voltage_lower_v", 207)), voltage_upper_v=float(p.get("voltage_upper_v", 253)))
        if name == "voltage_fluctuation":
            voltage_rows = [r for r in modified if r["asset_id"] == target and pd.Timestamp(r["timestamp"]) >= cutoff]
            result["details"]["voltage_observations"] = [{"timestamp": r["timestamp"], "voltage": r["voltage"]} for r in voltage_rows]
        if name == "reported_outage":
            result["details"]["outage_context"] = "Synthetic independent outage report accompanies zero readings; unverified until inspection. Zero consumption alone is insufficient."
        result["details"]["tank"] = simulate_tank(outflow_lph=float(p.get("outflow_lph", 1800 + magnitude if domain == "water" and name == "overnight_leak" else 1800))) if domain == "water" else None
        checksum = identity(json.dumps(records, sort_keys=True))
        modified_checksum = identity(json.dumps(modified, sort_keys=True))
        comparison = {"baseline_findings": len(baseline["findings"]), "modified_findings": len(result["findings"]), "baseline_excess": baseline["details"]["estimated_excess"], "modified_excess": result["details"]["estimated_excess"], "difference": result["details"]["estimated_excess"] - baseline["details"]["estimated_excess"], "unit": "L" if domain == "water" else "kWh"}
    else:
        inputs = generate_domain_inputs(seed)
        checksum = identity(json.dumps(inputs, sort_keys=True))
        if domain == "roads":
            records = inputs["roads"]
            priority_weights = p.get("priority_weights")
            baseline = analyze_roads(records, priority_weights=priority_weights)
            modified = [dict(r) for r in records]
            if name == "pothole":
                modified[0].update({"severity": 5, "extent_m2": 6.5})
            elif name == "recurring_damage":
                modified[0]["repeat_count"] = 5
            elif name == "repair":
                modified[0].update({"severity": 0, "extent_m2": 0, "repeat_count": 0})
            result = analyze_roads(modified, float(p.get("budget", 65000 if name == "budget" else 100000)), priority_weights)
            before_value, after_value = baseline["details"]["plan"]["spent"], result["details"]["plan"]["spent"]
            unit = "INR planned"
        elif domain == "drainage":
            baseline = analyze_drainage()
            dp = {"rainfall_mmph": float(p.get("rainfall", p.get("rainfall_mmph", 32))), "blockage": float(p.get("blockage", .65)), "hours": float(p.get("hours", 6))}
            if name == "rainfall":
                dp["rainfall_mmph"] = float(p.get("rainfall", p.get("rainfall_mmph", 52)))
            elif name == "blockage":
                dp["blockage"] = float(p.get("blockage", .85))
            elif name == "maintenance":
                dp["blockage"] = float(p.get("blockage", .05))
            elif name == "sensor_failure":
                dp["rainfall_mmph"] = None
            result = analyze_drainage(dp)
            before_value, after_value = baseline["details"]["simulation"].get("overflow_m3"), result["details"]["simulation"].get("overflow_m3")
            unit = "m³ modeled overflow"
            modified = dp
        elif domain == "waste":
            records = inputs["waste"]
            baseline = analyze_waste([dict(r) for r in records])
            modified = [dict(r) for r in records]
            if name == "overflow":
                modified[0].update({"estimated_volume_l": 1100, "fill_fraction": 1.1})
            elif name == "missed_pickup":
                modified[0].update({"overdue": True, "hours_since_collection": 72})
            elif name == "collection":
                for item in modified:
                    item.update({"estimated_volume_l": 50, "fill_fraction": .05, "overdue": False, "hours_since_collection": 0})
            result = analyze_waste(modified, float(p.get("capacity", p.get("vehicle_capacity_l", 950 if name == "capacity" else 1600))))
            before_value, after_value = baseline["details"]["plan"]["trips_needed"], result["details"]["plan"]["trips_needed"]
            unit = "planned trips"
        elif domain == "streetlights":
            on_hour, off_hour = int(p.get("on_hour", 18)), int(p.get("off_hour", 6))
            streetlight_expected(CLOCK.isoformat(), on_hour, off_hour)  # Validate schedule before building either branch.
            records = [{**r, "on": streetlight_expected(r["timestamp"], on_hour, off_hour)} for r in inputs["streetlights"]]
            baseline = analyze_streetlights(records, on_hour, off_hour)
            modified = [dict(r) for r in records]
            for row in modified:
                if row["asset_id"] != "streetlights-river":
                    continue
                stamp = pd.Timestamp(row["timestamp"])
                if stamp < CLOCK - timedelta(hours=24):
                    continue
                if name == "failed_lamp" and streetlight_expected(row["timestamp"], on_hour, off_hour):
                    row["on"] = False
                elif name == "stuck_on":
                    row["on"] = True
                elif name == "sensor_failure" and stamp >= CLOCK - timedelta(hours=8):
                    row["on"] = None
                elif name == "repair" and stamp < CLOCK - timedelta(hours=4):
                    row["on"] = False
            result = analyze_streetlights(modified, on_hour, off_hour)
            before_value, after_value = len(baseline["findings"]), len(result["findings"])
            unit = "schedule events"
        else:
            records = inputs["general"]
            baseline = analyze_general(records)
            modified = [dict(r) for r in records]
            modified[0].update({"severity": 5 if name == "damage" else 0, "repeat_count": 2 if name == "damage" else 0})
            result = analyze_general(modified)
            before_value, after_value = len(baseline["findings"]), len(result["findings"])
            unit = "review findings"
        modified_checksum = identity(json.dumps(modified, sort_keys=True))
        comparison = {"baseline_findings": len(baseline["findings"]), "modified_findings": len(result["findings"]), "baseline_value": before_value, "modified_value": after_value, "difference": after_value - before_value if after_value is not None and before_value is not None else None, "unit": unit}
    result = _public_analysis(result)
    result.update({"comparison": comparison, "baseline": _public_analysis(baseline), "metadata": {"scenario": name, "domain": domain, "seed": seed, "dataset_checksum": checksum, "modified_checksum": modified_checksum, "clock": safe(CLOCK), "model_version": MODEL_VERSION, "config_version": CONFIG_VERSION, "parameters": p, "provenance": "Simulated", "interpretation": "Computed counterfactual branch from the same original observations; no verified repair or causal savings claim", "replay": "Same domain, scenario, seed and parameters reproduce these results"}})
    return safe(result)
