from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api import main
from services.api.models import Asset, Case, Session, User, Zone


def test_electricity_report_preserves_unverified_type_department_and_asset_mapping():
    asset = SimpleNamespace(id="electricity-market", domain="electricity", zone_id="river")

    class Database:
        def get(self, model, ident):
            return asset if model is Asset and ident == asset.id else None

    body = main.ReportBody(domain="electricity", zone_id="river", title="Power interruption", description="Service appears interrupted at the public market.", location="Public market", idempotency_key="report-123456", incident_type="power_outage", affected_asset_id=asset.id)
    result = main.reported_incident_metadata(Database(), body)

    assert result["type"] == "power_outage"
    assert result["affected_asset_id"] == asset.id
    assert result["classification"] == "citizen_report_unverified"
    assert result["requested_department"] == "electricity"
    assert result["assignment_status"] == "awaiting_authorized_staff_assignment"
    assert "Do not touch" in result["safety_guidance"]


@pytest.mark.parametrize("wrong_asset", [
    SimpleNamespace(id="water-river", domain="water", zone_id="river"),
    SimpleNamespace(id="electricity-other", domain="electricity", zone_id="market"),
    None,
])
def test_electricity_report_rejects_asset_outside_its_domain_or_zone(wrong_asset):
    class Database:
        def get(self, _model, ident):
            return wrong_asset if wrong_asset and ident == wrong_asset.id else None

    asset_id = wrong_asset.id if wrong_asset else "some-asset"
    body = main.ReportBody(domain="electricity", zone_id="river", title="Electrical issue", description="A reported electrical condition needs staff review.", location="Public market", idempotency_key="report-123456", incident_type="electrical_hazard", affected_asset_id=asset_id)
    with pytest.raises(HTTPException) as raised:
        main.reported_incident_metadata(Database(), body)
    assert raised.value.status_code == 422


def test_non_electricity_reports_cannot_claim_electrical_incident_type():
    class Database:
        def get(self, *_args):
            return None

    body = main.ReportBody(domain="water", zone_id="river", title="Water issue", description="A reported water condition needs staff review.", location="Public market", idempotency_key="report-123456", incident_type="power_outage")
    with pytest.raises(HTTPException, match="only valid for electricity"):
        main.reported_incident_metadata(Database(), body)


def test_report_submission_persists_the_structured_incident_without_a_schema_change(monkeypatch):
    from services.api.models import Configuration, Report, uid

    zone = SimpleNamespace(id="river")
    config = SimpleNamespace(value={"review_hours": 72})
    saved = []
    monkeypatch.setattr(main, "rate_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "notify_case", lambda *_args, **_kwargs: None)

    class Query:
        def filter_by(self, **_filters):
            return self

        def first(self):
            return None

    class Database:
        def get(self, model, ident):
            if model is Zone and ident == "river":
                return zone
            if model is Configuration and ident == "platform":
                return config
            if model is Case:
                return next((row for row in saved if isinstance(row, Case) and row.id == ident), None)
            return None

        def query(self, _model):
            return Query()

        def add(self, row):
            saved.append(row)

        def flush(self):
            for row in saved:
                if isinstance(row, Case):
                    row.status = "needs_review"
                    row.updated_at = main.now()
                if isinstance(row, Report):
                    row.id = row.id or uid()
                    row.created_at = row.created_at or main.now()

        def commit(self):
            pass

    body = main.ReportBody(domain="electricity", zone_id="river", title="Reported outage", description="A resident reports an interruption near the public market.", location="Public market", idempotency_key="report-123456", incident_type="power_outage", affected_asset_id="")
    result = main.create_report(body, SimpleNamespace(id="citizen-1", role="citizen", domains=[], zones=[]), Database())

    assert result["reported_incident"]["type"] == "power_outage"
    assert result["reported_incident"]["classification"] == "citizen_report_unverified"
    assert result["reported_incident"]["affected_asset_id"] is None


def test_electricity_assignment_requires_administrator_recorded_qualification(monkeypatch):
    case = SimpleNamespace(id="case-1", domain="electricity", zone_id="river", status="needs_review", version=1, assigned_to=None, secondary_assignees=[], support_assignments=[])
    inspector = SimpleNamespace(id="inspector-1", role="inspector", active=True, domains=["electricity"], zones=["river"], settings={"electrical_qualified": False})
    monkeypatch.setattr(main, "case_access", lambda *_args: case)

    class Database:
        def get(self, model, ident):
            return inspector if model is User and ident == inspector.id else None

    with pytest.raises(HTTPException, match="qualification was recorded") as raised:
        main.assign(case.id, main.AssignmentBody(inspector_id=inspector.id, reason="Assign authorized electrical inspection", version=1), SimpleNamespace(role="admin"), Database())
    assert raised.value.status_code == 422


@pytest.mark.parametrize(("qualified", "checklist", "status"), [(False, {"qualified_electricity_assessment": True}, 403), (True, {}, 422)])
def test_electricity_inspection_requires_qualified_inspector_and_case_confirmation(monkeypatch, qualified, checklist, status):
    case = SimpleNamespace(id="case-1", domain="electricity", zone_id="river", status="assigned", version=1)
    inspector = SimpleNamespace(id="inspector-1", role="inspector", settings={"electrical_qualified": qualified})
    monkeypatch.setattr(main, "case_access", lambda *_args: case)

    class Query:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return None

    class Database:
        def query(self, _model):
            return Query()

    body = main.InspectionBody(notes="The site was observed from a safe area and recorded for review.", version=1, checklist=checklist, idempotency_key="inspect-123456")
    with pytest.raises(HTTPException) as raised:
        main.inspect_case(case.id, body, inspector, Database())
    assert raised.value.status_code == status


def test_admin_can_record_qualification_only_for_electricity_inspectors(monkeypatch):
    target = SimpleNamespace(id="inspector-1", role="inspector", domains=["electricity"], zones=["river"], active=True, settings={}, name="Inspector", email="i@example.test")
    admin = SimpleNamespace(id="admin-1", role="admin")
    monkeypatch.setattr(main, "audit", lambda *_args, **_kwargs: None)

    class Query:
        def filter_by(self, **_kwargs):
            return self

        def all(self):
            return [SimpleNamespace(id="river")]

        def delete(self):
            return 0

    class Database:
        def get(self, model, ident):
            return target if model is User and ident == target.id else None

        def query(self, _model):
            return Query()

        def commit(self):
            pass

    body = main.UserUpdate(role="inspector", domains=["electricity"], zones=["river"], electrical_qualified=True, reason="Credentials checked by the organization")
    result = main.update_user(target.id, body, admin, Database())
    assert result["settings"]["electrical_qualified"] is True

    invalid = main.UserUpdate(role="operator", domains=["electricity"], zones=["river"], electrical_qualified=True, reason="Invalid role assignment")
    with pytest.raises(HTTPException) as raised:
        main.update_user(target.id, invalid, admin, Database())
    assert raised.value.status_code == 422
