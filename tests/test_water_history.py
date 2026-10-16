import copy
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from services.analytics.water_history import historical_schedule_review, compare_meter_group
from services.api.database import SessionLocal
from services.api.models import Asset, Configuration, Reading

START = datetime(2031, 1, 6, tzinfo=timezone.utc)


def row(asset="a", hour=0, volume=100, **changes):
    return {"id": f"{asset}-{hour}", "asset_id": asset, "timestamp": (START+timedelta(hours=hour)).isoformat(), "interval_minutes": 60, "quantity": volume, "unit": "L", "source": "Synthetic", "quality_flag": "valid", **changes}


def entry(start=START, end=START+timedelta(hours=1), **changes):
    return {"id":"period-1", "effective_from":start.isoformat(), "effective_until":end.isoformat(), "configuration_version":1, "source_reference":"Synthetic notice", "schedule":{"timezone":"UTC", "supply_windows":[{"days":[0,1,2,3,4,5,6], "start_minute":0, "end_minute":1440}], "exceptions":[], "outside_rate_lph":0}, **changes}


def test_historical_schedule_preserves_unknown_gaps_and_boundary_intervals():
    assert historical_schedule_review([row()], [entry()])[0]["status"] == "within_window"
    assert historical_schedule_review([row(hour=1)], [entry()])[0]["status"] == "history_missing"
    assert historical_schedule_review([row(hour=.5)], [entry()])[0]["status"] == "history_boundary"
    assert historical_schedule_review([row()], [entry(revoked_at=START.isoformat())])[0]["status"] == "history_missing"
    assert historical_schedule_review([row(quantity=None)], [entry()])[0]["status"] == "data_quality"
    adjacent = entry(start=START+timedelta(hours=1), end=START+timedelta(hours=2), id="period-2")
    assert historical_schedule_review([row(hour=.5)], [entry(), adjacent])[0]["status"] == "history_boundary"


def test_group_comparison_converts_units_and_requires_every_meter_complete():
    before=[row(asset=a,hour=h) for a in ['a','b'] for h in range(24)]
    after=[row(asset=a,hour=168+h,volume=.08,unit='m3') for a in ['a','b'] for h in range(24)]
    args=(['a','b'], START, START+timedelta(days=1), START+timedelta(days=7), START+timedelta(days=8))
    result=compare_meter_group(before,after,*args)
    assert result['before_total_l']==4800 and result['after_total_l']==3840
    assert result['observed_reduction_l']==960 and not result['closure_eligible']
    # Missing final reading, invalid observation, overlap and boundary crossing all fail.
    for bad in [after[:-1], after+[after[-1]], [*after[:-1],{**after[-1],'quantity':None}], [*after[:-1],{**after[-1],'interval_minutes':120}]]:
        result=compare_meter_group(before,bad,*args)
        assert result['status']=='insufficient_followup' and result['observed_reduction_l'] is None
    zeros=[{**r,'quantity':0} for r in before]
    assert compare_meter_group(zeros,after,*args)['observed_reduction_l']==-3840


@pytest.fixture
def setup_water(login):
    admin,operator,citizen=login('admin'),login('operator'),login('citizen')
    path='/api/v1/water/zones/river'
    keys=['water-operations:river','water-schedule-history:river']
    ids=['history-'+uuid.uuid4().hex for _ in range(3)]
    with SessionLocal() as db:
        originals={key: (copy.deepcopy(db.get(Configuration,key).value),db.get(Configuration,key).version) if db.get(Configuration,key) else None for key in keys}
        for ident in ids: db.add(Asset(id=ident,name=ident,domain='water',zone_id='river',kind='meter',provenance='Synthetic'))
        db.flush()
        for ident in ids[1:]:
            for h in [*range(24),*range(168,192)]:
                db.add(Reading(**row(asset=ident,hour=h,volume=100 if h<24 else 80),zone_id='river',domain='water',original={}))
        db.commit()
    old=admin.get(path+'/operations').json()['configuration']
    config={**old,'reason':'Synthetic comparison fixture','timezone':'UTC','supply_windows':[{'days':list(range(7)),'start_minute':0,'end_minute':1440,'label':'Synthetic all-day supply'}],'exceptions':[], 'inlet_ids':[ids[0]],'consumption_ids':ids[1:],'outlet_ids':[], 'meter_parents':{ids[1]:ids[0],ids[2]:ids[0]},'boundary_confirmed':True}
    saved=admin.put(path+'/operations',json=config)
    assert saved.status_code==200,saved.text
    try: yield admin,operator,citizen,path,ids,saved.json()
    finally:
        with SessionLocal() as db:
            db.query(Reading).filter(Reading.asset_id.in_(ids)).delete(synchronize_session=False)
            db.query(Asset).filter(Asset.id.in_(ids)).delete(synchronize_session=False)
            for key,original in originals.items():
                item=db.get(Configuration,key)
                if original:
                    item.value,item.version=original
                elif item: db.delete(item)
            db.commit()


def history_body(admin,path,config):
    history=admin.get(path+'/operations').json()['schedule_history']
    return {'version':history['version'],'configuration_version':config['version'],'effective_from':START.isoformat(),'effective_until':(START+timedelta(days=1)).isoformat(),'source_reference':'Synthetic dated supply notice','reason':'Test recorded effective schedule','idempotency_key':uuid.uuid4().hex}


def test_history_permission_overlap_retry_correction_and_snapshot_freeze(setup_water):
    admin,operator,citizen,path,ids,config=setup_water
    body=history_body(admin,path,config)
    assert operator.post(path+'/schedule-history',json=body).status_code==403
    assert citizen.get(path+'/operations').status_code==403
    response=admin.post(path+'/schedule-history',json=body)
    assert response.status_code==200,response.text
    history=response.json();assert history['version']==body['version']+1
    record=history['entries'][-1]
    assert admin.post(path+'/schedule-history',json=body).json()==history
    assert admin.post(path+'/schedule-history',json={**body,'reason':'Different pending request'}).status_code==409
    assert admin.post(path+'/schedule-history',json={**body,'version':history['version'],'idempotency_key':uuid.uuid4().hex}).status_code==409
    changed=admin.put(path+'/operations',json={**config,'outside_rate_lph':777,'reason':'Change live schedule threshold'}).json()
    assert admin.get(path+'/operations').json()['schedule_history']['entries'][-1]['schedule']['outside_rate_lph']==config['outside_rate_lph']
    review={'start':START.isoformat(),'end':(START+timedelta(days=1)).isoformat(),'configuration_version':changed['version'],'schedule_mode':'historical','history_version':history['version']}
    result=operator.post(path+'/review',json=review);assert result.status_code==200,result.text
    snapshot=result.json();assert snapshot['schedule_counts']['within_window']==48
    assert all(r['schedule_record_id']==record['id'] for r in snapshot['schedule'])
    report=citizen.post('/api/v1/reports',json={'domain':'water','zone_id':'river','title':'Synthetic historical schedule evidence','description':'A synthetic verification report, not a real incident.','location':'Synthetic test site','idempotency_key':uuid.uuid4().hex}).json()
    case=operator.get('/api/v1/cases/'+report['case_id']).json()
    attachment={'review':snapshot['review_inputs'],'snapshot_hash':snapshot['snapshot_hash'],'case_version':case['version'],'reason':'Historical context for synthetic report','idempotency_key':uuid.uuid4().hex}
    attached=operator.post(path+'/cases/'+case['id']+'/reviews',json=attachment)
    assert attached.status_code==200,attached.text
    revoke=admin.post(path+'/schedule-history/'+record['id']+'/revoke',json={'version':history['version'],'reason':'Correct unsupported source reference'})
    assert revoke.status_code==200
    assert operator.post(path+'/review',json=review).status_code==409
    new=operator.post(path+'/review',json={**review,'history_version':revoke.json()['version']}).json()
    assert new['schedule_counts']['history_missing']==48
    assert snapshot['schedule_history_snapshot']['entries'][-1].get('revoked_at') is None
    saved_case=operator.get('/api/v1/cases/'+case['id']).json()
    assert saved_case['evidence_records'][0]['observations']['water_review']==snapshot
    assert operator.post(path+'/cases/'+case['id']+'/reviews',json=attachment).json()['duplicate'] is True
    assert operator.post(path+'/cases/'+case['id']+'/reviews',json={**attachment,'case_version':saved_case['version'],'idempotency_key':uuid.uuid4().hex}).status_code==409
    assert admin.post(path+'/schedule-history',json={**body,'version':revoke.json()['version'],'configuration_version':changed['version'],'idempotency_key':uuid.uuid4().hex}).status_code==200


def test_history_requires_valid_effective_dates_sources_and_fresh_configuration(setup_water):
    admin,_,_,path,_,config=setup_water;body=history_body(admin,path,config)
    for patch in [{'effective_from':'2031-01-06T00:00:00'},{'effective_until':body['effective_from']},{'source_reference':'     '}]:
        assert admin.post(path+'/schedule-history',json={**body,**patch}).status_code==422
    assert admin.post(path+'/schedule-history',json={**body,'configuration_version':config['version']+1}).status_code==409


def group_body(ids,config):
    return {'configuration_version':config['version'],'meter_ids':ids[1:],'before_start':START.isoformat(),'before_end':(START+timedelta(days=1)).isoformat(),'after_start':(START+timedelta(days=7)).isoformat(),'after_end':(START+timedelta(days=8)).isoformat(),'independent_meters_confirmed':True,'context_note':'Synthetic siblings below the same inlet; unchanged supply.'}


def test_group_api_scoping_accounting_roles_and_exact_sources(setup_water):
    admin,operator,citizen,path,ids,config=setup_water;body=group_body(ids,config)
    response=operator.post(path+'/impact-comparison',json=body)
    assert response.status_code==200,response.text
    result=response.json();assert result['observed_reduction_l']==960
    assert len(result['source_observations']['after'])==48 and len(result['snapshot_hash'])==64
    assert citizen.post(path+'/impact-comparison',json=body).status_code==403
    assert operator.post(path.replace('river','hill')+'/impact-comparison',json=body).status_code in (409,422)
    assert operator.post(path+'/impact-comparison',json={**body,'meter_ids':[ids[0],ids[1]]}).status_code==422
    assert operator.post(path+'/impact-comparison',json={**body,'meter_ids':[ids[1],ids[1]]}).status_code==422
    assert operator.post(path+'/impact-comparison',json={**body,'configuration_version':config['version']+1}).status_code==409
    assert operator.post(path+'/impact-comparison',json={**body,'independent_meters_confirmed':False}).status_code==422
    # Parent and child cannot be assigned to the summed consumption role.
    assert admin.put(path+'/operations',json={**config,'meter_parents':{ids[2]:ids[1]},'reason':'Invalid overlapping meter comparison'}).status_code==422


def test_group_api_rejects_unmatched_incomplete_and_unequal_windows(setup_water):
    _,operator,_,path,ids,config=setup_water;body=group_body(ids,config)
    assert operator.post(path+'/impact-comparison',json={**body,'after_end':(START+timedelta(days=9)).isoformat()}).status_code==422
    assert operator.post(path+'/impact-comparison',json={**body,'before_start':START.replace(tzinfo=None).isoformat()}).status_code==422
    mismatch={**body,'after_start':(START+timedelta(days=6)).isoformat(),'after_end':(START+timedelta(days=7)).isoformat()}
    result=operator.post(path+'/impact-comparison',json=mismatch).json()
    assert result['status']=='insufficient_followup' and result['observed_reduction_l'] is None
    with SessionLocal() as db:
        db.query(Reading).filter_by(asset_id=ids[2],timestamp=(START+timedelta(hours=191)).isoformat()).delete();db.commit()
    result=operator.post(path+'/impact-comparison',json=body).json()
    assert result['observed_reduction_l'] is None and result['before_total_l'] is None
