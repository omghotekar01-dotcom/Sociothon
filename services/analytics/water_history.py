"""Explicitly recorded schedule history and complete-coverage meter comparison."""
from .water_operations import instant, interval, meter_total, schedule_review


def historical_schedule_review(rows, entries):
    active = [entry for entry in entries if not entry.get("revoked_at")]
    output = []
    for row in rows:
        try:
            start, end, volume = interval(row)
        except (ValueError, TypeError, KeyError, OverflowError):
            output.extend(schedule_review([row], {}))
            continue
        overlapping = [e for e in active if instant(e["effective_from"]) < end and instant(e["effective_until"]) > start]
        covering = [e for e in overlapping if instant(e["effective_from"]) <= start and instant(e["effective_until"]) >= end]
        if len(covering) == 1 and len(overlapping) == 1:
            entry = covering[0]
            result = schedule_review([row], entry["schedule"])[0]
            output.append({**result, "schedule_record_id": entry["id"], "schedule_configuration_version": entry["configuration_version"], "schedule_source_reference": entry["source_reference"]})
        else:
            output.append({"reading_id": row["id"], "asset_id": row["asset_id"], "timestamp": row["timestamp"], "source": row.get("source"), "volume_l": volume,
                           "status": "history_boundary" if overlapping else "history_missing",
                           "explanation": "The observation crosses recorded schedule periods or a gap; no invented split or current-schedule fallback." if overlapping else "No effective schedule is recorded for this observation. Current configuration is not historical evidence."})
    return output


def compare_meter_group(before_rows, after_rows, ids, before_start, before_end, after_start, after_end):
    """Exact complete-window totals; no extrapolation, inferred zeros or savings."""
    meters = {ident: {"before": meter_total([r for r in before_rows if r["asset_id"] == ident], before_start, before_end),
                      "after": meter_total([r for r in after_rows if r["asset_id"] == ident], after_start, after_end)} for ident in ids}
    issues = []
    if (before_end-before_start).total_seconds() < 86400:
        issues.append("At least 24 hours in each window are required.")
    # Only UTC and Asia/Kolkata schedules are supported; neither changes UTC offset.
    if (after_start-before_start).total_seconds() % (7*86400) != 0:
        issues.append("Align windows to the same weekday and local time, an exact number of weeks apart.")
    if any(m[side]["status"] != "ready" for m in meters.values() for side in ("before", "after")):
        issues.append("Every selected meter must have complete, valid, non-overlapping observations in both windows.")
    ready = not issues
    before = sum(m["before"]["total_l"] for m in meters.values()) if ready else None
    after = sum(m["after"]["total_l"] for m in meters.values()) if ready else None
    return {"status": "comparison_available" if ready else "insufficient_followup", "meters": meters, "issues": issues,
            "before_total_l": before, "after_total_l": after, "observed_reduction_l": before-after if ready else None,
            "closure_eligible": False, "requires_human_review": True,
            "interpretation": "Difference in recorded volumes for the same meters and matched windows; not verified savings, repair or causal impact. Review supply schedules, demand and storage changes."}
