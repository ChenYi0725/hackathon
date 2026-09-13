import pytest
import ntpc_shulin_api as source
from app.infrastructure.autofill_data import GovernmentFieldData


def test_no_allowed_sources_never_triggers_full_city_download(monkeypatch):
    def fail(*args,**kwargs): raise AssertionError('unexpected network')
    monkeypatch.setattr(source,'fetch_valuation_factors',fail)
    data=GovernmentFieldData()
    assert data.lookup('金山區',[],None)['sources']==[]
    assert data.lookup('金山區',['elementary'],None)['gaps']
    assert data.lookup('金山區',['bus_stops'],None)['gaps']
    with pytest.raises(ValueError):data.lookup('金山區',['https://attacker.invalid'],111)


def test_registered_api_response_is_filtered_and_retains_source_status(monkeypatch):
    calls=[]
    def fetch(locality,**kwargs):
        calls.append((locality,kwargs))
        return dict(fetched_at='2026-09-13',sources=[dict(key='parks',name='合成公園',url='https://data.ntpc.gov.tw/api/datasets/synthetic/json',status='ok',period='現行')],
            factors=[dict(records=[dict(source_key='parks',source_url='https://data.ntpc.gov.tw/api/datasets/synthetic/json',name='合成公園',raw={'secret':'exclude'})])])
    monkeypatch.setattr(source,'fetch_valuation_factors',fetch)
    result=GovernmentFieldData().lookup('新北市金山區',['parks'],None)
    assert calls[0][1]['only_source_keys']==('parks',)
    assert result['sources'][0]['historical_applicability']=='unverified'
    assert 'secret' not in str(result)
    assert result['record_count']==1
