import io
import uuid

from PIL import Image
from services.api.database import SessionLocal
from services.api.models import Audit, Evidence


def report(client):
    response = client.post('/api/v1/reports', json={
        'domain': 'water', 'zone_id': 'river', 'title': 'Synthetic photo recovery',
        'description': 'Synthetic photograph upload recovery verification.',
        'location': 'Public test landmark', 'idempotency_key': str(uuid.uuid4())})
    assert response.status_code == 201
    return response.json()['case_id']


def photo(color='blue'):
    stream = io.BytesIO()
    Image.new('RGB', (12, 12), color).save(stream, 'PNG')
    return stream.getvalue()


def upload(client, case_id, key, color='blue', notes='Citizen observation'):
    return client.post(f'/api/v1/cases/{case_id}/evidence',
                       files={'file': ('synthetic.png', photo(color), 'image/png')},
                       data={'notes': notes, 'idempotency_key': key})


def test_photo_confirmation_lookup_and_retry_leave_one_evidence_and_audit(login):
    citizen = login('citizen')
    case_id, key = report(citizen), str(uuid.uuid4())
    lookup = f'/api/v1/cases/{case_id}/evidence/submissions/{key}'
    assert citizen.get(lookup).json() == {'evidence': None}
    first = upload(citizen, case_id, key)
    assert first.status_code == 200, first.text
    assert citizen.get(lookup).json()['evidence'] == first.json()
    retried = upload(citizen, case_id, key)
    assert retried.status_code == 200
    assert retried.json()['id'] == first.json()['id']
    assert retried.json()['idempotent'] is True
    assert citizen.get(first.json()['url']).status_code == 200
    with SessionLocal() as db:
        assert db.query(Evidence).filter_by(case_id=case_id, actor_id='demo-citizen', idempotency_key=key).count() == 1
        assert db.query(Audit).filter_by(case_id=case_id, action='evidence_added').count() == 1


def test_photo_recovery_is_actor_and_case_scoped_and_requires_current_access(login):
    citizen, operator, inspector = login('citizen'), login('operator'), login('inspector')
    case_id, key = report(citizen), str(uuid.uuid4())
    assert upload(citizen, case_id, key).status_code == 200
    lookup = f'/api/v1/cases/{case_id}/evidence/submissions/{key}'
    assert operator.get(lookup).json() == {'evidence': None}
    assert inspector.get(lookup).status_code == 403
    other_case = report(citizen)
    assert citizen.get(f'/api/v1/cases/{other_case}/evidence/submissions/{key}').json() == {'evidence': None}
    citizen.post('/api/v1/auth/logout')
    assert citizen.get(lookup).status_code == 401


def test_photo_pending_identifier_cannot_be_reused_for_changed_bytes_or_notes(login):
    citizen = login('citizen')
    case_id, key = report(citizen), str(uuid.uuid4())
    original = upload(citizen, case_id, key).json()
    assert upload(citizen, case_id, key, color='red').status_code == 409
    assert upload(citizen, case_id, key, notes='Different note').status_code == 409
    assert citizen.get(f'/api/v1/cases/{case_id}/evidence/submissions/{key}').json()['evidence']['id'] == original['id']
    assert citizen.get(f'/api/v1/cases/{case_id}/evidence/submissions/short').status_code == 422
    assert citizen.get(f'/api/v1/cases/{case_id}/evidence/submissions/'+('x'*101)).status_code == 422
