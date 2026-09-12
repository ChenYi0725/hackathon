from copy import deepcopy
from app.bootstrap import build_service
from app.infrastructure.settings import Settings
from scripts.evaluate_agent import specifications, prepare, assess, run
from app.domain.workflow import calculate


def test_fixture_validation_never_calls_cloud(tmp_path):
    report=run(Settings(data_dir=tmp_path,reference_dir=tmp_path,ai_enabled=False))
    assert report['mode']=='fixture-validation' and report['aws_requests']==0
    assert len(report['results'])==6 and all(r['fixture_valid'] for r in report['results'])
    assert 'passed' not in report  # Fixture checks are not model evaluation.


def calculation_fixture(tmp_path):
    service=build_service(Settings(data_dir=tmp_path,reference_dir=tmp_path,ai_enabled=False))
    spec=specifications()[0]
    case,rules,sources=prepare(service,spec)
    result=dict(status='insufficient_evidence',statements=[],hits=[],review=calculate(case,rules,[]),
                tool_trace=[dict(tool='get_rule',status='success'),dict(tool='review_case',status='success')])
    outputs=[dict(status='success',data=dict(rule=rules['rules'][0],ruleset_id=rules['id'],ruleset_version=rules['version']))]
    return spec,result,case,rules,sources,outputs


def test_numeric_gold_rejects_changed_computation(tmp_path):
    spec,result,case,rules,sources,outputs=calculation_fixture(tmp_path)
    assert all(assess(spec,result,case,rules,sources,outputs).values())
    result['review']['computed']['individual']=999
    checks=assess(spec,result,case,rules,sources,outputs)
    assert not checks['golden_numeric_result'] and not checks['review_matches_engine']


def test_missing_tool_and_fabricated_check_citation_fail(tmp_path):
    spec,result,case,rules,sources,outputs=calculation_fixture(tmp_path)
    result['tool_trace']=[]
    result['statements']=[dict(text='偽造引用',citation_ids=['width'])]
    checks=assess(spec,result,case,rules,sources,outputs)
    assert not checks['required_tools'] and not checks['statement_citations'] and not checks['abstained']


def test_missing_value_gold_is_not_zero(tmp_path):
    service=build_service(Settings(data_dir=tmp_path,reference_dir=tmp_path,ai_enabled=False))
    spec=next(s for s in specifications() if s['id']=='missing_data')
    case,rules,sources=prepare(service,spec)
    result=dict(status='insufficient_evidence',statements=[],hits=[],review=calculate(case,rules,[]),
                tool_trace=[dict(tool='review_case',status='success')])
    assert all(assess(spec,result,case,rules,sources,[]).values())
    result['review']['computed']['individual']=0
    assert not assess(spec,result,case,rules,sources,[])['golden_numeric_result']


def test_wrong_version_and_altered_quote_fail(tmp_path):
    from app.application.rag_contracts import EvidenceQuery
    service=build_service(Settings(data_dir=tmp_path,reference_dir=tmp_path,ai_enabled=False))
    spec=next(s for s in specifications() if s['id']=='grounded_answer')
    case,rules,sources=prepare(service,spec)
    hits=service.rag.retriever.retrieve(EvidenceQuery(question='寬度',ruleset_id=rules['id'],ruleset_version=rules['version'],locality=case.locality,land_use=case.land_use,valuation_date='2025-09-01'))
    result=dict(status='draft',hits=[h.model_dump(mode='json') for h in hits],
                statements=[dict(text='有原文',citation_ids=[hits[0].id])],
                tool_trace=[dict(tool=t,status='success') for t in spec['tools']])
    assert all(assess(spec,result,case,rules,sources,[]).values())
    altered=deepcopy(result);altered['hits'][0]['source']['quote']='捏造原文'
    assert not assess(spec,altered,case,rules,sources,[])['source_scope_and_quotes']
    altered=deepcopy(result);altered['hits'][0]['ruleset_version']='old'
    assert not assess(spec,altered,case,rules,sources,[])['source_scope_and_quotes']
