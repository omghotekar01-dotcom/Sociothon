import time
import uuid

from services.api.database import SessionLocal
from services.api.models import Audit, Case, Job
from services.api.worker import claim_next, execute_job


def scenario(client, paused=False):
    response = client.post('/api/v1/scenarios', json={'domain':'roads','scenario':'pothole','parameters':{'seed':2026},'start_paused':paused,'idempotency_key':str(uuid.uuid4())})
    assert response.status_code == 202, response.text
    return response.json()


def control(client, job, action):
    response = client.post('/api/v1/jobs/'+job['id']+'/'+action, json={'version':job['control_version'],'reason':'Synthetic verification of worker '+action})
    assert response.status_code == 200, response.text
    return response.json()


def claim(ident):
    # Scope queue selection to this test; unrelated tests can leave queued jobs.
    with SessionLocal() as db:
        others = db.query(Job).filter(Job.id != ident, Job.status.in_(['queued','running','pausing'])).all()
        states = {j.id:j.status for j in others}
        for job in others: job.status='paused'
        db.commit()
        try:
            assert claim_next(db) == ident
            db.expire_all()
            return db.get(Job,ident).claim_token
        finally:
            # Expired running jobs from lease-recovery tests are candidates too.
            # Restore their original state without weakening production claiming.
            for other, status in states.items(): db.get(Job,other).status=status
            db.commit()


def test_queued_pause_resume_permissions_and_versions(login):
    admin, operator = login('admin'), login('operator')
    job = scenario(admin, True)
    assert job['status']=='paused' and not job['checkpoint_ready']
    with SessionLocal() as db:
        assert db.get(Job,job['id']).attempts == 0
    route='/api/v1/jobs/'+job['id']+'/resume'
    body={'version':job['control_version'],'reason':'Try to resume another account job'}
    assert operator.post(route,json=body).status_code == 404
    assert login('citizen').post(route,json=body).status_code in {403,404}
    queued=control(admin,job,'resume')
    assert queued['status']=='queued'
    assert admin.post(route,json=body).status_code == 409
    paused=control(admin,queued,'pause')
    assert paused['status']=='paused'
    stale=admin.post(route,json={**body,'version':queued['control_version']})
    assert stale.status_code==409
    assert admin.get('/api/v1/jobs/'+job['id']).json()['status']=='paused'
    with SessionLocal() as db:
        assert db.get(Job,job['id']).attempts == 0
        actions=[a.action for a in db.query(Audit).all() if a.after.get('job_id')==job['id']]
        assert actions == ['job_resume','job_pause']
    analysis=admin.post('/api/v1/jobs',json={'kind':'analysis','parameters':{'domain':'water'}}).json()
    assert admin.post('/api/v1/jobs/'+analysis['id']+'/pause',json={'version':analysis['control_version'],'reason':'Unsupported analysis control'}).status_code==422


def test_running_pause_saves_checkpoint_and_resume_does_not_recalculate(login, monkeypatch):
    from services.analytics import pipeline
    admin=login('admin'); job=scenario(admin)
    token=claim(job['id']); real=pipeline.run_scenario
    with SessionLocal() as db: before=db.query(Case).count()
    calls=[]
    def calculate(*args,**kwargs):
        result=real(*args,**kwargs)
        current=admin.get('/api/v1/jobs/'+job['id']).json()
        assert control(admin,current,'pause')['status']=='pausing'
        calls.append(result)
        return result
    monkeypatch.setattr(pipeline,'run_scenario',calculate)
    execute_job(job['id'],token)
    paused=admin.get('/api/v1/jobs/'+job['id']).json()
    assert paused['status']=='paused' and paused['checkpoint_ready'] and paused['result'] is None
    with SessionLocal() as db:
        assert db.query(Case).count()==before
        saved=db.get(Job,job['id']).checkpoint
        assert saved['findings']==calls[0]['findings']
    queued=control(admin,paused,'resume')
    new_token=claim(job['id'])
    assert new_token != token
    # A retired claimant may not clear, overwrite or publish the saved result.
    execute_job(job['id'],token)
    assert admin.get('/api/v1/jobs/'+job['id']).json()['status']=='running'
    monkeypatch.setattr(pipeline,'run_scenario',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Checkpoint should be reused')))
    execute_job(job['id'],new_token)
    done=admin.get('/api/v1/jobs/'+job['id']).json()
    assert done['status']=='succeeded' and not done['checkpoint_ready']
    assert done['result']['findings']==saved['findings']
    assert len(done['result']['case_ids'])==len(saved['findings'])
    assert len(set(done['result']['case_ids']))==len(done['result']['case_ids'])
    with SessionLocal() as db: after=db.query(Case).count()
    execute_job(job['id'],new_token)
    with SessionLocal() as db: assert db.query(Case).count()==after
    assert admin.post('/api/v1/jobs/'+job['id']+'/pause',json={'version':done['control_version'],'reason':'Already completed run'}).status_code==409


def test_expired_pause_request_recovers_without_running_old_claim(login):
    admin=login('admin');job=scenario(admin);token=claim(job['id'])
    running=admin.get('/api/v1/jobs/'+job['id']).json()
    control(admin,running,'pause')
    with SessionLocal() as db:
        db.get(Job,job['id']).lease_until=time.time()-1;db.commit()
        claim_next(db)
    recovered=admin.get('/api/v1/jobs/'+job['id']).json()
    assert recovered['status']=='paused' and recovered['attempts']==0
    execute_job(job['id'],token)
    assert admin.get('/api/v1/jobs/'+job['id']).json()['status']=='paused'
