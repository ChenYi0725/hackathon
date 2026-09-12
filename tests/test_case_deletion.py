from fastapi.testclient import TestClient

from app.infrastructure.settings import Settings
from app.interfaces.http import create_app


def test_delete_persists_and_does_not_reseed_or_resurrect(tmp_path):
    settings = Settings(data_dir=tmp_path, ai_enabled=False)
    app = create_app(settings)
    with TestClient(app) as client:
        cases = client.get('/api/cases').json()
        assert len(cases) == 2
        repository = app.state.service.repository
        document_id = repository.save_document(b'%PDF-synthetic', 'synthetic.pdf', [])
        saved = []
        for case in cases:
            body = client.get('/api/cases/' + case['id']).json()['case']
            body['document_id'] = document_id
            saved.append(client.put('/api/cases/' + case['id'], json=body).json()['case'])
        for index, body in enumerate(saved):
            url = '/api/cases/' + body['id']
            audit_id = client.get(url + '/audit').json()[0]['id']
            response = client.request('DELETE', url, json={'revision': body['revision']})
            assert response.status_code == 200
            assert response.json() == {'deleted': body['id']}
            for suffix in ('', '/audit', f'/audit/{audit_id}', '/export/json'):
                assert client.get(url + suffix).status_code == 404
            assert client.put(url, json=body).status_code == 404
            assert client.request('DELETE', url, json={'revision': body['revision']}).status_code == 404
            if index == 0:
                assert client.get('/api/documents/' + document_id + '/file').content == b'%PDF-synthetic'
            else:
                assert client.get('/api/documents/' + document_id).status_code == 404
                assert client.get('/api/documents/' + document_id + '/file').status_code == 404
        assert client.get('/api/cases').json() == []
        with repository.db() as db:
            assert db.execute("SELECT COUNT(*) FROM audit WHERE action='刪除案件'").fetchone()[0] == 2
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/cases').json() == []
        assert client.post('/api/cases', json={'title': '新案件'}).status_code == 200


def test_delete_requires_current_revision_and_preserves_other_cases(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, ai_enabled=False))
    with TestClient(app) as client:
        cases = client.get('/api/cases').json()
        case = cases[0]
        url = '/api/cases/' + case['id']
        body = client.get(url).json()['case']
        assert body['revision'] == case['revision']
        assert client.request('DELETE', url).status_code == 422
        assert client.request('DELETE', url, json={'revision': case['revision']},
                              headers={'Origin': 'https://evil.example'}).status_code == 403
        body['title'] = '更新後案件'
        updated = client.put(url, json=body).json()['case']
        assert client.request('DELETE', url, json={'revision': case['revision']}).status_code == 409
        assert client.get(url).json()['case'] == updated
        assert len(client.get(url + '/audit').json()) == 2
        assert client.request('DELETE', url, json={'revision': updated['revision']}).status_code == 200
        assert [c['id'] for c in client.get('/api/cases').json()] == [cases[1]['id']]
