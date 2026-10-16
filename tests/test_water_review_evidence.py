import copy
import uuid
from datetime import datetime, timedelta

from services.api.database import SessionLocal
from services.api.models import Evidence, Reading, User


def fixture(login, domain="water", zone="river"):
    citizen, operator = login("citizen"), login("operator")
    report = citizen.post('/api/v1/reports', json={"domain":domain,"zone_id":zone,"title":"Synthetic saved water review", "description":"Synthetic review evidence verification, not a real incident.","location":"Synthetic test site","idempotency_key":str(uuid.uuid4())}).json()
    case = operator.get('/api/v1/cases/'+report['case_id']).json()
    config = operator.get('/api/v1/water/zones/river/operations').json()
    end = datetime.fromisoformat(config['latest_end'])
    inputs = {"start":(end-timedelta(days=1)).isoformat(),"end":end.isoformat(),"configuration_version":config['configuration']['version']}
    review = operator.post('/api/v1/water/zones/river/review', json=inputs)
    assert review.status_code == 200, review.text
    snapshot = review.json()
    body = {"review":inputs,"snapshot_hash":snapshot['snapshot_hash'],"case_version":case['version'],"reason":"Synthetic water context reviewed by the operator.","idempotency_key":str(uuid.uuid4())}
    path = '/api/v1/water/zones/river/cases/'+case['id']+'/reviews'
    return operator, citizen, case, snapshot, body, path


def test_water_snapshot_persists_exact_sources_without_field_evidence_or_decision(login):
    operator, citizen, before, snapshot, body, path = fixture(login)
    assert operator.post(path,json={**body,'reason':'     '}).status_code == 422
    attached = operator.post(path,json=body)
    assert attached.status_code == 200, attached.text
    assert attached.json()['duplicate'] is False
    after = operator.get('/api/v1/cases/'+before['id']).json()
    record = next(e for e in after['evidence_records'] if e['id']==attached.json()['evidence_id'])
    assert record['kind']=='water_review' and record['observations']['water_review']==snapshot
    assert after['status']==before['status'] and after['version']==before['version']+1
    assert after['priority_review']['evidence_quality']==before['priority_review']['evidence_quality']
    assert len([a for a in after['audits'] if a['action']=='water_review_attached'])==1
    assert citizen.get('/api/v1/cases/'+before['id']).status_code==403
    assert snapshot['balance']['unaccounted_l'] is None
    assert snapshot['source_observations'] and len(snapshot['snapshot_hash'])==64


def test_retry_returns_original_evidence_even_after_underlying_configuration_changes(login):
    operator, _, case, snapshot, body, path = fixture(login)
    first = operator.post(path,json=body).json()
    admin=login('admin'); config_path='/api/v1/water/zones/river/operations'
    config=admin.get(config_path).json()['configuration']
    changed=admin.put(config_path,json={**config,'outside_rate_lph':config['outside_rate_lph']+1,'reason':'Change configuration after saving review'}).json()
    try:
        repeat=operator.post(path,json=body)
        assert repeat.status_code==200 and repeat.json()['duplicate'] is True
        assert repeat.json()['evidence_id']==first['evidence_id']
        altered={**body,'reason':'Different reason must not replace original evidence'}
        assert operator.post(path,json=altered).status_code==409
        evidence=operator.get('/api/v1/cases/'+case['id']).json()['evidence_records']
        assert len(evidence)==1 and evidence[0]['observations']['water_review']==snapshot
    finally:
        assert admin.put(config_path,json={**config,'version':changed['version'],'reason':'Restore prior synthetic configuration'}).status_code==200


def test_changed_source_reading_or_case_version_rejects_attachment(login):
    operator, _, case, snapshot, body, path = fixture(login)
    assert operator.post(path,json={**body,'case_version':case['version']+1}).status_code==409
    reading_id=snapshot['source_observations'][0]['id']
    with SessionLocal() as db:
        row=db.get(Reading,reading_id); old=row.quantity; row.quantity=(old or 0)+1; db.commit()
    try:
        rejected=operator.post(path,json=body)
        assert rejected.status_code==409 and 'observations' in rejected.json()['detail']
        assert not operator.get('/api/v1/cases/'+case['id']).json()['evidence_records']
    finally:
        with SessionLocal() as db:
            db.get(Reading,reading_id).quantity=old; db.commit()


def test_attachment_rejects_wrong_domain_zone_and_untrusted_browser_snapshot(login):
    for domain,zone in [('roads','river'),('water','hill')]:
        operator, _, _, _, body, path = fixture(login,domain,zone)
        assert operator.post(path,json=body).status_code==422
    operator, citizen, case, snapshot, body, path = fixture(login)
    assert citizen.post(path,json=body).status_code==403
    assert login('inspector').post(path,json=body).status_code==403
    assert operator.post(path,json={**body,'snapshot':snapshot}).status_code==422
    assert operator.post(path,json={**body,'snapshot_hash':'0'*64}).status_code==409
    with SessionLocal() as db:
        user=db.get(User,'demo-operator'); old=copy.deepcopy(user.zones); user.zones=['hill']; db.commit()
    try:
        assert operator.post(path,json=body).status_code==404
    finally:
        with SessionLocal() as db:
            db.get(User,'demo-operator').zones=old; db.commit()


def test_closed_case_requires_explicit_reopening(login):
    operator, _, case, _, body, path = fixture(login)
    closed=operator.post('/api/v1/cases/'+case['id']+'/transition',json={'version':case['version'],'status':'closed','reason':'Synthetic review dismissed this report'}).json()
    assert operator.post(path,json={**body,'case_version':closed['version']}).status_code==409
    with SessionLocal() as db:
        assert db.query(Evidence).filter_by(case_id=case['id']).count()==0
