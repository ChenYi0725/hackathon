from copy import deepcopy
import pytest
from app.application.agent_contracts import AgentTurn, CaseMeasurements, MeasurementInput
from app.application.agentic_rag import AgenticRagService
from app.application.agent_calculations import calculate_measurement
from app.application.ports import RevisionConflict
from app.infrastructure.retrieval import LocalEvidenceRetriever
from app.infrastructure.public_data import GovernmentDataLookup
from test_agentic_rag import setup, call, finish


class PublicData:
    def __init__(self):self.calls=[]
    def catalog(self):return {'sources':[{'key':'park'}], 'gaps':[]}
    def lookup(self, locality, source_key, school_year):
        self.calls.append((locality,source_key,school_year))
        return dict(sources=[dict(id='api1',url='https://data.ntpc.gov.tw/datasets/synthetic',
                    title='合成公園',fetched_at='2025-09-01',locality=locality)], candidates=[dict(name='合成公園')])


def test_agent_routes_sources_missing_fields_api_and_existing_functions(setup):
    repo,case=setup; public=PublicData(); before=repo.audit(case.id)
    class Route:
        def next_turn(self,context,history,tools):
            if len(history)==0:
                return AgentTurn(calls=(call('s','search_evidence',question='寬度'),
                    call('i','inspect_case'),call('l','list_data_sources')))
            citation=history[0]['results'][0]['data']['hits'][0]['id']
            if len(history)==1:
                assert history[0]['results'][1]['data']['field_gaps']
                return AgentTurn(calls=(call('p','query_public_data',source_key='park'),
                    call('m','calculate_measurement',method='average_road_width',side='subject',citation_id=citation),
                    call('f','calculate_factor',rule_id='width')))
            if len(history)==2:return AgentTurn(calls=(call('r','review_case'),))
            return finish('api1')
    result=AgenticRagService(repo,LocalEvidenceRetriever(repo),Route(),public).query(case.id,case.revision,'查規範補欄位並計算',True,
        measurements={'subject':{'opened_road_widths_m':['6','8','10']}})
    assert public.calls==[(case.locality,'park',None)]
    assert all(t['status']=='success' for t in result['tool_trace'])
    assert result['calculations'][0]['result']=='8'
    assert result['calculations'][0]['inputs']=={'opened_road_widths_m':['6','8','10']}
    assert result['calculations'][1]['rule_id']=='width'
    assert result['review'] and result['field_gaps'] and result['api_sources'][0]['id']=='api1'
    assert repo.get_case(case.id)==case and repo.audit(case.id)==before


def test_measurement_functions_use_validated_inputs_and_report_missing():
    data=CaseMeasurements(subject=dict(built_land_area_m2='25',section_total_area_m2='100',coordinates_m=['0','0','3','4']))
    assert calculate_measurement(data.subject,'building_density')['result']=='25.00'
    assert calculate_measurement(data.subject,'straight_line_distance')['result']=='5'
    assert calculate_measurement(data.subject,'average_road_width')['missing_fields']==['opened_road_widths_m']
    for value in (True,'NaN','Infinity','1e100000'):
        with pytest.raises(ValueError):CaseMeasurements(subject=dict(built_land_area_m2=value))
    with pytest.raises(ValueError):MeasurementInput(method='eval',side='subject',citation_id='a')
    with pytest.raises(ValueError):MeasurementInput(method='building_density',side='subject',citation_id='a',value=123)


def test_model_cannot_supply_measurement_values_or_foreign_citation(setup):
    repo,case=setup
    class Bad:
        def next_turn(self,context,history,tools):
            if not history:return AgentTurn(calls=(call('m','calculate_measurement',method='average_road_width',side='subject',citation_id='foreign'),))
            return finish()
    result=AgenticRagService(repo,LocalEvidenceRetriever(repo),Bad()).query(case.id,case.revision,'calculate',True,
        measurements={'subject':{'opened_road_widths_m':['6']}})
    assert result['calculations']==[] and result['tool_trace'][0]['status']=='error'


def test_revision_change_during_public_lookup_is_rejected(setup):
    repo,case=setup
    class Racing(PublicData):
        def lookup(self,*args):
            repo.save_case(case,'concurrent')
            return super().lookup(*args)
    class Agent:
        def next_turn(self,*args):return AgentTurn(calls=(call('p','query_public_data',source_key='park'),))
    with pytest.raises(RevisionConflict):AgenticRagService(repo,None,Agent(),Racing()).query(case.id,case.revision,'查公園',True)


def test_government_adapter_uses_registered_sources_and_preserves_candidate_provenance(monkeypatch):
    import ntpc_shulin_api as module
    adapter=GovernmentDataLookup(); item=next(s for s in module.NTPC_SOURCES if not s['heavy'])
    requests=[]
    def fetch(district,**kwargs):
        requests.append((district,kwargs))
        return dict(status='partial',fetched_at='2026-09-13T00:00:00Z',errors=[{'message':'private upstream detail'}],
                    factors=[{'records':[dict(name='候選',source_url='https://data.ntpc.gov.tw/api/datasets/test/json',
                       source_name='合成來源',longitude=121,latitude=25,raw={'secret':'no'})]*12}])
    monkeypatch.setattr(module,'fetch_valuation_factors',fetch)
    result=adapter.lookup('新北市金山區',item['key'],None)
    assert requests[0][0]=='金山區' and requests[0][1]['only_source_keys']==(item['key'],)
    assert result['truncated'] and len(result['candidates'])==10 and result['record_count']==12
    assert result['candidates'][0]['distance_m'] is None and not result['candidates'][0]['confirmed']
    assert result['sources'][0]['historical_applicability']=='unverified'
    assert result['upstream_error_count']==1 and 'private' not in str(result) and 'secret' not in str(result)
    with pytest.raises(ValueError):adapter.lookup('金山區','https://attacker.example',None)
    with pytest.raises(ValueError):adapter.lookup('臺北市',item['key'],None)
    assert adapter.lookup('金山區','elementary',None)['missing_fields']==['school_year']
    assert len(requests)==1
