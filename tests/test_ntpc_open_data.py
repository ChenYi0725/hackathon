import httpx
import pytest
import ssl
from fastapi.testclient import TestClient
from app.interfaces.http import create_app
from app.infrastructure.settings import Settings

from app.application.open_data import DatasetRead, DatasetSearch, OpenDataUnavailable
from app.infrastructure.ntpc_open_data import NtpcOpenData
from app.application.agentic_rag import AgenticRagService
from app.application.agent_contracts import AgentTurn, ToolCall
from app.application.rag_contracts import AnswerDraft, AnswerStatement
from app.application.ports import ExtractionUnavailable, RevisionConflict
from app.domain.models import Case
from app.infrastructure.persistence import SQLiteReviewRepository

ID = '12345678-1234-1234-1234-123456789abc'


def provider(rows=None):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url.host == 'data.ntpc.gov.tw'
        if '/openapi/' in request.url.path:
            return httpx.Response(200, json={'paths': {
                '/api/datasets/' + ID + '/json': {'get': {'summary': '合成樹林資料', 'description': '測試'}},
                '/api/datasets/' + ID + '/csv': {'get': {'summary': '合成樹林資料'}},
                'https://example.com/evil': {'get': {'summary': '合成樹林資料'}},
            }})
        assert request.url.params['page'] == '0'
        return httpx.Response(200, json=[{'district': '合成樹林區', 'value': '未知'}] if rows is None else rows)
    return NtpcOpenData(httpx.MockTransport(handle)), requests


def test_discovery_pagination_provenance_and_cache():
    adapter, requests = provider()
    assert adapter._tls.check_hostname and adapter._tls.verify_mode == ssl.CERT_REQUIRED
    result = adapter.search(DatasetSearch(keyword='合成 樹林'))
    assert [d['dataset_id'] for d in result['datasets']] == [ID]
    assert adapter.search(DatasetSearch(keyword='不存在'))['datasets'] == []
    page = adapter.read(DatasetRead(dataset_id=ID, size=1))
    assert page['next_page'] == 1 and page['fetched_at']
    assert page['records'][0]['value'] == '未知'
    assert 'size=1' in page['source_url']
    assert adapter.read(DatasetRead(dataset_id=ID, size=1)) == page
    assert len(requests) == 2


@pytest.mark.parametrize('reply', [httpx.Response(503), httpx.Response(302, headers={'Location': 'https://example.com'}),
                                  httpx.Response(200, text='not json'), httpx.Response(200, json={'error': 'offline'})])
def test_errors_are_not_empty_results_and_redirects_are_not_followed(reply):
    calls = []
    def handle(request):
        calls.append(request)
        return reply
    with pytest.raises(OpenDataUnavailable):
        NtpcOpenData(httpx.MockTransport(handle)).read(DatasetRead(dataset_id=ID))
    assert len(calls) == 1


def test_timeout_and_oversized_response_are_bounded():
    def timeout(request):
        raise httpx.ReadTimeout('private upstream message')
    with pytest.raises(OpenDataUnavailable, match='暫時無法'):
        NtpcOpenData(httpx.MockTransport(timeout)).read(DatasetRead(dataset_id=ID))
    adapter, _ = provider([{'text': 'x' * 13000}])
    with pytest.raises(OpenDataUnavailable, match='過長'):
        adapter.read(DatasetRead(dataset_id=ID))


@pytest.mark.parametrize('arguments', [{'dataset_id': '../../.env'}, {'dataset_id': ID, 'size': 1000},
                                       {'dataset_id': ID, 'page': -1}, {'dataset_id': ID, 'page': True},
                                       {'dataset_id': ID, 'url': 'https://example.com'}])
def test_read_inputs_reject_unbounded_or_arbitrary_requests(arguments):
    with pytest.raises(ValueError):
        DatasetRead(**arguments)


@pytest.mark.parametrize('mode', ['success', 'empty', 'outage', 'unsearched', 'fake', 'revision'])
def test_agent_official_data_citations_and_no_case_mutations(tmp_path, mode):
    repo = SQLiteReviewRepository(tmp_path)
    repo.initialize()
    case = repo.save_case(Case(title='合成', valuation_date='1140901'), 'test', new=True)
    audit = repo.audit(case.id)
    adapter, requests = provider([] if mode == 'empty' else None)
    if mode == 'outage':
        def fail(query):
            raise OpenDataUnavailable('官方 API 暫時無法讀取')
        adapter.read = fail
    if mode == 'revision':
        original = adapter.read
        def race(query):
            result = original(query)
            repo.save_case(case, 'concurrent edit')
            return result
        adapter.read = race
    class Model:
        def next_turn(self, context, history, tools):
            assert 'read_public_dataset' in {t['name'] for t in tools}
            if not history and mode != 'unsearched':
                return AgentTurn(calls=(ToolCall(id='s', name='search_public_datasets', arguments={'keyword': '樹林'}),))
            if len(history) == (0 if mode == 'unsearched' else 1):
                return AgentTurn(calls=(ToolCall(id='r', name='read_public_dataset', arguments={'dataset_id': ID}),))
            data = history[-1]['results'][0]
            if mode in {'outage', 'unsearched'}:
                assert data['status'] == 'error'
            if mode in {'empty', 'outage', 'unsearched'}:
                return AgentTurn(answer=AnswerDraft(insufficient_evidence=True))
            citation = 'invented' if mode == 'fake' else data['data']['id']
            return AgentTurn(answer=AnswerDraft(statements=(AnswerStatement(text='公開合成資料，適用日期待確認。', citation_ids=(citation,)),)))
    service = AgenticRagService(repo, None, Model(), adapter)
    if mode in {'fake', 'revision'}:
        with pytest.raises(RevisionConflict if mode == 'revision' else ExtractionUnavailable):
            service.query(case.id, case.revision, '樹林', True)
        return
    result = service.query(case.id, case.revision, '樹林', True)
    assert result['status'] == ('draft' if mode == 'success' else 'insufficient_evidence')
    assert bool(result['public_sources']) == (mode == 'success')
    assert repo.get_case(case.id) == case and repo.audit(case.id) == audit
    if mode == 'unsearched':
        assert not requests


def test_http_composition_returns_public_sources(tmp_path, monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES', 'false')
    adapter, requests = provider()
    class Model:
        def next_turn(self, context, history, tools):
            if not history:
                return AgentTurn(calls=(ToolCall(id='s', name='search_public_datasets', arguments={'keyword': '樹林'}),))
            if len(history) == 1:
                return AgentTurn(calls=(ToolCall(id='r', name='read_public_dataset', arguments={'dataset_id': ID}),))
            return AgentTurn(answer=AnswerDraft(statements=(AnswerStatement(text='合成公開資料。', citation_ids=(history[-1]['results'][0]['data']['id'],)),)))
    with TestClient(create_app(Settings(data_dir=tmp_path, reference_dir=tmp_path, ai_enabled=False),
                               agent_model=Model(), public_data=adapter)) as client:
        case = client.post('/api/cases', json={'title': '合成', 'valuation_date': '1140901'}).json()['case']
        url = '/api/cases/' + case['id'] + '/agent-evidence'
        body = dict(revision=case['revision'], question='樹林')
        assert client.post(url, json=body).status_code == 400
        assert not requests
        response = client.post(url, json=dict(body, cloud_data_approved=True))
        assert response.status_code == 200
        assert response.json()['public_sources'][0]['dataset_id'] == ID
        assert response.json()['status'] == 'draft'
        assert client.get('/api/cases/' + case['id']).json()['case'] == case
