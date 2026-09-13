import time
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app.application.autofill import AutofillService, marked_choices
from app.application.autofill_contracts import AutofillRequest
from app.application.ports import RevisionConflict
from app.domain.models import Case, Factor, FieldSource
from app.infrastructure.settings import Settings
from app.interfaces.http import create_app


class PublicData:
    def __init__(self): self.calls = []
    def catalog(self):
        return [dict(key='elementary', item='接近學校之程度', name='合成學校來源', school_year_required=True, heavy=False)]
    def lookup(self, locality, keys, year):
        self.calls.append((locality, keys, year))
        return dict(sources=[dict(key='elementary', title='合成學校來源', url='https://stats.moe.gov.tw/files/synthetic', status='ok', fetched_at='2026-09-13',period='合成')], candidates=[], gaps=[], record_count=0)


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES', 'false')
    with TestClient(create_app(Settings(data_dir=tmp_path, ai_enabled=False))) as client:
        service = client.app.state.service
        rules = service.repository.get_rules('jinshan-commercial-v1')
        case = Case(title='純合成選填驗收', subject_name='合成比準地', comparable_name='合成比較地',
            factors=[Factor(id=r['id']) for r in rules['rules']])
        case = service.repository.save_case(case, 'fixture', new=True)
        data = PublicData()
        service.autofill.data = data
        yield client, service, case, data


def patch_map(draft):
    return {(p['factor_id'],p['field']):p['value'] for p in draft['patches']}


def test_checked_options_query_preview_apply_and_export_have_provenance(context):
    client, service, case, data = context
    text = '有無禁止建築 比準地 □有 ☑無 比較標的 ☑有 □無'
    case.document_id = service.repository.save_document(b'%PDF-synthetic','synthetic.pdf',[dict(page=1,text=text)])
    case = service.repository.save_case(case, 'link synthetic source')
    before = service.repository.audit(case.id)
    draft = service.autofill.preview(case.id, AutofillRequest(revision=case.revision, school_year=111))
    values = patch_map(draft)
    assert values['r_ban','subject'] == '無' and values['r_ban','comparable'] == '有'
    assert values['r_ban','subject_grade'] == '無'
    assert ('r_ban','entered_rate') not in values  # New values have not been confirmed.
    assert data.calls == [('新北市金山區',['elementary'],111)]
    assert ('school','subject') not in values and ('school','comparable') not in values
    assert len(draft['coverage']) == len(case.factors)
    assert service.repository.get_case(case.id) == case and service.repository.audit(case.id) == before
    applied = client.post(f'/api/cases/{case.id}/autofill/apply', json={'revision':case.revision,'token':draft['token']})
    assert applied.status_code == 200, applied.text
    saved = service.repository.get_case(case.id)
    f = next(f for f in saved.factors if f.id=='r_ban')
    assert (f.subject,f.comparable) == ('無','有') and not f.confirmed
    assert f.evidence.page == 1 and f.evidence.quote == text
    assert saved.field_sources and saved.revision == case.revision+1
    html = client.get(f'/api/cases/{case.id}/export/forms').text
    assert '自動選填來源' in html and text in html
    assert '☑無' in html and '☑有' in html
    assert len(service.repository.audit(case.id)) == len(before)+1
    assert client.post(f'/api/cases/{case.id}/autofill/apply', json={'revision':case.revision,'token':draft['token']}).status_code == 409


def test_unchecked_ambiguous_and_multiple_comparable_options_are_not_selected():
    rule = {'name':'有無禁止建築','bands':[{'label':'有','values':['有']},{'label':'無','values':['無']}]}
    for text in ['有無禁止建築 比準地 □有 □無 比較標的 □有 □無',
                 '有無禁止建築 比準地 ☑有 ☑無 比較標的 ☑有 ☑無',
                 '有無禁止建築 比準地 ☑有 比較標的2 ☑無']:
        assert marked_choices([dict(page=1,text=text)],rule) == {}
    assert marked_choices([dict(page=1,text='寬度 比準地 10 比較標的 20')],{'name':'寬度','bands':[{'label':'優','values':None}]}) == {}


def test_existing_functions_fill_only_empty_fields_with_input_reference(context):
    _, service, case, _ = context
    request = AutofillRequest(revision=case.revision,query_public_data=False,
        subject={'opened_road_widths_m':['6','8','10'],'source':'合成勘查第1頁'})
    draft = service.autofill.preview(case.id,request)
    assert patch_map(draft)['r_avg_width','subject'] == '8'
    assert any(t['function']=='calculate_average_road_width' for t in draft['trace'])
    assert next(p for p in draft['patches'] if p['field']=='subject')['source']['detail'].startswith('合成勘查第1頁')
    saved = service.autofill.apply(case.id,case.revision,draft['token'])
    draft2 = service.autofill.preview(saved.id,AutofillRequest(revision=saved.revision,query_public_data=False,
        subject={'opened_road_widths_m':['99'],'source':'另一筆資料'}))
    assert ('r_avg_width','subject') not in patch_map(draft2)
    assert next(f for f in service.repository.get_case(case.id).factors if f.id=='r_avg_width').subject=='8'


def test_source_required_for_measurements_and_invalid_values_never_fill(context):
    _, service, case, _ = context
    for observations in [{'opened_road_widths_m':['6']}, {'opened_road_widths_m':[-1],'source':'合成'}]:
        draft = service.autofill.preview(case.id,AutofillRequest(revision=case.revision,query_public_data=False,subject=observations))
        assert ('r_avg_width','subject') not in patch_map(draft)
    for value in [True,'NaN','Infinity','1e1000']:
        with pytest.raises(ValueError): AutofillRequest(revision=case.revision,subject={'built_land_area_m2':value})


def test_confirmed_saved_inputs_can_fill_empty_calculated_result(context):
    _, service, case, _ = context
    case.totals.normal_price=100;case.totals.time_rate=2;case.totals_confirmed=True
    case=service.repository.save_case(case,'confirmed synthetic inputs')
    draft=service.autofill.preview(case.id,AutofillRequest(revision=case.revision,query_public_data=False))
    assert patch_map(draft)[None,'adjusted_price']==102
    saved=service.autofill.apply(case.id,case.revision,draft['token'])
    assert saved.totals.adjusted_price==102 and not saved.totals_confirmed


def test_missing_data_does_not_become_zero_or_false_and_no_network_when_disabled(context):
    _, service, case, data = context
    draft=service.autofill.preview(case.id,AutofillRequest(revision=case.revision,query_public_data=False))
    assert draft['patches']==[] and data.calls==[]
    before=service.repository.audit(case.id)
    assert service.autofill.apply(case.id,case.revision,draft['token'])==case
    assert service.repository.audit(case.id)==before


def test_client_cannot_forge_patch_values_or_provenance(context):
    client, service, case, _ = context
    assert client.post(f'/api/cases/{case.id}/autofill/apply',json={'revision':case.revision,'token':'a'*32,'patches':[{'value':'無'}]}).status_code==422
    case.field_sources=[FieldSource(factor_id='r_ban',field='subject',kind='government-api',value='無',reference='forged')]
    saved=service.save_case(case)
    assert saved['case']['field_sources']==[]


def test_manual_edit_clears_stale_provenance(context):
    _, service, case, _ = context
    draft=service.autofill.preview(case.id,AutofillRequest(revision=case.revision,query_public_data=False,
        subject={'opened_road_widths_m':['6','8','10'],'source':'合成'}))
    saved=service.autofill.apply(case.id,case.revision,draft['token'])
    next(f for f in saved.factors if f.id=='r_avg_width').subject='12'
    result=service.save_case(saved)['case']
    assert not any(s['factor_id']=='r_avg_width' and s['field']=='subject' for s in result['field_sources'])


def test_revision_change_during_lookup_rejects_draft(context):
    _, service, case, data = context
    lookup=data.lookup
    def racing(*args):
        service.repository.save_case(case,'concurrent')
        return lookup(*args)
    data.lookup=racing
    with pytest.raises(RevisionConflict):
        service.autofill.preview(case.id,AutofillRequest(revision=case.revision))


def test_expired_or_foreign_draft_cannot_be_applied(context):
    _, service, case, _ = context
    draft=service.autofill.preview(case.id,AutofillRequest(revision=case.revision,query_public_data=False))
    stored=service.autofill.drafts.get(draft['token']);stored['created_at']=time.time()-901
    service.autofill.drafts.put(draft['token'],stored)
    with pytest.raises(ValueError):service.autofill.apply(case.id,case.revision,draft['token'])
    with pytest.raises(ValueError):service.autofill.apply('foreign',case.revision,draft['token'])


def test_background_job_returns_202_and_result_without_editing_case(context):
    client, service, case, _ = context
    response=client.post(f'/api/cases/{case.id}/autofill/jobs',json={'revision':case.revision,'query_public_data':False})
    assert response.status_code==202
    key=response.json()['job_id']
    for _ in range(100):
        response=client.get(f'/api/cases/{case.id}/autofill/jobs/{key}')
        if response.json()['status']=='done':break
        time.sleep(.01)
    assert response.json()['status']=='done',response.text
    assert service.repository.get_case(case.id)==case
    assert client.get(f'/api/cases/foreign/autofill/jobs/{key}').status_code==404


def test_editing_calculation_input_clears_old_result_provenance(context):
    _, service, case, _ = context
    case.totals.normal_price=100;case.totals.time_rate=2;case.totals_confirmed=True
    case=service.repository.save_case(case,'confirmed synthetic inputs')
    draft=service.autofill.preview(case.id,AutofillRequest(revision=case.revision,query_public_data=False))
    saved=service.autofill.apply(case.id,case.revision,draft['token'])
    assert any(s.field=='adjusted_price' for s in saved.field_sources)
    saved.totals.normal_price=200
    result=service.save_case(saved)['case']
    assert result['totals']['adjusted_price']==102
    assert not any(s['field']=='adjusted_price' for s in result['field_sources'])
