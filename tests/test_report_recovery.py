import uuid
from services.api.database import SessionLocal
from services.api.models import Report, Case, Audit

def test_submission_lookup_recovers_same_receipt_and_does_not_publish_again(login):
    citizen=login('citizen')
    key=str(uuid.uuid4())
    lookup='/api/v1/reports/submissions/'+key
    assert citizen.get(lookup).json()=={'report':None}
    body={'domain':'water','zone_id':'river','title':'Synthetic report recovery','description':'Synthetic observation for lost report confirmation verification.','location':'Public test landmark','idempotency_key':key}
    response=citizen.post('/api/v1/reports',json=body)
    assert response.status_code==201,response.text
    original=response.json()
    assert citizen.get(lookup).json()['report']==original
    assert citizen.post('/api/v1/reports',json=body).json()==original
    with SessionLocal() as db:
        assert db.query(Report).filter_by(user_id='demo-citizen',idempotency_key=key).count()==1
        assert db.query(Case).filter_by(id=original['case_id']).count()==1
        assert db.query(Audit).filter_by(case_id=original['case_id'],action='reported').count()==1

def test_submission_lookup_is_owner_only_even_for_staff(login):
    citizen,operator=login('citizen'),login('operator')
    key=str(uuid.uuid4())
    response=citizen.post('/api/v1/reports',json={'domain':'water','zone_id':'river','title':'Private recovery check','description':'A synthetic private observation for ownership verification.','location':'Public test site','idempotency_key':key})
    assert response.status_code==201
    assert operator.get('/api/v1/reports/submissions/'+key).json()=={'report':None}
    citizen.post('/api/v1/auth/logout')
    assert citizen.get('/api/v1/reports/submissions/'+key).status_code==401

def test_invalid_submission_lookup_identifier_is_rejected(login):
    citizen=login('citizen')
    assert citizen.get('/api/v1/reports/submissions/short').status_code==422
    assert citizen.get('/api/v1/reports/submissions/'+'a'*101).status_code==422
