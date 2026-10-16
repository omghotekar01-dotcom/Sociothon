import copy
import uuid

from services.api.database import SessionLocal
from services.api.models import Audit, Configuration, User


def fixture(login):
    operator=login('operator')
    network=operator.get('/api/v1/network').json()
    edge=network['edges'][0]
    body={'name':'Synthetic closure '+uuid.uuid4().hex[:8],'reason':'Synthetic route investigation only','inputs':{'source':edge['source'],'target':edge['target'],'zone_id':None,'closed_edges':[edge['id']]},'configuration_hash':network['configuration_hash'],'idempotency_key':uuid.uuid4().hex}
    return operator,body


def test_named_network_save_retries_restore_exact_inputs_without_case_changes(login):
    operator,body=fixture(login)
    before={c['id']:(c['version'],c['status']) for c in operator.get('/api/v1/cases').json()}
    created=operator.post('/api/v1/network/scenarios',json=body)
    assert created.status_code==200,created.text
    saved=created.json();path='/api/v1/network/scenarios/'+saved['id']
    assert saved['inputs']==body['inputs'] and saved['duplicate'] is False
    assert operator.post('/api/v1/network/scenarios',json=body).json()['duplicate'] is True
    assert operator.post('/api/v1/network/scenarios',json={**body,'name':'Different pending request'}).status_code==409
    assert operator.get(path).json()['inputs']==body['inputs']
    assert any(s['id']==saved['id'] for s in operator.get('/api/v1/network/scenarios').json())
    assert {c['id']:(c['version'],c['status']) for c in operator.get('/api/v1/cases').json()}==before
    with SessionLocal() as db:
        assert len([a for a in db.query(Audit).filter_by(action='network_scenario_saved').all() if a.after.get('scenario_id')==saved['id']])==1


def test_saved_network_owner_permissions_and_revoked_zone_scope(login):
    operator,body=fixture(login);saved=operator.post('/api/v1/network/scenarios',json=body).json();path='/api/v1/network/scenarios/'+saved['id']
    assert login('admin').get(path).status_code==404
    assert login('citizen').get('/api/v1/network/scenarios').status_code==403
    assert login('inspector').post('/api/v1/network/scenarios',json=body).status_code==403
    with SessionLocal() as db:
        user=db.get(User,'demo-operator');old=copy.deepcopy(user.zones);user.zones=[];db.commit()
    try:
        assert operator.get('/api/v1/network/scenarios').json()==[]
        assert operator.get(path).status_code==403
        assert operator.post('/api/v1/network/scenarios',json=body).status_code==403
    finally:
        with SessionLocal() as db:db.get(User,'demo-operator').zones=old;db.commit()


def test_topology_change_rejects_load_and_new_save_but_exact_retry_recovers_original(login):
    operator,body=fixture(login);saved=operator.post('/api/v1/network/scenarios',json=body).json()
    with SessionLocal() as db:
        row=db.get(Configuration,'network');original=copy.deepcopy(row.value);changed=copy.deepcopy(original);changed['edges'][0]['length_m']+=1;row.value=changed;db.commit()
    try:
        assert operator.get('/api/v1/network/scenarios/'+saved['id']).status_code==409
        assert next(s for s in operator.get('/api/v1/network/scenarios').json() if s['id']==saved['id'])['topology_changed'] is True
        assert operator.post('/api/v1/network/scenarios',json={**body,'idempotency_key':uuid.uuid4().hex}).status_code==409
        assert operator.post('/api/v1/network/scenarios',json=body).json()['duplicate'] is True
    finally:
        with SessionLocal() as db:db.get(Configuration,'network').value=original;db.commit()


def test_archive_restore_versions_and_invalid_selection(login):
    operator,body=fixture(login)
    assert operator.post('/api/v1/network/scenarios',json={**body,'reason':'     '}).status_code==422
    assert operator.post('/api/v1/network/scenarios',json={**body,'inputs':{**body['inputs'],'closed_edges':['not-a-pipe']}}).status_code==422
    saved=operator.post('/api/v1/network/scenarios',json=body).json();path='/api/v1/network/scenarios/'+saved['id']
    archive={'version':saved['version'],'archived':True,'reason':'Archive synthetic experiment'}
    result=operator.post(path+'/archive',json=archive);assert result.status_code==200,result.text
    assert result.json()['archived'] is True and result.json()['version']==saved['version']+1
    assert operator.get(path).status_code==409
    assert operator.post(path+'/archive',json=archive).status_code==409
    restored=operator.post(path+'/archive',json={**archive,'version':result.json()['version'],'archived':False,'reason':'Restore synthetic experiment'})
    assert restored.status_code==200
    assert operator.get(path).json()['inputs']==body['inputs']
