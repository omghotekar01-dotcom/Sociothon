import uuid
from services.api.database import SessionLocal
from services.api.models import Evidence, Audit, User


def assigned_case(login):
    operator, inspector = login('operator'), login('inspector')
    report = operator.post('/api/v1/reports', json={'domain':'water','zone_id':'river','title':'Synthetic field reconnect test','description':'Synthetic observation for reconnect verification.','location':'Public test location','idempotency_key':str(uuid.uuid4())}).json()
    case = operator.get('/api/v1/cases/'+report['case_id']).json()
    case = operator.post('/api/v1/cases/'+case['id']+'/assign', json={'inspector_id':'demo-inspector','reason':'Assign synthetic field verification','version':case['version']}).json()
    return operator, inspector, case


def test_lost_acknowledgement_retry_does_not_duplicate_inspection_or_audit(login):
    operator, inspector, case = assigned_case(login)
    body={'notes':'Synthetic offline observation, safely recorded.','checklist':{'observed':True},'version':case['version'],'idempotency_key':str(uuid.uuid4())}
    url='/api/v1/cases/'+case['id']+'/inspection'
    first=inspector.post(url,json=body)
    assert first.status_code==200,first.text
    again=inspector.post(url,json=body)
    assert again.status_code==200 and again.json()['version']==first.json()['version']
    with SessionLocal() as db:
        assert db.query(Evidence).filter_by(case_id=case['id'],idempotency_key=body['idempotency_key']).count()==1
        assert db.query(Audit).filter_by(case_id=case['id'],action='inspection').count()==1
    assert inspector.post(url,json={**body,'notes':'Different observation with the same submission ID.'}).status_code==409
    assert inspector.post(url,json={**body,'checklist':{'observed':False}}).status_code==409
    assert operator.post(url,json=body).status_code==403


def test_intervention_retry_succeeds_after_state_change_and_revocation_is_enforced(login):
    operator, inspector, case = assigned_case(login)
    body={'notes':'Synthetic intervention and responsible crew documented.','checklist':{'observation':True,'action':True,'follow_up':True},'version':case['version'],'idempotency_key':str(uuid.uuid4())}
    url='/api/v1/cases/'+case['id']+'/intervention'
    first=inspector.post(url,json=body)
    assert first.status_code==200 and first.json()['status']=='intervention'
    assert inspector.post(url,json=body).json()['version']==first.json()['version']
    with SessionLocal() as db:
        user=db.get(User,'demo-inspector');previous=list(user.zones);user.zones=[];db.commit()
    try:
        assert inspector.post(url,json=body).status_code==403
    finally:
        with SessionLocal() as db:
            db.get(User,'demo-inspector').zones=previous;db.commit()


def test_stale_draft_rejected_until_explicit_revision_review(login):
    operator, inspector, case = assigned_case(login)
    url='/api/v1/cases/'+case['id']+'/inspection'
    body={'notes':'Synthetic draft written before another reviewer changed the case.','checklist':{},'version':case['version'],'idempotency_key':str(uuid.uuid4())}
    newer=operator.post('/api/v1/cases/'+case['id']+'/transition',json={'version':case['version'],'status':'investigating','reason':'Review concurrent synthetic observation'}).json()
    assert inspector.post(url,json=body).status_code==409
    with SessionLocal() as db:
        assert db.query(Evidence).filter_by(case_id=case['id'],idempotency_key=body['idempotency_key']).count()==0
    accepted=inspector.post(url,json={**body,'version':newer['version'],'idempotency_key':str(uuid.uuid4())})
    assert accepted.status_code==200,accepted.text
