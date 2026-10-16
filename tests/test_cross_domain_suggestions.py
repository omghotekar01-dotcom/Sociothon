from services.analytics.pipeline import asset_registry, cross_domain_suggestions


def test_suggestions_require_compatible_domains_within_configured_distance_and_time():
    cases = [
        {"id": "water-1", "domain": "water", "asset_id": "meter", "start": "2026-10-15T00:00:00Z"},
        {"id": "power-1", "domain": "electricity", "asset_id": "feeder", "start": "2026-10-15T01:00:00+01:00"},
        {"id": "road-1", "domain": "roads", "asset_id": "road", "start": "2026-10-20T00:30:00Z"},
    ]
    assets = [
        {"id": "meter", "lat": 18.52, "lon": 73.85},
        {"id": "feeder", "lat": 18.5201, "lon": 73.8501},
        {"id": "road", "lat": 18.52, "lon": 73.85},
    ]

    result = cross_domain_suggestions(cases, assets, max_distance_m=50, max_hours=2)

    assert len(result) == 1
    assert result[0]["status"] == "suggested"
    assert result[0]["relationship"] == "shared_location"
    assert result[0]["distance_m"] < 50
    assert result[0]["time_offset_hours"] == 0
    assert "causation" not in result[0]
    assert "not causation" in result[0]["limitation"].lower()
    assert cross_domain_suggestions(cases, assets, max_distance_m=5, max_hours=2) == []


def test_shared_asset_is_labeled_separately_from_shared_location():
    cases = [
        {"id": "water-2", "domain": "water", "asset_id": "shared", "created_at": "2026-10-15T00:00:00Z"},
        {"id": "power-2", "domain": "electricity", "asset_id": "shared", "created_at": "2026-10-15T00:10:00Z"},
    ]
    assets = [{"id": "shared", "lat": 18.52, "lon": 73.85}]

    suggestion, = cross_domain_suggestions(cases, assets)

    assert suggestion["relationship"] == "shared_asset"
    assert suggestion["same_asset"] is True
    assert suggestion["distance_m"] == 0


def test_explicitly_empty_coordinate_registry_does_not_fall_back_to_seed_assets():
    cases = [
        {"id": "water", "domain": "water", "asset_id": "water-river", "created_at": "2026-10-15T00:00:00Z"},
        {"id": "electricity", "domain": "electricity", "asset_id": "electricity-river", "created_at": "2026-10-15T00:10:00Z"},
    ]
    assert cross_domain_suggestions(cases, assets=[]) == []
    assert cross_domain_suggestions(cases, assets=asset_registry())


def test_bad_coordinates_and_naive_times_are_not_used_as_evidence():
    cases = [
        {"id": "water", "domain": "water", "asset_id": "meter-a", "start": "not a timestamp", "created_at": "2026-10-15T00:00:00Z"},
        {"id": "electricity", "domain": "electricity", "asset_id": "meter-b", "start": "2026-10-15T01:00:00", "created_at": "2026-10-15T01:00:00"},
    ]
    assets = [
        {"id": "meter-a", "lat": 999, "lon": 73.85},
        {"id": "meter-b", "lat": 18.52, "lon": 73.85},
    ]
    assert cross_domain_suggestions(cases, assets) == []
