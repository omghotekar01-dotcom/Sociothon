import copy
import uuid
import pytest
from datetime import timedelta

from services.api.baselines import checksum, stamp
from services.api.database import SessionLocal
from services.api.models import BaselineVersion, Case, Job, Reading, User, Zone
from services.api.worker import execute_job


@pytest.fixture(autouse=True)
def operator_baseline_scope(server):
    # Registry tests elsewhere add zones. Explicitly grant this test operator
    # the all-zone scope required for cross-zone baseline evaluation.
    with SessionLocal() as db:
        user = db.get(User, 'demo-operator')
        previous = list(user.zones)
        user.zones = [zone.id for zone in db.query(Zone).all()]
        db.commit()
    yield
    with SessionLocal() as db:
        db.get(User, 'demo-operator').zones = previous
        db.commit()


def prepare(client, **overrides):
    registry = client.get('/api/v1/baselines/water').json()
    body = {'train_start': registry['suggested_start'], 'train_end': registry['suggested_end'], 'reason': 'Explicitly review a different historical window.', 'idempotency_key': str(uuid.uuid4()), **overrides}
    response = client.post('/api/v1/baselines/water/candidates', json=body)
    return response, body, registry


def run_job(ident):
    with SessionLocal() as db:
        job = db.get(Job, ident)
        job.status, job.attempts = 'running', 1
        db.commit()
    execute_job(ident)
    with SessionLocal() as db:
        job = db.get(Job, ident)
        assert job.status == 'succeeded', job.error
        return job.result


def test_evaluate_promote_rerun_and_rollback_preserve_cases(login):
    op, admin = login('operator'), login('admin')
    initial = op.get('/api/v1/analytics/water').json()
    before = [(c['id'], c['status'], c['version']) for c in op.get('/api/v1/cases').json()]
    response, body, registry = prepare(op)
    assert response.status_code == 202, response.text
    queued = response.json()
    assert op.post('/api/v1/baselines/water/candidates', json=body).json() == queued
    assert op.post('/api/v1/baselines/water/candidates', json={**body, 'reason': 'Different request using same key'}).status_code == 409
    result = run_job(queued['job_id'])
    assert result['status'] == 'evaluated', result
    assert result['evaluation']['intervals'] >= 72
    assert result['evaluation']['candidate']['mae'] >= 0
    assert result['evaluation']['previous']['rmse'] >= 0
    assert op.get('/api/v1/analytics/water').json() == initial
    assert [(c['id'], c['status'], c['version']) for c in op.get('/api/v1/cases').json()] == before
    activation = {'baseline_id': queued['baseline_id'], 'version': registry['version'], 'reason': 'Reviewed chronological residuals and excluded incidents.'}
    assert op.post('/api/v1/baselines/water/promote', json=activation).status_code == 403
    promoted = admin.post('/api/v1/baselines/water/promote', json=activation)
    assert promoted.status_code == 200, promoted.text
    try:
        assert op.get('/api/v1/analytics/water').json()['baseline_id'] == queued['baseline_id']
        assert [(c['id'], c['status'], c['version']) for c in op.get('/api/v1/cases').json()] == before
        analysis = op.post('/api/v1/jobs', json={'kind': 'analysis', 'parameters': {'domain': 'water'}}).json()
        output = run_job(analysis['id'])
        assert output['baseline_id'] == queued['baseline_id']
        assert output['details']['training_source'] == 'Immutable reviewed baseline snapshot'
        state = op.get('/api/v1/baselines/water').json()
        stale = admin.post('/api/v1/baselines/water/rollback', json={'baseline_id': registry['active_id'], 'version': registry['version'], 'reason': 'Stale rollback must fail atomically'})
        assert stale.status_code == 409
        assert op.get('/api/v1/baselines/water').json()['active_id'] == queued['baseline_id']
    finally:
        state = op.get('/api/v1/baselines/water').json()
        restored = admin.post('/api/v1/baselines/water/rollback', json={'baseline_id': registry['active_id'], 'version': state['version'], 'reason': 'Restore previous approved baseline after verification.'})
        assert restored.status_code == 200, restored.text
    assert op.get('/api/v1/analytics/water').json() == initial
    decisions = op.get('/api/v1/baselines/water').json()['decisions']
    assert {'baseline_candidate','baseline_promote','baseline_rollback'} <= {a['action'] for a in decisions}


def test_candidate_excludes_unresolved_periods_and_validates_scope(login):
    op = login('operator')
    response, _, registry = prepare(op, train_start='2026-09-01', train_end='2026-09-30')
    assert response.status_code == 422
    assert prepare(op, train_start=registry['suggested_end'])[0].status_code == 422
    for role in ('citizen', 'inspector'):
        assert login(role).get('/api/v1/baselines/water').status_code == 403
    with SessionLocal() as db:
        row = db.query(Reading).filter(Reading.domain == 'water', Reading.timestamp >= registry['suggested_start'].replace('+00:00','Z')).order_by(Reading.timestamp).first()
        case = Case(id=str(uuid.uuid4()), event_key=str(uuid.uuid4()), title='Unresolved baseline test', domain='water', zone_id=row.zone_id, asset_id=row.asset_id, severity='medium', summary='Exclude this unresolved historical interval', provenance='Derived', evidence={'start': row.timestamp, 'end': row.timestamp})
        db.add(case); db.commit(); case_id, reading_id = case.id, row.id
    try:
        response, _, _ = prepare(op)
        assert response.status_code == 202, response.text
        with SessionLocal() as db:
            candidate = db.get(BaselineVersion, response.json()['baseline_id'])
            assert reading_id not in {r['id'] for r in candidate.training}
            assert case_id in candidate.exclusions['case_ids']
            assert checksum(candidate.training) == candidate.checksum
        with SessionLocal() as db:
            user = db.get(User, 'demo-operator'); old = user.zones; user.zones = ['river']; db.commit()
        try:
            assert op.get('/api/v1/baselines/water').status_code == 403
            assert op.post('/api/v1/baselines/water/candidates', json={'train_start':registry['suggested_start'],'train_end':registry['suggested_end'],'reason':'No all-zone grant','idempotency_key':str(uuid.uuid4())}).status_code == 403
        finally:
            with SessionLocal() as db:
                db.get(User, 'demo-operator').zones = old; db.commit()
    finally:
        with SessionLocal() as db:
            db.get(Case, case_id).status = 'closed'; db.commit()


def test_promotion_rechecks_new_unresolved_evidence_and_artifact_integrity(login):
    admin = login('admin')
    response, _, state = prepare(admin)
    queued = response.json()
    assert run_job(queued['job_id'])['status'] == 'evaluated'
    body = {'baseline_id': queued['baseline_id'], 'version': state['version'], 'reason': 'Review the evaluated candidate for activation.'}
    assert admin.post('/api/v1/baselines/water/rollback', json=body).status_code == 409
    assert admin.post('/api/v1/baselines/electricity/promote', json=body).status_code == 404
    with SessionLocal() as db:
        candidate = db.get(BaselineVersion, queued['baseline_id']); row = candidate.training[0]
        case = Case(id=str(uuid.uuid4()), event_key=str(uuid.uuid4()), title='New historical evidence', domain='water', asset_id=row['asset_id'], zone_id=row['zone_id'], severity='medium', summary='New evidence invalidates training review', provenance='Derived', evidence={'start': row['timestamp'], 'end': row['timestamp']})
        db.add(case); db.commit(); ident = case.id
    try:
        assert admin.post('/api/v1/baselines/water/promote', json=body).status_code == 409
    finally:
        with SessionLocal() as db:
            db.get(Case, ident).status = 'closed'
            candidate = db.get(BaselineVersion, queued['baseline_id']); original = candidate.checksum; candidate.checksum = 'changed'
            db.commit()
    try:
        assert admin.post('/api/v1/baselines/water/promote', json=body).status_code == 409
    finally:
        with SessionLocal() as db:
            db.get(BaselineVersion, queued['baseline_id']).checksum = original; db.commit()
    assert admin.get('/api/v1/baselines/water').json()['active_id'] == state['active_id']


def test_frozen_training_cannot_learn_changed_observations():
    from services.analytics.pipeline import analyze_consumption, generate_consumption
    rows = [r for r in generate_consumption('water', days=28, anomalies=False)[0] if r['asset_id']=='water-river']
    cutoff = (stamp(rows[0]['timestamp']) + timedelta(days=14)).isoformat()
    training = copy.deepcopy(rows[:14*24])
    first = analyze_consumption(rows, 'water', train_end=cutoff, training_readings=training)
    changed = copy.deepcopy(rows)
    for row in changed[:14*24]:
        row['quantity'] *= 2
    second = analyze_consumption(changed, 'water', train_end=cutoff, training_readings=training)
    assert [r['expected'] for r in first['_rows']] == [r['expected'] for r in second['_rows']]
    refit = analyze_consumption(changed, 'water', train_end=cutoff, training_readings=changed[:14*24])
    assert refit['series'][0]['expected'] > second['series'][0]['expected'] * 1.9
