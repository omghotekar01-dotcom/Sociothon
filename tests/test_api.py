import io
import time
import uuid
from datetime import datetime, timedelta, timezone
from PIL import Image
import pytest
from sqlalchemy import func, or_
from services.api.database import SessionLocal, init_db
from services.api.models import Asset, Association, Audit, Case, Evidence, Job, Notification, Reading, User, Configuration, Session
from services.api.security import hash_password
from services.api.worker import claim_next, execute_job

DOMAINS = ["water", "electricity", "roads", "drainage", "waste", "streetlights", "general"]

def report(client, domain="water", key=None):
    body = {"domain": domain, "zone_id": "river", "title": f"Test {domain} observation", "description": "Synthetic test observation recorded from a safe location.", "location": "Public market entrance", "idempotency_key": key or str(uuid.uuid4())}
    response = client.post("/api/v1/reports", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body

def mutation(client, case, path, **body):
    response = client.post(f"/api/v1/cases/{case['id']}/{path}", json={**body, "version": case["version"]})
    assert response.status_code == 200, response.text
    return response.json()

@pytest.mark.parametrize("domain", DOMAINS)
def test_complete_human_reviewed_domain_workflow(login, domain):
    citizen, operator = login("citizen"), login("operator")
    if domain == "electricity":
        admin = login("admin")
        registry = admin.get("/api/v1/admin").json()
        inspector_record = next(user for user in registry["users"] if user["id"] == "demo-inspector")
        qualified = admin.patch("/api/v1/admin/users/demo-inspector", json={
            "role": inspector_record["role"],
            "domains": inspector_record["domains"],
            "zones": inspector_record["zones"],
            "active": inspector_record["active"],
            "electrical_qualified": True,
            "reason": "Record the synthetic test inspector qualification",
        })
        assert qualified.status_code == 200, qualified.text
    inspector = login("inspector")
    submitted, _ = report(citizen, domain)
    ident = submitted["case_id"]
    assert inspector.get(f"/api/v1/cases/{ident}").status_code == 403
    case = operator.get(f"/api/v1/cases/{ident}").json()
    assert operator.post(f"/api/v1/cases/{ident}/transition", json={"status": "resolved", "reason": "Invalid jump", "version": case["version"]}).status_code == 409
    case = mutation(operator, case, "transition", status="investigating", reason="Review submitted observation")
    case = mutation(operator, case, "assign", inspector_id="demo-inspector", reason="Assign authorized field inspection")
    electrical_confirmation = {"qualified_electricity_assessment": True} if domain == "electricity" else {}
    case = mutation(inspector, case, "inspection", notes="Synthetic inspector confirms the observed condition.", checklist={"observed": True, **electrical_confirmation})
    case = mutation(inspector, case, "intervention", notes="Synthetic intervention recorded with responsible crew.", checklist={"documented": True, **electrical_confirmation})
    case = mutation(inspector, case, "transition", status="monitoring", reason="Collect follow-up evidence")
    assert operator.post(f"/api/v1/cases/{ident}/transition", json={"status": "resolved", "reason": "No followup yet", "version": case["version"]}).status_code == 409
    case = mutation(inspector, case, "inspection", kind="follow_up", notes="Synthetic follow-up inspection records restored condition.", checklist={"follow_up": True, **electrical_confirmation})
    assert inspector.post(f"/api/v1/cases/{ident}/transition", json={"status": "resolved", "reason": "Inspector cannot close", "version": case["version"]}).status_code == 403
    case = mutation(operator, case, "transition", status="resolved", reason="Human-reviewed follow-up evidence supports closure")
    assert len(case["audits"]) >= 8
    assert citizen.get(f"/api/v1/reports/{submitted['id']}").json()["status"] == "resolved"
    case = mutation(operator, case, "transition", status="investigating", reason="Reopen after a new observation")
    assert case["status"] == "investigating"

def test_report_idempotency_ownership_and_registration(login, server):
    citizen = login("citizen")
    one, body = report(citizen)
    assert citizen.post("/api/v1/reports", json=body).json()["id"] == one["id"]
    assert citizen.post("/api/v1/reports", json={**body, "title": "Conflicting content"}).status_code == 409
    email = uuid.uuid4().hex + "@example.test"
    attempt = {"name": "Second citizen", "email": email, "password": "StrongPassword2026", "role": "admin"}
    assert server.post("/api/v1/auth/register", json=attempt).status_code == 422
    attempt.pop("role")
    response = server.post("/api/v1/auth/register", json=attempt)
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "citizen"
    assert server.get("/api/v1/reports/" + one["id"]).status_code == 403
    assert citizen.get("/api/v1/admin").status_code == 403
    assert citizen.get("/api/v1/analytics/water").status_code == 403


def test_high_risk_electrical_report_enters_review_before_telemetry(login):
    citizen, operator = login("citizen"), login("operator")
    body = {
        "domain": "electricity", "zone_id": "river", "title": "Electrical hazard report",
        "description": "A resident reports an exposed electrical hazard at the public market.",
        "location": "Public market entrance", "idempotency_key": str(uuid.uuid4()),
        "incident_type": "electrical_hazard",
    }

    submitted = citizen.post("/api/v1/reports", json=body)
    assert submitted.status_code == 201, submitted.text
    case = operator.get("/api/v1/cases/" + submitted.json()["case_id"]).json()

    assert case["status"] == "needs_review"
    assert case["severity"] == "high"
    assert case["priority_review"]["urgency"]["review_required"] is True
    assert case["priority_review"]["urgency"]["score"] == 75
    assert case["priority_review"]["components"]["persistence"]["status"] == "missing"

def test_csrf_concurrency_and_revocation(login):
    client = login("operator")
    case = client.get("/api/v1/cases").json()[0]
    response = client.post(f"/api/v1/cases/{case['id']}/transition", headers={"X-CSRF-Token": "wrong"}, json={"status": "closed", "reason": "test reason", "version": case["version"]})
    assert response.status_code == 403
    assert client.patch("/api/v1/settings", headers={"Origin": "https://untrusted.example"}, json={"language": "mr"}).status_code == 403
    submitted, _ = report(client)
    case = client.get("/api/v1/cases/" + submitted["case_id"]).json()
    mutation(client, case, "transition", status="investigating", reason="First reviewer update")
    assert client.post(f"/api/v1/cases/{case['id']}/transition", json={"status": "investigating", "reason": "Stale second reviewer", "version": case["version"]}).status_code == 409
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401

def test_restricted_operator_does_not_receive_other_domain_or_zone_analytics(login):
    admin = login("admin")
    with SessionLocal() as db:
        ident = uuid.uuid4().hex
        db.add(User(id=ident, name="Limited", email=ident+"@example.test", password_hash=hash_password("ScopePassword2026"), role="operator", domains=["electricity"], zones=["river"]))
        db.commit()
    response = admin.post("/api/v1/auth/login", json={"email": ident+"@example.test", "password": "ScopePassword2026"})
    admin.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    result = admin.get("/api/v1/bootstrap").json()
    assert result["series"] == []
    assert all(c["domain"] == "electricity" and c["zone_id"] == "river" for c in result["cases"])
    output = admin.get("/api/v1/analytics/electricity").json()
    assert "Restricted" in output["forecast"]["status"]
    assert all(row["zone_id"] == "river" for row in output["series"])
    assert admin.post("/api/v1/scenarios", json={"domain":"electricity","scenario":"normal"}).status_code == 403

def test_csv_preview_commit_rollback_duplicates(login):
    op = login("operator")
    header = "id,asset_id,zone_id,timestamp,interval_minutes,quantity,unit,source,quality_flag\n"
    row = "upload-a,water-river,river,2026-10-15T00:00:00Z,60,1.25,m3,Measured,valid\n"
    bad = "upload-b,water-river,river,2026-10-15T01:00:00,60,-3,L,Measured,valid\n"
    preview = op.post("/api/v1/uploads/preview", files={"file": ("readings.csv", (header+row+bad).encode(), "text/csv")}).json()
    assert (preview["accepted"], preview["rejected"]) == (1, 1)
    assert op.post(f"/api/v1/uploads/{preview['id']}/commit").status_code == 422
    preview = op.post("/api/v1/uploads/preview", files={"file": ("readings.csv", (header+row).encode(), "text/csv")}).json()
    url = f"/api/v1/uploads/{preview['id']}/commit"
    assert op.post(url).status_code == 200
    assert op.post(url).json()["idempotent"]
    duplicate = op.post("/api/v1/uploads/preview", files={"file": ("readings.csv", (header+row).encode(), "text/csv")}).json()
    assert duplicate["duplicates"] == 1
    with SessionLocal() as db:
        value = db.get(Reading, "upload-a")
        assert value.quantity == 1250 and value.original["quantity"] == "1.25"

def test_private_photograph_validation_idempotency_and_permissions(login):
    citizen, op = login("citizen"), login("operator")
    submitted, _ = report(citizen)
    route = f"/api/v1/cases/{submitted['case_id']}/evidence"
    assert citizen.post(route, files={"file": ("image.svg", b"<svg/>", "image/svg+xml")}).status_code == 422
    assert citizen.post(route, files={"file": ("image.png", b"not a png", "image/png")}).status_code == 422
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image, "PNG")
    upload = lambda: citizen.post(route, files={"file": ("image.png", image.getvalue(), "image/png")}, data={"notes":"Synthetic photograph"})
    first, second = upload(), upload()
    assert first.status_code == 200 and second.json()["id"] == first.json()["id"]
    assert citizen.get(first.json()["url"]).status_code == 200
    assert login("inspector").get(first.json()["url"]).status_code == 403
    assert op.get(first.json()["url"]).headers["content-type"].startswith("image/jpeg")

def test_durable_job_recovery_deduplication_and_safe_reset(login):
    op = login("operator")
    key = uuid.uuid4().hex
    body = {"domain":"roads","scenario":"pothole","idempotency_key":key}
    job = op.post("/api/v1/scenarios", json=body).json()
    assert op.post("/api/v1/scenarios", json=body).json()["id"] == job["id"]
    with SessionLocal() as db:
        stored = db.get(Job, job["id"])
        stored.status, stored.lease_until, stored.attempts = "running", time.time()-1, 1
        db.commit()
        assert claim_next(db) == job["id"]
    execute_job(job["id"])
    result = op.get("/api/v1/jobs/"+job["id"]).json()
    assert result["status"] == "succeeded", result
    with SessionLocal() as db:
        before = db.query(Reading).count()
    assert op.post(f"/api/v1/scenarios/{job['id']}/reset").status_code == 200
    with SessionLocal() as db:
        assert db.query(Reading).count() == before
    assert login("citizen").get("/api/v1/jobs/"+job["id"]).status_code == 404

def test_seed_and_migration_repeatability(server):
    from services.api.seed import seed_database
    with SessionLocal() as db:
        before = (db.query(Reading).count(), db.query(Case).count())
        init_db()
        seed_database(db)
        assert before == (db.query(Reading).count(), db.query(Case).count())
        assert db.query(Reading).count() >= 8064


def test_admin_registry_authorization_validation_and_duplicate_safety(login):
    admin, citizen = login('admin'), login('citizen')
    zone = {'id': 'registry-' + uuid.uuid4().hex[:8], 'name': 'Test service zone', 'population': 2500, 'reason': 'Register synthetic test zone'}
    assert citizen.post('/api/v1/admin/zones', json=zone).status_code == 403
    created = admin.post('/api/v1/admin/zones', json=zone)
    assert created.status_code == 201, created.text
    assert created.json()['population'] == 2500
    assert admin.post('/api/v1/admin/zones', json=zone).status_code == 409
    asset = {'id': 'test-' + uuid.uuid4().hex[:8], 'name': 'Test registered asset', 'domain': 'water', 'zone_id': zone['id'], 'kind': 'meter', 'x': 25, 'y': 75, 'reason': 'Register test observation source'}
    assert admin.post('/api/v1/admin/assets', json={**asset, 'zone_id': 'missing-zone'}).status_code == 422
    assert admin.post('/api/v1/admin/assets', json=asset).status_code == 201
    assert admin.post('/api/v1/admin/assets', json=asset).status_code == 409


def test_report_corroboration_preserves_history_and_counts_distinct_accounts(login):
    citizen, op = login('citizen'), login('operator')
    first, _ = report(citizen)
    second, _ = report(citizen)
    other, _ = report(citizen, 'electricity')
    url = '/api/v1/reports/' + second['id'] + '/link'
    body = {'case_id': first['case_id'], 'reason': 'Same observed location and issue'}
    assert citizen.post(url, json=body).status_code == 403
    assert op.post(url, json={**body, 'case_id': other['case_id']}).status_code == 422
    result = op.post(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['corroboration']['reports'] == 2
    assert result.json()['corroboration']['unique_reporters'] == 1
    assert result.json()['corroboration']['same_account_repeat_groups'] == 1
    assert result.json()['corroboration']['same_account_additional_reports'] == 1
    assert op.post(url, json=body).json()['corroboration']['reports'] == 2
    assert op.get('/api/v1/cases/' + second['case_id']).status_code == 200
    assert citizen.get('/api/v1/reports/' + second['id']).json()['case_id'] == first['case_id']


def test_cross_domain_suggestions_use_scoped_coordinates_and_are_audited_when_reviewed(login):
    operator = login('operator')
    scope_user_id = operator.get('/api/v1/bootstrap').json()['user']['id']
    suffix = uuid.uuid4().hex
    asset_ids = ["water-geo-" + suffix, "power-geo-" + suffix]
    case_ids = ["water-case-" + suffix, "power-case-" + suffix]
    created = datetime.now(timezone.utc) - timedelta(hours=3)
    original_domains = None
    try:
        with SessionLocal() as db:
            db.add_all([
                Asset(id=asset_ids[0], name="Synthetic water asset", domain="water", zone_id="river", kind="meter", properties={"lat": 18.52, "lon": 73.85}),
                Asset(id=asset_ids[1], name="Synthetic electricity asset", domain="electricity", zone_id="river", kind="feeder", properties={"lat": 18.5201, "lon": 73.8501}),
                Case(id=case_ids[0], event_key=case_ids[0], title="Water observation", domain="water", zone_id="river", asset_id=asset_ids[0], severity="high", status="needs_review", summary="Test signal", provenance="Derived", priority=75, evidence={}, created_at=created.isoformat(), updated_at=created.isoformat()),
                Case(id=case_ids[1], event_key=case_ids[1], title="Electrical observation", domain="electricity", zone_id="river", asset_id=asset_ids[1], severity="high", status="needs_review", summary="Test signal", provenance="Derived", priority=75, evidence={}, created_at=(created + timedelta(hours=1)).isoformat(), updated_at=(created + timedelta(hours=1)).isoformat()),
            ])
            db.commit()

        candidates = operator.get('/api/v1/associations').json()
        suggestion = next(item for item in candidates if {item.get('source_id'), item.get('target_id')} == set(case_ids))
        assert suggestion['status'] == 'suggested'
        assert suggestion['basis']['relationship'] == 'shared_location'
        assert suggestion['basis']['distance_m'] < 500
        assert suggestion['basis']['time_offset_hours'] == 1

        reviewed = operator.patch('/api/v1/associations/' + suggestion['id'], json={
            'status': 'accepted', 'expected_status': 'suggested', 'reason': 'Review nearby cross-domain evidence',
        })
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()['status'] == 'accepted'
        assert reviewed.json()['basis']['relationship'] == 'shared_location'
        assert operator.patch('/api/v1/associations/' + suggestion['id'], json={
            'status': 'rejected', 'expected_status': 'suggested', 'reason': 'Stale browser decision must fail',
        }).status_code == 409
        with SessionLocal() as db:
            assert db.query(Audit).filter(Audit.case_id.in_(case_ids), Audit.action == 'association_review').count() == 2
            original_notices = db.query(Notification).filter(Notification.case_id.in_(case_ids)).count()
            assert original_notices > 0
        assert operator.patch('/api/v1/associations/' + suggestion['id'], json={
            'status': 'unlinked', 'expected_status': 'accepted', 'reason': 'Follow-up shows independent events',
        }).status_code == 200
        refreshed = operator.get('/api/v1/associations').json()
        assert [item['status'] for item in refreshed if {item['source_id'], item['target_id']} == set(case_ids)] == ['unlinked']
        with SessionLocal() as db:
            assert db.query(Case).filter(Case.id.in_(case_ids)).count() == 2
            assert db.query(Notification).filter(Notification.case_id.in_(case_ids)).count() == original_notices

        # A staff member who can see only water cases must not receive a pair
        # suggestion requiring the hidden electricity case.
        with SessionLocal() as db:
            scoped_user = db.get(User, scope_user_id)
            original_domains = list(scoped_user.domains)
            scoped_user.domains = ['water']
            db.commit()
        assert all({item.get('source', item.get('source_id')), item.get('target', item.get('target_id'))} != set(case_ids)
                   for item in operator.get('/api/v1/associations').json())
        assert login('citizen').get('/api/v1/associations').status_code == 403
    finally:
        with SessionLocal() as db:
            if original_domains is not None:
                scoped_user = db.get(User, scope_user_id)
                scoped_user.domains = original_domains
            db.query(Notification).filter(Notification.case_id.in_(case_ids)).delete(synchronize_session=False)
            db.query(Audit).filter(Audit.case_id.in_(case_ids)).delete(synchronize_session=False)
            db.query(Association).filter(or_(Association.source_id.in_(case_ids), Association.target_id.in_(case_ids))).delete(synchronize_session=False)
            db.query(Case).filter(Case.id.in_(case_ids)).delete(synchronize_session=False)
            db.query(Asset).filter(Asset.id.in_(asset_ids)).delete(synchronize_session=False)
            db.commit()


def test_impact_requires_staff_and_exposes_limits(login):
    assert login('citizen').get('/api/v1/impact').status_code == 403
    response = login('operator').get('/api/v1/impact')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['provenance'] == 'Derived' and result['limitations']
    assert result['response_sample_count'] >= 0


def test_supporting_inspector_access_evidence_audit_and_removal(login):
    op, support = login('operator'), login('support')
    submitted, _ = report(op)
    ident = submitted['case_id']
    assert support.get('/api/v1/cases/'+ident).status_code == 403
    case = op.get('/api/v1/cases/'+ident).json()
    case = mutation(op,case,'assign',inspector_id='demo-inspector',reason='Lead field inspector assigned')
    case = mutation(op,case,'supporting-inspectors',inspector_ids=['demo-support'],reason='Supporting inspection needed')
    assert case['assigned_to'] == 'demo-inspector'
    assert case['secondary_assignees'] == ['demo-support']
    assert case['assignment_team']['supporting'][0]['name'].startswith('Kiran')
    assert ident in {c['id'] for c in support.get('/api/v1/bootstrap').json()['cases']}
    assert ident in {n['case_id'] for n in support.get('/api/v1/notifications').json()}
    assert support.post('/api/v1/cases/'+ident+'/supporting-inspectors',json={'inspector_ids':[],'reason':'Cannot self-modify access','version':case['version']}).status_code == 403
    case = mutation(support,case,'inspection',notes='Supporting inspector records site observations.',checklist={'observed':True})
    case = mutation(support,case,'intervention',notes='Supporting inspector records authorized field work.',checklist={'documented':True})
    case = mutation(support,case,'transition',status='monitoring',reason='Record follow-up monitoring')
    case = mutation(support,case,'inspection',kind='follow_up',notes='Follow-up field evidence from supporting inspector.',checklist={'observed':True})
    assert support.post('/api/v1/cases/'+ident+'/transition',json={'status':'resolved','reason':'Inspector cannot approve closure','version':case['version']}).status_code == 403
    evidence_count=len(case['evidence_records'])
    case = mutation(op,case,'supporting-inspectors',inspector_ids=[],reason='Supporting task finished; remove access')
    assert support.get('/api/v1/cases/'+ident).status_code == 403
    assert ident not in {c['id'] for c in support.get('/api/v1/cases').json()}
    assert ident not in {n['case_id'] for n in support.get('/api/v1/notifications').json()}
    assert len(case['evidence_records']) == evidence_count
    audit = [a for a in case['audits'] if a['action']=='supporting_assignment'][-1]
    assert audit['before']['secondary_assignees']==['demo-support'] and audit['after']['secondary_assignees']==[]


def test_supporting_assignment_validation_and_stale_rollback(login):
    op = login('operator')
    submitted,_=report(op)
    case=op.get('/api/v1/cases/'+submitted['case_id']).json()
    url='/api/v1/cases/'+case['id']+'/supporting-inspectors'
    body={'inspector_ids':['demo-support'],'reason':'Supporting field inspection','version':case['version']}
    assert op.post(url,json=body).status_code==409
    case=mutation(op,case,'assign',inspector_id='demo-inspector',reason='Lead assigned before supporting team')
    for ids in [['demo-citizen'],['demo-admin'],['missing-user'],['demo-inspector'],['demo-support','demo-support']]:
        assert op.post(url,json={**body,'version':case['version'],'inspector_ids':ids}).status_code==422
    with SessionLocal() as db:
        restricted=User(id=uuid.uuid4().hex,name='Out of scope inspector',email=uuid.uuid4().hex+'@example.test',password_hash=hash_password('TestPassword2026'),role='inspector',domains=['electricity'],zones=['river'])
        db.add(restricted);db.commit();restricted_id=restricted.id
    assert op.post(url,json={**body,'version':case['version'],'inspector_ids':[restricted_id]}).status_code==422
    stale=case['version']
    case=mutation(op,case,'supporting-inspectors',inspector_ids=['demo-support'],reason='Add authorized supporting inspector')
    assert op.post(url,json={**body,'version':stale,'inspector_ids':[]}).status_code==409
    current=op.get('/api/v1/cases/'+case['id']).json()
    assert current['secondary_assignees']==['demo-support'] and current['version']==case['version']
    promoted=mutation(op,current,'assign',inspector_id='demo-support',reason='Promote supporting inspector to lead')
    assert promoted['assigned_to']=='demo-support' and promoted['secondary_assignees']==[]
    assert login('inspector').get('/api/v1/cases/'+case['id']).status_code==403


def test_supporting_assignment_does_not_override_revoked_scope(login):
    op,support=login('operator'),login('support')
    submitted,_=report(op)
    case=op.get('/api/v1/cases/'+submitted['case_id']).json()
    case=mutation(op,case,'assign',inspector_id='demo-inspector',reason='Choose lead inspector')
    case=mutation(op,case,'supporting-inspectors',inspector_ids=['demo-support'],reason='Choose supporting inspector')
    with SessionLocal() as db:
        user=db.get(User,'demo-support');previous=user.domains;user.domains=[];db.commit()
    try:
        assert support.get('/api/v1/cases/'+case['id']).status_code==403
        assert case['id'] not in {c['id'] for c in support.get('/api/v1/cases').json()}
    finally:
        with SessionLocal() as db:
            db.get(User,'demo-support').domains=previous;db.commit()
