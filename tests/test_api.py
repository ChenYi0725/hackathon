from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.interfaces.http import create_app
from app.infrastructure.settings import Settings
from app.infrastructure.text_pdf import read_pdf
from app import store


@pytest.fixture
def client(tmp_path,monkeypatch):
    class FixturePdfReader:
        def read(self, data): return read_pdf(data)
    app = create_app(Settings(data_dir=tmp_path, ai_enabled=False), pdf=FixturePdfReader())
    with TestClient(app) as client:yield client


def test_full_review_fix_audit_export_and_reload(client):
    assert client.get('/api/health').json()['status']=='ok'
    cases=client.get('/api/cases').json();assert len(cases)==2
    cid=next(c['id'] for c in cases if c['demo'])
    current=client.get('/api/cases/'+cid).json()
    response=client.post(f'/api/cases/{cid}/fix/road_width',json={'revision':current['case']['revision']})
    assert response.status_code==200
    updated=response.json()
    assert next(f for f in updated['case']['factors'] if f['id']=='road_width')['entered_rate']==5
    assert client.post(f'/api/cases/{cid}/fix/road_width',json={'revision':current['case']['revision']}).status_code==409
    assert len(client.get(f'/api/cases/{cid}/audit').json())==2
    snapshot=client.get(f'/api/cases/{cid}/audit').json()[-1]['id']
    assert client.get(f'/api/cases/{cid}/audit/{snapshot}').json()['revision']==1
    for kind in ['json','csv','report','forms']:
        r=client.get(f'/api/cases/{cid}/export/{kind}');assert r.status_code==200
    assert '人工植入' in client.get(f'/api/cases/{cid}/export/report').text
    assert client.get(f'/api/cases/{cid}').json()['case']['revision']==2


def test_update_validation_and_concurrency(client):
    c=client.get('/api/cases').json()[0]
    data=client.get('/api/cases/'+c['id']).json()['case']
    original=data.copy();data['title']='修改標題'
    assert client.put('/api/cases/'+c['id'],json=data).status_code==200
    assert client.put('/api/cases/'+c['id'],json=original).status_code==409
    data=client.get('/api/cases/'+c['id']).json()['case']
    data['factors'].append(data['factors'][0])
    assert client.put('/api/cases/'+c['id'],json=data).status_code==400


def test_pdf_upload_persistence_and_serving(client):
    path=Settings().reference('sample')
    if path is None: pytest.skip('External reference PDF is not installed')
    data=path.read_bytes()
    result=client.post('/api/documents?name=test.pdf',content=data,headers={'Content-Type':'application/pdf'})
    assert result.status_code==200,result.text
    case=result.json()['case'];assert case['totals']['individual']==13
    assert result.json()['review']['counts']['pass']==0
    doc=client.get('/api/documents/'+case['document_id']).json();assert len(doc['pages'])==6
    assert client.get('/api/documents/'+case['document_id']+'/file').content==data
    assert client.post('/api/documents',content=b'bad').status_code==422


def test_ruleset_versioning_and_snapshot_isolation(client):
    rules=client.get('/api/rulesets').json()[0];old_id=rules['id']
    rules['version']='2';rules['rules'][0]['matrix'][0][1]=3
    res=client.post('/api/rulesets',json=rules);assert res.status_code==200,res.text
    assert res.json()['id']!=old_id
    old=next(r for r in client.get('/api/rulesets').json() if r['id']==old_id)
    assert old['rules'][0]['matrix'][0][1]==2


def test_bad_origin_unknown_ids_and_html_escape(client):
    assert client.post('/api/samples/original',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/cases/unknown').status_code==404
    c=client.post('/api/cases',json={'title':'<script>alert(1)</script>'}).json()['case']
    report=client.get(f'/api/cases/{c["id"]}/export/report').text
    assert '<script>alert(1)</script>' not in report
    assert '&lt;script&gt;' in report
