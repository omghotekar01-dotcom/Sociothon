import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text, inspect
from database.migrations import migrate
from services.api.database import Base
from services.api.field_schema import SCHEMAS, validate_observations


@pytest.mark.parametrize("domain",list(SCHEMAS))
def test_domain_fields_accept_manual_observations_only(domain):
    field=SCHEMAS[domain][0]
    value=50 if field["type"]=="number" else "Recorded field observation"
    assert validate_observations(domain,{field["key"]:value}) == {field["key"]:value}
    with pytest.raises(HTTPException):
        validate_observations(domain,{"invented_field":"Unaccepted"})
    with pytest.raises(HTTPException):
        validate_observations(domain,{field["key"]:float('nan') if field["type"]=="number" else []})


def test_water_measurement_needs_method_and_duration():
    with pytest.raises(HTTPException):
        validate_observations("water",{"measured_volume_l":20})
    assert validate_observations("water",{"measured_volume_l":0,"measurement_minutes":5,"measurement_method":"Manual interval measurement"})["measured_volume_l"] == 0
    for value in [True, -1, float('inf')]:
        with pytest.raises(HTTPException):
            validate_observations("roads",{"measured_length_m":value})


def test_field_observation_upgrade_preserves_legacy_evidence():
    from database.migrations import BASELINE,EVIDENCE_KEYS,CASE_INSPECTORS,BASELINE_VERSIONS,JOB_CONTROLS,SCENARIO_PLAYBACK,DEMO_SESSION_ISOLATION,FIELD_OBSERVATIONS
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE schema_migrations (revision VARCHAR PRIMARY KEY, applied_at VARCHAR NOT NULL)'))
        for revision in [BASELINE,EVIDENCE_KEYS,CASE_INSPECTORS,BASELINE_VERSIONS,JOB_CONTROLS,SCENARIO_PLAYBACK,DEMO_SESSION_ISOLATION]:
            conn.execute(text('INSERT INTO schema_migrations VALUES (:r, :a)'),{'r':revision,'a':'2026-10-15'})
        conn.execute(text('CREATE TABLE evidence (id VARCHAR PRIMARY KEY, notes TEXT NOT NULL)'))
        conn.execute(text("INSERT INTO evidence VALUES ('legacy','Existing inspection')"))
    migrate(engine,Base.metadata)
    migrate(engine,Base.metadata)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT notes,observations FROM evidence')).one() == ('Existing inspection','{}')
        assert conn.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:r'),{'r':FIELD_OBSERVATIONS}).scalar_one() == 1
    engine.dispose()


def test_observations_persist_and_idempotency_rejects_modified_measurements(login):
    citizen=login('citizen'); admin=login('admin')
    report=citizen.post('/api/v1/reports',json={'domain':'water','zone_id':'river','title':'Synthetic structured field verification','description':'Synthetic observation for domain form integration verification.','location':'Synthetic test facility','idempotency_key':str(uuid.uuid4())}).json()
    case=admin.get('/api/v1/cases/'+report['case_id']).json()
    schema=admin.get('/api/v1/cases/'+case['id']+'/field-schema')
    assert schema.status_code == 200 and schema.json()['domain']=='water'
    body={'notes':'Synthetic inspection of the selected water asset.','version':case['version'],'idempotency_key':str(uuid.uuid4()),'observations':{'observed_condition':'Pooling reported; physical cause not established','measured_volume_l':10,'measurement_minutes':5,'measurement_method':'Synthetic timed measurement'}}
    path='/api/v1/cases/'+case['id']+'/inspection'
    result=admin.post(path,json=body)
    assert result.status_code==200,result.text
    record=result.json()['evidence_records'][-1]
    assert record['observations']==body['observations']
    repeat=admin.post(path,json=body)
    assert repeat.status_code==200 and len(repeat.json()['evidence_records'])==1
    body['observations']['measured_volume_l']=12
    assert admin.post(path,json=body).status_code==409
    assert login('operator').post(path,json=body).status_code==403
