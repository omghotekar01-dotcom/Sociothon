from copy import deepcopy

from services.analytics.pipeline import network_data, network_path
from services.api.database import SessionLocal
from services.api.models import Case, Configuration, User


def test_network_alternate_closure_reopening_and_direction():
    baseline = network_path('reservoir-main', 'water-hill')
    assert baseline['path_edges'] == ['pipe-01', 'pipe-06']
    assert baseline['distance_m'] == 1650
    rerouted = network_path('reservoir-main', 'water-hill', ['pipe-06'])
    assert rerouted['path_edges'] == ['pipe-01', 'pipe-03', 'pipe-05']
    assert rerouted['distance_m'] == 2250
    isolated = network_path('reservoir-main', 'water-hill', ['pipe-06', 'pipe-03'])
    assert not isolated['connected'] and isolated['distance_m'] is None
    assert 'water-hill' in isolated['unreachable']
    assert not network_path('water-hill', 'reservoir-main')['connected']
    assert network_path('water-hill', 'water-hill')['distance_m'] == 0
    assert network_path('reservoir-main', 'water-hill') == baseline
    config = network_data()
    config['edges'][0]['open'] = False
    assert network_path('reservoir-main', 'water-hill', data=config)['reachable'] == []


def test_network_api_closures_are_read_only_and_use_stored_graph(login):
    op = login('operator')
    with SessionLocal() as db:
        original = deepcopy(db.get(Configuration, 'network').value)
        cases_before = [(c.id, c.version, c.status) for c in db.query(Case).order_by(Case.id)]
        updated = deepcopy(original)
        updated['edges'][0]['length_m'] = 10
        db.get(Configuration, 'network').value = updated
        db.commit()
    try:
        body = {'source': 'reservoir-main', 'target': 'water-hill'}
        baseline = op.post('/api/v1/network/path', json=body)
        assert baseline.status_code == 200, baseline.text
        assert baseline.json()['distance_m'] == 1040
        closed = op.post('/api/v1/network/path', json={**body, 'closed_edges': ['pipe-01']}).json()
        assert not closed['connected'] and closed['reachable'] == []
        assert login('admin').post('/api/v1/network/path', json=body).json()['connected']
        assert op.post('/api/v1/network/path', json=body).json() == baseline.json()
        assert op.post('/api/v1/network/path', json={**body, 'closed_edges': ['missing']}).status_code == 422
        with SessionLocal() as db:
            assert db.get(Configuration, 'network').value == updated
            assert [(c.id, c.version, c.status) for c in db.query(Case).order_by(Case.id)] == cases_before
    finally:
        with SessionLocal() as db:
            db.get(Configuration, 'network').value = original
            db.commit()


def test_network_scoped_traversal_cannot_bridge_restricted_zones(login):
    op = login('operator')
    with SessionLocal() as db:
        user = db.get(User, 'demo-operator')
        original = list(user.zones)
        user.zones = ['river', 'hill']
        db.commit()
    try:
        graph = op.get('/api/v1/network').json()
        assert 'junction-east' not in [n['id'] for n in graph['nodes']]
        body = {'source': 'reservoir-main', 'target': 'water-hill', 'closed_edges': ['pipe-06']}
        response = op.post('/api/v1/network/path', json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert not result['connected']
        assert result['reachable'] == ['tank-central', 'water-river']
        assert 'water-hill' in result['unreachable']
        assert op.post('/api/v1/network/path', json={**body, 'closed_edges': ['pipe-03']}).status_code == 422
        assert op.post('/api/v1/network/path', json={**body, 'target': 'water-market'}).status_code == 403
    finally:
        with SessionLocal() as db:
            db.get(User, 'demo-operator').zones = original
            db.commit()


def test_network_zone_filter_and_citizen_access(login):
    op, citizen = login('operator'), login('citizen')
    body = {'source': 'reservoir-main', 'target': 'water-river', 'zone_id': 'river'}
    response = op.post('/api/v1/network/path', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['path_edges'] == ['pipe-01', 'pipe-02']
    assert result['reachable'] == ['tank-central', 'water-river']
    assert op.post('/api/v1/network/path', json={**body, 'target': 'water-hill'}).status_code == 422
    assert op.post('/api/v1/network/path', json={**body, 'zone_id': 'not-a-zone'}).status_code == 422
    assert op.post('/api/v1/network/path', json={**body, 'closed_edges': ['pipe-06']}).status_code == 422
    assert citizen.get('/api/v1/network').status_code == 403
    assert citizen.post('/api/v1/network/path', json=body).status_code == 403
