from types import SimpleNamespace

from services.api import main as api_main
from services.api.models import Job
from services.api.priorities import DEFAULT_CASE_PRIORITY_WEIGHTS
from services.api.worker import configured_scenario_parameters


class FakeDatabase:
    def __init__(self, config):
        self.config = config

    def get(self, model, key):
        assert key == "platform"
        return self.config


def test_worker_freezes_audited_streetlight_schedule_into_run_parameters():
    db = FakeDatabase(SimpleNamespace(value={"streetlight_on_hour": 17, "streetlight_off_hour": 7}))

    result = configured_scenario_parameters(db, "streetlights", {"seed": 721})

    assert result == {"seed": 721, "case_priority_weights": DEFAULT_CASE_PRIORITY_WEIGHTS, "case_priority_weights_version": 1, "on_hour": 17, "off_hour": 7}


def test_worker_uses_default_schedule_for_legacy_configuration():
    result = configured_scenario_parameters(FakeDatabase(SimpleNamespace(value={})), "streetlights", {})

    assert result == {"case_priority_weights": DEFAULT_CASE_PRIORITY_WEIGHTS, "case_priority_weights_version": 1, "on_hour": 18, "off_hour": 6}


def test_other_domain_scenario_parameters_are_not_modified():
    parameters = {"seed": 12, "budget": 40000}

    result = configured_scenario_parameters(FakeDatabase(None), "roads", parameters)

    assert result == parameters
    assert result is not parameters


def test_worker_freezes_versioned_road_priority_weights_into_run_parameters():
    weights = {"severity": 50, "extent_m2": 15, "daily_exposure": 15, "repeat_count": 10, "vulnerable_location": 10}
    config = SimpleNamespace(value={"road_priority_weights": weights}, version=4)
    result = configured_scenario_parameters(FakeDatabase(config), "roads", {"seed": 721})

    assert result == {"seed": 721, "case_priority_weights": DEFAULT_CASE_PRIORITY_WEIGHTS, "case_priority_weights_version": 4, "priority_weights": weights, "priority_weights_version": 4}


def test_worker_freezes_shared_case_priority_for_new_scenarios():
    weights = {"severity": 40, "persistence": 15, "exposure": 10, "evidence_diversity": 15, "case_age": 10, "cross_domain_hazard": 10}
    config = SimpleNamespace(value={"case_priority_weights": weights}, version=6)

    result = configured_scenario_parameters(FakeDatabase(config), "water", {"seed": 721})

    assert result["case_priority_weights"] == weights
    assert result["case_priority_weights_version"] == 6


def test_scenario_enqueue_freezes_configuration_version(monkeypatch):
    weights = {"severity": 50, "extent_m2": 15, "daily_exposure": 15, "repeat_count": 10, "vulnerable_location": 10}
    config = SimpleNamespace(value={"road_priority_weights": weights}, version=8)

    class Query:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return None

    class Database(FakeDatabase):
        def query(self, model):
            assert model is Job
            return Query()

        def add(self, job):
            self.job = job

        def commit(self):
            pass

    db = Database(config)
    monkeypatch.setattr(api_main, "DEMO_MODE", True)
    monkeypatch.setattr(api_main, "require_staff", lambda _user: None)
    monkeypatch.setattr(api_main, "serialize_job", lambda job: job.parameters)
    result = api_main.enqueue(
        db,
        SimpleNamespace(id="admin-1", role="admin", domains=[], zones=[]),
        "scenario",
        {"domain": "roads", "scenario": "pothole", "parameters": {"seed": 721}},
        key="priority-snapshot",
        demo_session_id="opaque-session",
    )

    assert result["parameters"]["priority_weights"] == weights
    assert result["parameters"]["priority_weights_version"] == 8
    assert db.job.demo_session_id == "opaque-session"


def test_worker_preserves_the_priority_snapshot_on_a_later_config_change():
    frozen = {"severity": 50, "extent_m2": 15, "daily_exposure": 15, "repeat_count": 10, "vulnerable_location": 10}
    later = {"severity": 35, "extent_m2": 20, "daily_exposure": 20, "repeat_count": 15, "vulnerable_location": 10}
    config = SimpleNamespace(value={"road_priority_weights": later}, version=9)

    result = configured_scenario_parameters(
        FakeDatabase(config),
        "roads",
        {"priority_weights": frozen, "priority_weights_version": 8},
    )

    assert result["priority_weights"] == frozen
    assert result["priority_weights_version"] == 8
