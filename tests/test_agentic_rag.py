import json
from datetime import date
import pytest
from fastapi.testclient import TestClient
from app.application.agentic_rag import AgenticRagService
from app.application.agent_contracts import AgentTurn, ToolCall, tool_catalog
from app.application.rag_contracts import AnswerDraft, AnswerStatement
from app.application.ports import ExtractionUnavailable, RevisionConflict
from app.domain.models import Case
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.retrieval import LocalEvidenceRetriever
from app.infrastructure.settings import Settings
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.bedrock_agent import BedrockAgentModel
from app.interfaces.http import create_app


@pytest.fixture
def setup(tmp_path):
    repo=SQLiteReviewRepository(tmp_path);repo.initialize()
    case=repo.save_case(Case(title='合成案件',valuation_date='1140901'),'test',new=True)
    rules=repo.get_rules(case.ruleset_id)
    repo.save_evidence_document(b'%PDF synthetic','合成基準.pdf',[dict(page=1,text='寬度必須核對原文。')],
                                rules,date(2025,1,1),date(2025,12,31))
    return repo,case


def call(id,name,**arguments):
    return ToolCall(id=id,name=name,arguments=arguments)


def finish(citation=None):
    return AgentTurn(answer=AnswerDraft(statements=(AnswerStatement(text='依原文核對。',citation_ids=(citation,)),) if citation else (),insufficient_evidence=not bool(citation)))


class ChoosingAgent:
    def __init__(self):self.histories=[]
    def next_turn(self,context,history,tools):
        self.histories.append(history.copy())
        assert {t['name'] for t in tools}=={'search_evidence','read_source_page','get_rule','review_case'}
        if len(history)==0:return AgentTurn(calls=(call('1','search_evidence',question='unknownxyz'),))
        if len(history)==1:return AgentTurn(calls=(call('2','search_evidence',question='寬度'),call('3','get_rule',rule_id='width')))
        if len(history)==2:
            hit=history[-1]['results'][0]['data']['hits'][0]
            return AgentTurn(calls=(call('4','read_source_page',citation_id=hit['id'],start=0),call('5','review_case')))
        return finish(history[-1]['results'][0]['data']['hit']['id'])


def test_agent_selects_functions_retries_search_reads_source_and_calculates(setup):
    repo,case=setup;model=ChoosingAgent()
    old_audit=repo.audit(case.id)
    service=AgenticRagService(repo,LocalEvidenceRetriever(repo),model)
    result=service.query(case.id,case.revision,'查文件並審查',True)
    assert result['status']=='draft' and len(model.histories)==4
    assert [t['tool'] for t in result['tool_trace']]==['search_evidence','search_evidence','get_rule','read_source_page','review_case']
    assert result['review']['complete'] is False
    assert result['review']['counts']['missing']>0
    assert all(s['citation_ids'][0] in {h['id'] for h in result['hits']} for s in result['statements'])
    assert repo.get_case(case.id)==case and repo.audit(case.id)==old_audit


@pytest.mark.parametrize('name,args', [('run_python',{'code':'danger'}),('review_case',{'code':'danger'}),
    ('read_source_page',{'citation_id':'../../.env'}),('get_rule',{'rule_id':'other-case'}),
    ('search_evidence',{'question':'寬度','ruleset_id':'other'})])
def test_unknown_functions_and_arguments_cannot_escape_scope(setup,name,args):
    repo,case=setup
    class BadAgent:
        def next_turn(self,context,history,tools):
            if not history:return AgentTurn(calls=(ToolCall(id='1',name=name,arguments=args),))
            assert history[0]['results'][0]['status']=='error'
            return finish()
    result=AgenticRagService(repo,LocalEvidenceRetriever(repo),BadAgent()).query(case.id,case.revision,'test',True)
    assert result['status']=='insufficient_evidence'
    assert repo.get_case(case.id)==case


def test_no_consent_or_stale_revision_prevents_model_call(setup):
    repo,case=setup
    service=AgenticRagService(repo,None,None)
    with pytest.raises(ValueError,match='上雲'):service.query(case.id,case.revision,'test')
    with pytest.raises(RevisionConflict):service.query(case.id,0,'test',True)


def test_revision_change_during_model_prevents_tool_execution(setup):
    repo,case=setup
    class Race:
        def next_turn(self,*args):
            repo.save_case(case,'other edit')
            return AgentTurn(calls=(call('1','review_case'),))
    with pytest.raises(RevisionConflict):
        AgenticRagService(repo,None,Race()).query(case.id,case.revision,'test',True)


@pytest.mark.parametrize('mode',['loop','duplicate','budget','fake-citation'])
def test_bounded_loop_and_citations(setup,mode):
    repo,case=setup
    class Loop:
        def next_turn(self,context,history,tools):
            if mode=='fake-citation':return finish('invented')
            calls=tuple(call(str(len(history)*3+i) if mode!='duplicate' else 'same','review_case') for i in range(3 if mode=='budget' else 1))
            return AgentTurn(calls=calls)
    with pytest.raises(ExtractionUnavailable):
        AgenticRagService(repo,None,Loop()).query(case.id,case.revision,'test',True)
    assert repo.get_case(case.id)==case


class NativeClient:
    def __init__(self,stop='tool_use'):self.calls=[];self.stop=stop
    def converse(self,**kwargs):
        self.calls.append(kwargs)
        if len(kwargs['messages'])==1:
            message=dict(role='assistant',content=[dict(toolUse=dict(toolUseId='native1',name='search_evidence',input={'question':'寬度'}))])
            return dict(stopReason=self.stop,output=dict(message=message))
        return dict(stopReason='end_turn',output=dict(message=dict(role='assistant',content=[dict(text='{"statements":[],"insufficient_evidence":true}')])) )


def test_native_converse_tool_protocol_cache_and_gate(setup):
    repo,_=setup;client=NativeClient()
    transport=BedrockFieldExtractor(Settings(data_dir=repo.data_dir),repo,client=client)
    gates=[];transport.gate.wait=lambda:gates.append(True)
    model=BedrockAgentModel(transport)
    first=model.next_turn({'question':'寬度'},[],tool_catalog())
    assert first==model.next_turn({'question':'寬度'},[],tool_catalog())
    history=[dict(continuation=first.continuation,results=[dict(id='native1',status='success',data={'hits':[]})])]
    last=model.next_turn({'question':'寬度'},history,tool_catalog())
    assert last.answer.insufficient_evidence
    assert len(client.calls)==2 and len(gates)==2
    request=client.calls[-1]
    assert request['messages'][1]==first.continuation
    assert request['messages'][2]['content'][0]['toolResult']['toolUseId']=='native1'
    assert 'toolConfig' in request and len(request['toolConfig']['tools'])==4


def test_truncated_native_response_is_rejected(setup):
    repo,_=setup
    transport=BedrockFieldExtractor(Settings(data_dir=repo.data_dir),repo,client=NativeClient('max_tokens'))
    with pytest.raises(ExtractionUnavailable):BedrockAgentModel(transport).next_turn({},[],tool_catalog())


def test_agent_http_is_explicit_and_read_only(tmp_path,monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES','false')
    class ReviewOnly:
        def next_turn(self,context,history,tools):
            return finish() if history else AgentTurn(calls=(call('1','review_case'),))
    with TestClient(create_app(Settings(data_dir=tmp_path,reference_dir=tmp_path,ai_enabled=False),agent_model=ReviewOnly())) as client:
        case=client.post('/api/cases',json=dict(title='合成',valuation_date='1140901')).json()['case']
        url='/api/cases/'+case['id']+'/agent-evidence'
        body=dict(revision=case['revision'],question='審查')
        assert client.post(url,json=body).status_code==400
        result=client.post(url,json=dict(body,cloud_data_approved=True))
        assert result.status_code==200 and result.json()['review']['complete'] is False
        assert client.get('/api/cases/'+case['id']).json()['case']==case


def test_large_review_tool_is_bounded_but_final_result_keeps_all_checks(setup):
    repo,case=setup
    from copy import deepcopy
    rules=repo.get_rules(case.ruleset_id)
    template=rules['rules'][0]
    rules['rules']=[dict(deepcopy(template),id='synthetic_'+str(i),name='合成因素 '+str(i)) for i in range(47)]
    rules=repo.add_rules(rules)
    case=repo.save_case(case.model_copy(update={'ruleset_id':rules['id']}),'synthetic rules')
    class Model:
        def next_turn(self,context,history,tools):
            if not history:return AgentTurn(calls=(call('1','review_case'),))
            response=history[-1]['results'][0]
            assert response['status']=='success'
            data=response['data']
            assert data['checks_truncated'] and data['total_checks']>47
            assert len(data['checks'])==30
            assert len(json.dumps(data,ensure_ascii=False))<24000
            assert data['complete'] is False
            return finish()
    result=AgenticRagService(repo,LocalEvidenceRetriever(repo),Model()).query(case.id,case.revision,'檢核所有因素',True)
    assert len(result['review']['checks'])>47
    assert result['review']['counts']['missing']>=47
