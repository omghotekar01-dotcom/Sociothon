from copy import deepcopy

from services.api.playback import playback_analysis


def scenario():
    return {
        "metadata": {"clock": "2026-10-13T03:00:00Z"},
        "series": [
            {"timestamp": "2026-10-13T00:00:00Z", "asset_id": "water-river", "actual": None, "flag": False},
            {"timestamp": "2026-10-13T01:00:00Z", "asset_id": "water-river", "actual": 0, "flag": True},
            {"timestamp": "2026-10-13T02:00:00Z", "asset_id": "water-river", "actual": 7, "flag": True},
        ],
        "findings": [
            {"id": "window", "title": "Persistent observation", "start": "2026-10-13T01:00:00Z", "end": "2026-10-13T02:00:00Z", "estimated_excess": 7, "evidence": {"interval_count": 2}},
            {"id": "quality", "title": "Full-window quality", "end": "2026-10-13T03:00:00Z", "evidence": {}},
            {"id": "snapshot", "title": "Untimed snapshot", "evidence": {}},
        ],
        "case_ids": ["case-window", "case-quality", "case-snapshot"],
        "baseline": {"series": [{"timestamp": "2026-10-13T00:00:00Z", "actual": 3}], "findings": []},
    }


def test_replay_reveals_only_completed_evidence_windows_without_future_aggregates():
    result = scenario()
    original = deepcopy(result)
    early = playback_analysis(result, "2026-10-13T01:00:00Z")
    assert early["modified"]["observations"] == 2
    assert early["modified"]["missing_observations"] == 1  # Zero is an observed value.
    assert early["modified"]["flagged_observations"] == 1
    assert early["modified"]["events"] == []
    later = playback_analysis(result, "2026-10-13T02:00:00Z")
    assert [event["id"] for event in later["modified"]["events"]] == ["window"]
    assert later["modified"]["events"][0]["case_id"] == "case-window"
    assert later["modified"]["events"][0]["estimated_excess"] == 7
    assert later["baseline"]["events"] == []
    assert result == original  # Seeking does not rewrite stored output or decisions.


def test_completed_frame_uses_saved_analysis_clock_for_quality_and_untimed_snapshots():
    state = playback_analysis(scenario(), "2026-10-13T02:00:00Z", completed=True)
    assert state["as_of"] == "2026-10-13T03:00:00+00:00"
    assert [event["id"] for event in state["modified"]["events"]] == ["window", "quality", "snapshot"]
    assert state["modified"]["events"][-1]["availability_basis"] == "completed_snapshot"
    assert state["completed"] is True


def test_bad_or_timezone_ambiguous_clocks_cannot_reveal_early_results():
    for timestamp in (None, "invalid", "2026-10-13T02:00:00"):
        state = playback_analysis(scenario(), timestamp)
        assert state["as_of"] is None
        assert state["modified"]["events"] == []
        assert state["modified"]["observations"] == 0
    equivalent = playback_analysis(scenario(), "2026-10-13T07:30:00+05:30")
    assert [event["id"] for event in equivalent["modified"]["events"]] == ["window"]
