"""Read-only views of persisted scenario observations and analytical events.

The replay does not invent historical detector runs or workflow decisions. Event
aggregates become visible once their entire recorded evidence window is visible.
"""
from datetime import datetime, timezone


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def playback_analysis(result, timestamp, completed=False):
    """Summarize only stored rows/windows visible at the selected replay frame.

    Series timestamps are recorded interval starts, matching the chart. At the
    final frame the saved analysis clock includes end-of-window quality findings.
    A stored finding's window end is not claimed to be its first detection time.
    """
    result = result if isinstance(result, dict) else {}
    cutoff = _timestamp(timestamp)
    metadata = result.get("metadata") or {}
    clock = _timestamp(metadata.get("clock"))
    if completed and clock is not None:
        cutoff = max(cutoff, clock) if cutoff else clock
    as_of = cutoff.isoformat() if cutoff else None

    def branch_view(branch, case_ids=None):
        branch = branch if isinstance(branch, dict) else {}
        rows = [row for row in branch.get("series", []) if isinstance(row, dict)
                and (stamp := _timestamp(row.get("timestamp"))) is not None
                and cutoff is not None and stamp <= cutoff]
        events = []
        for index, finding in enumerate(branch.get("findings", [])):
            if not isinstance(finding, dict):
                continue
            end = _timestamp(finding.get("end"))
            # Unknown observation boundaries cannot be assigned to an early frame.
            if cutoff is None or (end is None and not completed) or (end and end > cutoff):
                continue
            evidence = finding.get("evidence") or {}
            events.append({
                "id": finding.get("id"), "title": finding.get("title"),
                "asset_id": finding.get("asset_id"), "zone_id": finding.get("zone_id"),
                "severity": finding.get("severity"), "start": finding.get("start"),
                "end": finding.get("end"), "available_at": end.isoformat() if end else as_of,
                "availability_basis": "recorded_window_end" if end else "completed_snapshot",
                "reason_codes": finding.get("reason_codes", []),
                "source": evidence.get("source", "Derived"),
                "interval_count": evidence.get("interval_count"),
                "estimated_excess": finding.get("estimated_excess"), "unit": finding.get("unit"),
                "case_id": case_ids[index] if case_ids and index < len(case_ids) else None,
            })
        events.sort(key=lambda item: (item["available_at"] or "", item["id"] or ""))
        return {
            "observations": len(rows),
            "missing_observations": sum(row.get("actual") is None for row in rows),
            "flagged_observations": sum(row.get("flag") is True for row in rows),
            "asset_ids": sorted({row["asset_id"] for row in rows if row.get("asset_id")}),
            "events": events,
        }

    return {
        "mode": "stored_result_replay", "as_of": as_of, "completed": bool(completed),
        "baseline": branch_view(result.get("baseline")),
        "modified": branch_view(result, result.get("case_ids")),
        "interpretation": "Recorded analyses are revealed after their full evidence window. This is not the first detection time or a reconstruction of human decisions.",
    }
