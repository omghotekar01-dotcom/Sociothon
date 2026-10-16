"""Interval water accounting and schedule context; never a hydraulic diagnosis."""
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo


def instant(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if value.tzinfo is None:
        raise ValueError("Timestamps must include a timezone.")
    return value.astimezone(timezone.utc)


def interval(row):
    start = instant(row["timestamp"])
    minutes = float(row["interval_minutes"])
    quantity = row.get("quantity")
    factor = {"L": 1., "litres": 1., "liters": 1., "m3": 1000., "m³": 1000., "kL": 1000.}.get(row.get("unit"))
    if not math.isfinite(minutes) or not 0 < minutes <= 1440:
        raise ValueError("Invalid interval duration.")
    if quantity is None or factor is None or row.get("quality_flag") != "valid":
        raise ValueError("Missing or invalid interval observation.")
    quantity = float(quantity)
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError("Invalid interval volume.")
    return start, start + timedelta(minutes=minutes), quantity * factor


def schedule_segments(start, end, windows, timezone_name):
    """Union of weekly half-open windows, including overnight and DST boundaries."""
    zone = ZoneInfo(timezone_name)
    day = start.astimezone(zone).date() - timedelta(days=1)
    last = end.astimezone(zone).date()
    spans = []
    while day <= last:
        for window in windows:
            if day.weekday() not in window["days"]:
                continue
            base = datetime.combine(day, datetime.min.time(), zone)
            a = (base + timedelta(minutes=window["start_minute"])).astimezone(timezone.utc)
            finish = window["end_minute"] + (1440 if window["end_minute"] <= window["start_minute"] else 0)
            b = (base + timedelta(minutes=finish)).astimezone(timezone.utc)
            if a < end and b > start:
                spans.append((max(start, a), min(end, b)))
        day += timedelta(days=1)
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def schedule_review(rows, configuration):
    output = []
    for row in rows:
        item = {"reading_id": row["id"], "asset_id": row["asset_id"], "timestamp": row["timestamp"], "source": row.get("source"), "volume_l": None}
        try:
            start, end, volume = interval(row)
        except (ValueError, TypeError, KeyError, OverflowError):
            output.append({**item, "status": "data_quality", "explanation": "Missing or invalid observation; no consumption conclusion."})
            continue
        item["volume_l"] = volume
        if not configuration.get("supply_windows"):
            output.append({**item, "status": "not_configured", "explanation": "No supply schedule has been recorded."})
            continue
        spans = schedule_segments(start, end, configuration["supply_windows"] + configuration.get("exceptions", []), configuration["timezone"])
        covered = sum((b-a).total_seconds() for a, b in spans)
        duration = (end-start).total_seconds()
        rate = volume * 3600 / duration
        if covered >= duration:
            status, explanation = "within_window", "Within a configured supply or legitimate-use window; this does not establish normal consumption."
        elif covered > 0:
            status, explanation = "straddles_window", "The interval crosses a schedule boundary. Volume cannot be allocated inside/outside without finer readings."
        elif rate > configuration["outside_rate_lph"]:
            status, explanation = "review_outside_window", "Observed flow outside configured windows exceeds the review threshold. Check storage refilling, legitimate use and meter quality; this is not proof of leakage."
        else:
            status, explanation = "below_review_threshold", "Outside configured windows, but not above the configured flow review threshold."
        output.append({**item, "status": status, "explanation": explanation, "observed_rate_lph": rate, "scheduled_fraction": covered/duration})
    return output


def meter_total(rows, start, end):
    spans, errors, sources = [], [], set()
    for row in rows:
        try:
            raw_start = instant(row["timestamp"])
            raw_end = raw_start + timedelta(minutes=float(row["interval_minutes"]))
            if raw_end <= start or raw_start >= end:
                continue
            a, b, volume = interval(row)
            if a < start or b > end:
                errors.append("An interval crosses the selected boundary; select aligned times.")
                continue
            spans.append((a, b, volume))
            sources.add(row.get("source", "Unspecified"))
        except (ValueError, TypeError, KeyError, OverflowError):
            errors.append("Missing, invalid or unsupported interval observation.")
    cursor = start
    for a, b, _ in sorted(spans):
        if a != cursor:
            errors.append("A gap or overlapping interval prevents complete accounting.")
        cursor = max(cursor, b)
    if cursor != end:
        errors.append("Readings do not cover the complete selected window.")
    return {"status": "insufficient_data" if errors else "ready", "total_l": None if errors else sum(v for _, _, v in spans), "intervals": len(spans), "sources": sorted(sources), "issues": sorted(set(errors))}


def water_balance(rows, configuration, start, end, storage_change_l, unmetered_l):
    totals = {}
    for role in ("inlet_ids", "outlet_ids", "consumption_ids"):
        for asset_id in configuration.get(role, []):
            totals[asset_id] = {"role": role, **meter_total([r for r in rows if r["asset_id"] == asset_id], start, end)}
    issues = []
    if not configuration.get("inlet_ids"):
        issues.append("Configure at least one inlet meter.")
    if not configuration.get("boundary_confirmed"):
        issues.append("An administrator must confirm that the boundary and meter hierarchy are complete.")
    if storage_change_l is None:
        issues.append("Record storage change for this exact window, including explicit zero where justified.")
    if unmetered_l is None:
        issues.append("Record authorized unmetered consumption, including explicit zero where justified.")
    if any(v["status"] != "ready" for v in totals.values()):
        issues.append("Every selected meter needs complete valid coverage over the same window.")
    amounts = {role: sum(v["total_l"] or 0 for v in totals.values() if v["role"] == role) for role in ("inlet_ids", "outlet_ids", "consumption_ids")}
    return {"status": "insufficient_data" if issues else "ready", "meters": totals, "issues": issues,
            "inlet_l": None if issues else amounts["inlet_ids"], "outlet_l": None if issues else amounts["outlet_ids"], "consumption_l": None if issues else amounts["consumption_ids"],
            "storage_change_l": storage_change_l, "authorized_unmetered_l": unmetered_l,
            "unaccounted_l": None if issues else amounts["inlet_ids"]-amounts["outlet_ids"]-amounts["consumption_ids"]-storage_change_l-unmetered_l,
            "interpretation": "Unaccounted volume is a signed accounting residual, not confirmed leakage or savings. Review meter uncertainty, unrecorded use and boundary completeness. No missing observations are filled.",
            "provenance": "Derived", "closure_eligible": False}
