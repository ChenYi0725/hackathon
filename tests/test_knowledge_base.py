from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.application.ports import ExtractionUnavailable
from app.infrastructure.knowledge_base import BedrockKnowledgeBaseRetriever, S3KnowledgeBasePublisher
from app.infrastructure.aws_rag_runtime import AwsRagRuntime
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.settings import Settings
from app.interfaces.http import create_app
from test_rag import repo, source, query, PAGES, Pdf


class Runtime:
    def __init__(self):
        self.calls=[]; self.results=[]; self.status='IN_PROGRESS'; self.failures=0
    def call(self, service, operation, **kwargs):
        self.calls.append((service,operation,kwargs))
        if operation=='retrieve': return dict(retrievalResults=self.results)
        if operation in {'start_ingestion_job','get_ingestion_job'}:
            return dict(ingestionJob=dict(ingestionJobId='0123456789',status=self.status,
                                         statistics=dict(numberOfDocumentsFailed=self.failures)))
        return {}


def settings(repo):
    return Settings(data_dir=repo.data_dir, rag_backend='bedrock-kb', knowledge_base_id='0123456789',
                    knowledge_base_data_source_id='ABCDEFGHIJ', evidence_bucket='synthetic-evidence')


def prepared(repo):
    saved=source(repo); runtime=Runtime(); config=settings(repo)
    publisher=S3KnowledgeBasePublisher(config,repo,runtime)
    publisher.sync_ruleset(saved['ruleset_id'])
    metadata=next(json.loads(k['Body'])['metadataAttributes'] for _,op,k in runtime.calls
                  if op=='put_object' and k['Key'].endswith('.metadata.json'))
    key=next(k['Key'] for _,op,k in runtime.calls if op=='put_object' and k['Key'].endswith('.txt'))
    runtime.results=[dict(metadata=metadata,content=dict(text=PAGES[0]['text']),score=.92,
                          location=dict(type='S3',s3Location=dict(uri='s3://synthetic-evidence/'+key)))]
    runtime.calls.clear()
    return config,runtime,publisher


def test_publish_retrieve_exact_provenance_and_filters(repo):
    config,runtime,publisher=prepared(repo)
    assert publisher.status()['status']=='in_progress'
    runtime.status='COMPLETE'
    assert publisher.status()['status']=='complete'
    runtime.failures=1
    assert publisher.status()['status']=='failed'
    retriever=BedrockKnowledgeBaseRetriever(config,repo,runtime)
    hit=retriever.retrieve(query())[0]
    assert hit.source.quote==PAGES[0]['text'] and hit.source.start==0
    request=runtime.calls[-1][2]
    filters=request['retrievalConfiguration']['vectorSearchConfiguration']['filter']['andAll']
    assert {'equals':{'key':'ruleset_id','value':query().ruleset_id}} in filters
    assert {'lessThanOrEquals':{'key':'valid_from_day','value':query().valuation_date.toordinal()}} in filters
    before=len(runtime.calls)
    assert retriever.retrieve(query(ruleset_version='future'))==[]
    assert retriever.retrieve(query(valuation_date=date(2026,1,1)))==[]
    assert len(runtime.calls)==before


@pytest.mark.parametrize('change', ['sha','version','date','page','start','quote','uri','score'])
def test_forged_or_inapplicable_aws_result_is_never_cited(repo,change):
    config,runtime,_=prepared(repo)
    result=runtime.results[0]
    if change=='sha':result['metadata']['document_sha256']='fake'
    if change=='version':result['metadata']['ruleset_version']='other'
    if change=='date':result['metadata']['valid_from_day']=1
    if change=='page':result['metadata']['page']=True
    if change=='start':result['metadata']['start']=-1
    if change=='quote':result['content']['text']='模型捏造原文'
    if change=='uri':result['location']['s3Location']['uri']='s3://other/fake'
    if change=='score':result['score']=float('nan')
    assert BedrockKnowledgeBaseRetriever(config,repo,runtime).retrieve(query())==[]


def test_sync_in_progress_and_corrupt_pdf_do_not_upload(repo):
    config,runtime,publisher=prepared(repo)
    with pytest.raises(ExtractionUnavailable,match='正在同步'):publisher.sync_ruleset(query().ruleset_id)
    assert not any(op=='put_object' for _,op,_ in runtime.calls)
    runtime.status='COMPLETE'
    doc=repo.get_document(repo.list_evidence_documents(query().ruleset_id)[0]['document_id'])
    from pathlib import Path
    Path(doc['path']).write_bytes(b'changed')
    with pytest.raises(ExtractionUnavailable,match='指紋'):publisher.sync_ruleset(query().ruleset_id)
    assert not any(op=='put_object' for _,op,_ in runtime.calls)


def test_aws_edge_trimming_preserves_exact_original_span_but_not_internal_changes(repo):
    config,runtime,_=prepared(repo)
    document=repo.list_evidence_documents(query().ruleset_id)[0]
    original='  原文：數值 1 2\n  下一列\n'
    with repo.db() as db:
        db.execute('UPDATE documents SET pages=? WHERE id=?',
                   (json.dumps([dict(page=1,text=original,method='synthetic')]),document['document_id']))
    runtime.results[0]['content']['text']=original.strip()
    hit=BedrockKnowledgeBaseRetriever(config,repo,runtime).retrieve(query())[0]
    assert hit.source.quote==original and hit.source.start==0 and hit.source.end==len(original)
    runtime.results[0]['content']['text']=original.strip().replace('1 2','12')
    assert BedrockKnowledgeBaseRetriever(config,repo,runtime).retrieve(query())==[]


def test_http_consent_and_shared_agent_kb_wiring(tmp_path,monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES','false')
    runtime=Runtime()
    monkeypatch.setattr('app.bootstrap.AwsRagRuntime',lambda _:runtime)
    config=Settings(data_dir=tmp_path,rag_backend='bedrock-kb',knowledge_base_id='0123456789',
                    knowledge_base_data_source_id='ABCDEFGHIJ',evidence_bucket='synthetic-evidence')
    app=create_app(config,pdf=Pdf())
    with TestClient(app) as client:
        case=client.post('/api/cases',json=dict(title='合成',valuation_date='1140901')).json()['case']
        assert client.get('/api/rag/config').json()=={'cloud_retrieval':True}
        endpoint='/api/cases/'+case['id']+'/evidence'
        assert client.post(endpoint,json=dict(revision=case['revision'],question='道路')).status_code==400
        assert not runtime.calls
        endpoint='/api/rulesets/'+case['ruleset_id']+'/evidence-sync'
        assert client.post(endpoint,json={}).status_code==400
        assert client.post(endpoint,json={'cloud_data_approved':'true'}).status_code==422
        assert not runtime.calls
        service=app.state.service
        assert service.rag.retriever is service.rag.agent.retriever
        assert isinstance(service.rag.retriever,BedrockKnowledgeBaseRetriever)


def test_runtime_gate_and_safe_failure(repo):
    from botocore.exceptions import ClientError
    def retrieve(**kwargs):raise ClientError({'Error':{'Code':'AccessDenied','Message':'SECRET'}},'Retrieve')
    transport=BedrockFieldExtractor(settings(repo),repo)
    calls=[];transport.gate.wait=lambda:calls.append('gate')
    runtime=AwsRagRuntime(transport,{'bedrock-agent-runtime':SimpleNamespace(retrieve=retrieve)})
    with pytest.raises(ExtractionUnavailable) as error:runtime.call('bedrock-agent-runtime','retrieve')
    assert 'SECRET' not in str(error.value) and calls==['gate']


def test_cloud_configuration_fails_closed(tmp_path):
    with pytest.raises(ValueError,match='Knowledge Base'):Settings(data_dir=tmp_path,rag_backend='bedrock-kb')
    assert Settings(data_dir=tmp_path).rag_backend=='local'
