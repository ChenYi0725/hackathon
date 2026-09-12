import json
from datetime import date
import pytest
from fastapi.testclient import TestClient
from app.application.ports import ExtractionUnavailable, RevisionConflict
from app.application.rag import RagService
from app.application.rag_contracts import EvidenceQuery, AnswerDraft, AnswerStatement
from app.domain.applicability import valuation_day
from app.domain.models import Case
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.retrieval import LocalEvidenceRetriever
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.bedrock_rag import BedrockEvidenceAnswerer
from app.infrastructure.settings import Settings
from app.interfaces.http import create_app

PAGES = [dict(page=1, text='合成測試基準：寬度條件須核對原文。\n面前道路寬度應依文件級距檢核。',
              method='synthetic', width=600, height=800,
              lines=[dict(text='寬度條件須核對原文', bbox=[10,20,300,40])])]


class Pdf:
    def read(self, data):
        assert data.startswith(b'%PDF')
        return PAGES


class Answerer:
    def __init__(self): self.calls = []
    def answer(self, question, hits):
        self.calls.append((question, hits))
        return AnswerDraft(statements=(AnswerStatement(text='須核對原文。', citation_ids=(hits[0].id,)),))


@pytest.fixture
def repo(tmp_path):
    repository = SQLiteReviewRepository(tmp_path)
    repository.initialize()
    return repository


def source(repo, **updates):
    rules = dict(repo.get_rules('jinshan-commercial-v1'), **updates)
    return repo.save_evidence_document(b'%PDF synthetic', '合成基準.pdf', PAGES, rules,
                                      date(2025,1,1), date(2025,12,31))


def query(**updates):
    return EvidenceQuery(**dict(dict(question='面前道路寬度', ruleset_id='jinshan-commercial-v1',
        ruleset_version='1.0', locality='新北市金山區', land_use='商業用地', valuation_date=date(2025,9,1)), **updates))


def test_exact_scope_before_ranking_and_provenance(repo):
    correct = source(repo)
    source(repo, id='different-version')
    source(repo, version='future')
    source(repo, locality='另一地區')
    source(repo, land_use='住宅用地')
    hits = LocalEvidenceRetriever(repo).retrieve(query(ruleset_version=repo.get_rules('jinshan-commercial-v1')['version']))
    assert len(hits) == 1
    hit = hits[0]
    assert hit.source.document_id == correct['document_id']
    assert hit.source.document_sha256 == correct['sha256']
    assert hit.source.quote == PAGES[0]['text']
    assert hit.source.bbox == (10,20,300,40)
    assert hit.source.page_width == 600
    assert hit.source.quote == PAGES[0]['text'][hit.source.start:hit.source.end]
    assert LocalEvidenceRetriever(repo).retrieve(query(valuation_date=date(2026,1,1))) == []
    assert LocalEvidenceRetriever(repo).retrieve(query(question='xyzunknown')) == []


def test_boundaries_and_chunk_identity(repo):
    rules = repo.get_rules('jinshan-commercial-v1')
    pages = [dict(page=1, text='寬度原文。' * 400, method='synthetic')]
    repo.save_evidence_document(b'%PDF long', '長文件.pdf', pages, rules, date(2025,1,1), date(2025,12,31))
    retriever = LocalEvidenceRetriever(repo)
    for day in (date(2025,1,1), date(2025,12,31)):
        q = query(ruleset_version=rules['version'], valuation_date=day, limit=2)
        hits = retriever.retrieve(q)
        assert len(hits) == 2 and len({h.id for h in hits}) == 2
        for h in hits:
            assert h.source.quote == pages[0]['text'][h.source.start:h.source.end]
            assert h.source.bbox is None
        assert hits == retriever.retrieve(q)


@pytest.mark.parametrize('raw,expected', [('1140901',date(2025,9,1)), ('2025-09-01',date(2025,9,1))])
def test_date_formats(raw, expected):
    assert valuation_day(raw) == expected


@pytest.mark.parametrize('raw', ['', '今天', '1140230', '2025-13-01'])
def test_unknown_dates_are_not_guessed(raw):
    with pytest.raises(ValueError): valuation_day(raw)


def test_query_is_read_only_and_consent_is_required(repo):
    source(repo)
    case = repo.save_case(Case(title='合成', valuation_date='1140901'), 'test', new=True)
    answerer = Answerer()
    service = RagService(repo, Pdf(), LocalEvidenceRetriever(repo), answerer)
    original = repo.audit(case.id)
    result = service.query(case.id, case.revision, '寬度')
    assert result['status'] == 'sources' and not answerer.calls
    with pytest.raises(ValueError, match='上雲'):
        service.query(case.id, case.revision, '寬度', generate=True)
    result = service.query(case.id, case.revision, '寬度', generate=True, cloud_data_approved=True)
    assert result['status'] == 'draft' and len(answerer.calls) == 1
    result = service.query(case.id, case.revision, 'unknownxyz', generate=True, cloud_data_approved=True)
    assert result['status'] == 'no_evidence' and len(answerer.calls) == 1
    assert repo.get_case(case.id) == case and repo.audit(case.id) == original


def test_invalid_scope_and_ids_do_not_retrieve(repo):
    case = repo.save_case(Case(title='合成', valuation_date='1140901', land_use='住宅用地'), 'test', new=True)
    service = RagService(repo, Pdf(), None, Answerer())
    with pytest.raises(ValueError, match='適用性'): service.query(case.id, case.revision, '寬度')
    case.land_use = '商業用地'
    case = repo.save_case(case, 'test')
    with pytest.raises(ValueError, match='因素'): service.query(case.id, case.revision, '寬度', rule_ids=('fake',))


def test_revision_conflict_after_model_call(repo):
    source(repo)
    case = repo.save_case(Case(title='合成', valuation_date='1140901'), 'test', new=True)
    class ConcurrentAnswerer(Answerer):
        def answer(self, question, hits):
            repo.save_case(case, 'concurrent update')
            return super().answer(question, hits)
    service = RagService(repo, Pdf(), LocalEvidenceRetriever(repo), ConcurrentAnswerer())
    with pytest.raises(RevisionConflict):
        service.query(case.id, case.revision, '寬度', generate=True, cloud_data_approved=True)
    with pytest.raises(RevisionConflict): service.query(case.id, case.revision, '寬度')


def test_service_rejects_unknown_model_citation(repo):
    source(repo)
    case = repo.save_case(Case(title='合成', valuation_date='1140901'), 'test', new=True)
    class BadAnswerer:
        def answer(self, question, hits):
            return AnswerDraft(statements=(AnswerStatement(text='猜測', citation_ids=('fake',)),))
    with pytest.raises(ExtractionUnavailable):
        RagService(repo, Pdf(), LocalEvidenceRetriever(repo), BadAnswerer()).query(
            case.id, case.revision, '寬度', generate=True, cloud_data_approved=True)


class Client:
    def __init__(self, bad=False, stop='end_turn'):
        self.calls=[]; self.bad=bad; self.stop=stop
    def converse(self, **kwargs):
        self.calls.append(kwargs)
        evidence=json.loads(kwargs['messages'][0]['content'][0]['text'])['evidence']
        body=dict(statements=[dict(text='須核對原文。',citation_ids=['fake' if self.bad else evidence[0]['id']])])
        return dict(stopReason=self.stop, output=dict(message=dict(content=[dict(text=json.dumps(body))])))


def test_bedrock_uses_context_and_shared_cache(repo):
    source(repo)
    hits = LocalEvidenceRetriever(repo).retrieve(query(ruleset_version=repo.get_rules('jinshan-commercial-v1')['version']))
    client = Client()
    transport = BedrockFieldExtractor(Settings(data_dir=repo.data_dir), repo, client=client)
    answerer = BedrockEvidenceAnswerer(transport)
    assert answerer.answer('寬度',hits) == answerer.answer('寬度',hits)
    assert len(client.calls) == 1
    assert '不計算' in client.calls[0]['system'][0]['text']
    assert PAGES[0]['text'] in client.calls[0]['messages'][0]['content'][0]['text'].replace('\\n','\n')
    with repo.db() as c: assert c.execute('SELECT * FROM request_gate').fetchone()


@pytest.mark.parametrize('bad,stop', [(True,'end_turn'),(False,'max_tokens')])
def test_bad_bedrock_output_is_not_cached(repo, bad, stop):
    source(repo)
    hits = LocalEvidenceRetriever(repo).retrieve(query(ruleset_version=repo.get_rules('jinshan-commercial-v1')['version']))
    transport = BedrockFieldExtractor(Settings(data_dir=repo.data_dir), repo, client=Client(bad,stop))
    with pytest.raises(ExtractionUnavailable): BedrockEvidenceAnswerer(transport).answer('寬度',hits)
    with repo.db() as c: assert c.execute('SELECT COUNT(*) FROM extraction_cache').fetchone()[0] == 0


def test_disabled_bedrock_does_not_call_client(repo):
    client = Client()
    transport = BedrockFieldExtractor(Settings(data_dir=repo.data_dir, ai_enabled=False), repo, client=client)
    with pytest.raises(ExtractionUnavailable): BedrockEvidenceAnswerer(transport).answer('寬度',[])
    assert not client.calls


def test_api_upload_query_validation_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES','false')
    settings = Settings(data_dir=tmp_path, reference_dir=tmp_path, ai_enabled=False)
    with TestClient(create_app(settings,pdf=Pdf(),answerer=Answerer())) as client:
        case=client.post('/api/cases',json=dict(title='合成案件',valuation_date='1140901')).json()['case']
        url='/api/rulesets/'+case['ruleset_id']+'/evidence-documents'
        upload=client.post(url+'?valid_from=2025-01-01&valid_to=2025-12-31',content=b'%PDF synthetic')
        assert upload.status_code == 200, upload.text
        saved=upload.json()
        assert client.get('/api/documents/'+saved['document_id']+'/file').content == b'%PDF synthetic'
        assert len(client.get(url).json()) == 1
        request=dict(revision=case['revision'],question='寬度')
        result=client.post('/api/cases/'+case['id']+'/evidence',json=request)
        assert result.status_code == 200 and result.json()['status'] == 'sources'
        assert client.post('/api/cases/'+case['id']+'/evidence',json=dict(request,generate=True)).status_code == 400
        assert client.post('/api/cases/'+case['id']+'/evidence',json=dict(request,question='')).status_code == 422
        assert client.post(url+'?valid_from=2026-01-01&valid_to=2025-01-01',content=b'%PDF').status_code == 422
    with TestClient(create_app(settings,pdf=Pdf(),answerer=Answerer())) as client:
        assert len(client.get(url).json()) == 1
        assert client.post('/api/cases/'+case['id']+'/evidence',json=request).json()['status'] == 'sources'


def test_insufficient_model_evidence_discards_statements(repo):
    source(repo)
    case = repo.save_case(Case(title='合成',valuation_date='1140901'), 'test', new=True)
    class Insufficient(Answerer):
        def answer(self, question, hits):
            return super().answer(question, hits).model_copy(update={'insufficient_evidence': True})
    result = RagService(repo, Pdf(), LocalEvidenceRetriever(repo), Insufficient()).query(
        case.id, case.revision, '寬度', generate=True, cloud_data_approved=True)
    assert result['status'] == 'insufficient_evidence' and result['statements'] == []


def test_rag_transport_retries_share_gate_and_cache_is_question_scoped(repo):
    from botocore.exceptions import ClientError
    source(repo)
    hits=LocalEvidenceRetriever(repo).retrieve(query())
    class RetryClient(Client):
        attempts=0
        def converse(self, **kwargs):
            self.attempts+=1
            if self.attempts==1:
                raise ClientError({'Error':{'Code':'ThrottlingException','Message':'secret'}},'Converse')
            return super().converse(**kwargs)
    client=RetryClient()
    transport=BedrockFieldExtractor(Settings(data_dir=repo.data_dir),repo,client=client,sleep=lambda _: None)
    gates=[]
    transport.gate.wait=lambda: gates.append(True)
    answerer=BedrockEvidenceAnswerer(transport)
    answerer.answer('寬度',hits)
    answerer.answer('寬度',hits)
    answerer.answer('另一個寬度問題',hits)
    assert client.attempts==3 and len(gates)==3


def test_reinitialize_preserves_cases_and_sources(repo):
    item=source(repo)
    case=repo.save_case(Case(title='保存案件'), 'test', new=True)
    history=repo.audit(case.id)
    repo.initialize()
    assert repo.get_case(case.id)==case and repo.audit(case.id)==history
    assert repo.list_evidence_documents(case.ruleset_id)[0]['document_id']==item['document_id']


def test_factor_filter_uses_only_declared_source_page(repo):
    rules=repo.get_rules('jinshan-commercial-v1')
    factor=next(r for r in rules['rules'] if r['id']=='width')
    pages=[dict(page=factor['source_page'],text='寬度的合成正確頁面'),dict(page=199,text='寬度 寬度 寬度 錯誤頁面')]
    repo.save_evidence_document(b'%PDF two-pages','因素.pdf',pages,rules,date(2025,1,1),date(2025,12,31))
    hits=LocalEvidenceRetriever(repo).retrieve(query(rule_ids=('width',)))
    assert len(hits)==1 and hits[0].source.page==factor['source_page']
