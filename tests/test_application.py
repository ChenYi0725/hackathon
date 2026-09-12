import ast
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.application.ports import RevisionConflict
from app.domain.models import Factor, Evidence
from app.domain.rules import default_rules
from app.infrastructure.settings import Settings
from app.interfaces.http import create_app


class Pdf:
    def read(self, data):
        return [{'page': 1, 'text': '寬度 5 7', 'method': 'paddleocr', 'lines': [{'text': '寬度 5 7', 'confidence': .99, 'bbox': [0, 0, 100, 20]}]}]


class Ai:
    def __init__(self): self.calls = []
    def extract(self, pages, ruleset):
        self.calls.append((pages, ruleset))
        return [Factor(id='width', subject='5', comparable='7', evidence=Evidence(page=1, quote='寬度 5 7', method='bedrock:test'))]


@pytest.fixture
def context(tmp_path):
    ai = Ai()
    app = create_app(Settings(data_dir=tmp_path), pdf=Pdf(), ai=ai)
    with TestClient(app) as client:
        case = client.post('/api/documents?name=synthetic.pdf', content=b'%PDF-test').json()['case']
        yield client, ai, app.state.service, case


def test_ai_requires_cloud_data_confirmation_and_only_returns_preview(context):
    client, ai, service, case = context
    url = f'/api/cases/{case["id"]}/ai'
    assert client.post(url, json={'revision': case['revision']}).status_code == 400
    assert ai.calls == []
    response = client.post(url, json={'revision': case['revision'], 'cloud_data_approved': True})
    assert response.status_code == 200
    assert response.json()['factors'][0]['confirmed'] is False
    assert service.get_case(case['id'])['case'] == case
    assert len(service.repository.audit(case['id'])) == 1


def test_paddle_page_geometry_is_persisted_and_served(context):
    client, ai, service, case = context
    page = client.get('/api/documents/' + case['document_id']).json()['pages'][0]
    assert page['method'] == 'paddleocr'
    assert page['lines'][0]['bbox'] == [0, 0, 100, 20]
    assert client.get('/api/documents/' + case['document_id'] + '/file').content == b'%PDF-test'


def test_case_selected_ruleset_is_forwarded_to_bedrock(context):
    client, ai, service, case = context
    rules = default_rules()
    rules['name'] = '案件專用基準'
    created = client.post('/api/rulesets', json=rules).json()
    case['ruleset_id'] = created['id']
    case = client.put('/api/cases/' + case['id'], json=case).json()['case']
    response = client.post(f'/api/cases/{case["id"]}/ai', json={'revision': case['revision'], 'cloud_data_approved': True})
    assert response.status_code == 200
    assert ai.calls[0][1]['id'] == created['id']


def test_stale_ai_result_is_rejected_after_concurrent_update(context):
    client, ai, service, case = context
    original = ai.extract
    def update_during_extraction(pages, ruleset):
        current = service.repository.get_case(case['id'])
        service.repository.save_case(current, 'concurrent update')
        return original(pages, ruleset)
    ai.extract = update_during_extraction
    response = client.post(f'/api/cases/{case["id"]}/ai', json={'revision': case['revision'], 'cloud_data_approved': True})
    assert response.status_code == 409


def test_domain_and_application_do_not_import_infrastructure():
    root = Path(__file__).resolve().parents[1] / 'app'
    forbidden = ('app.infrastructure', 'app.interfaces', 'app.bootstrap', 'fastapi', 'boto3', 'paddleocr', 'sqlite3')
    for path in [*(root / 'domain').glob('*.py'), *(root / 'application').glob('*.py')]:
        for node in ast.walk(ast.parse(path.read_text())):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert not any(name.startswith(forbidden) for name in names), path
