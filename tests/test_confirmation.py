import pytest
from fastapi.testclient import TestClient
from app.domain.confirmation import CONFIRMATION_CONTEXT, invalidate_confirmations
from app.domain.models import Case, Evidence, Factor, Totals
from app.infrastructure.settings import Settings
from app.interfaces.http import create_app


def confirmed_case():
    return Case(title='合成案件', subject_name='合成比準地', comparable_name='合成比較標的',
                factors=[Factor(id='width', subject='5', comparable='7', entered_rate=0, confirmed=True),
                         Factor(id='depth', subject='23', comparable='25', entered_rate=0, confirmed=True)],
                totals=Totals(individual=0), totals_confirmed=True)


@pytest.mark.parametrize('field,value', [
    ('subject', '6'), ('comparable', '8'), ('entered_rate', 2),
    ('subject_grade', '優'), ('comparable_grade', '劣'), ('exempt', True),
    ('note', '特殊調整理由'), ('evidence', {'page': 2, 'quote': '修訂來源', 'method': 'manual'}),
])
def test_changed_factor_invalidates_only_it_and_totals(field, value):
    old = confirmed_case()
    body = old.model_dump()
    body['factors'][0][field] = value
    proposed = Case.model_validate(body)
    saved = invalidate_confirmations(old, proposed)
    assert not saved.factors[0].confirmed and saved.factors[1].confirmed
    assert not saved.totals_confirmed
    assert proposed.factors[0].confirmed and old.factors[0].confirmed


@pytest.mark.parametrize('field', CONFIRMATION_CONTEXT)
def test_context_changes_invalidate_every_confirmation(field):
    old = confirmed_case()
    proposed = old.model_copy(deep=True)
    value = {'document_ids': ['changed'], 'field_sources': {'totals.individual': Evidence(quote='changed')}}.get(field, 'changed')
    setattr(proposed, field, value)
    saved = invalidate_confirmations(old, proposed)
    assert not any(f.confirmed for f in saved.factors)
    assert not saved.totals_confirmed


def test_total_change_keeps_factor_confirmations():
    old = confirmed_case()
    proposed = old.model_copy(deep=True)
    proposed.totals.individual = 3
    saved = invalidate_confirmations(old, proposed)
    assert all(f.confirmed for f in saved.factors) and not saved.totals_confirmed


def test_metadata_and_factor_reordering_keep_confirmations():
    old = confirmed_case()
    proposed = old.model_copy(deep=True)
    proposed.title = '更名'
    proposed.case_number = 'new-number'
    proposed.notes = '一般備註'
    proposed.factors.reverse()
    saved = invalidate_confirmations(old, proposed)
    assert all(f.confirmed for f in saved.factors) and saved.totals_confirmed


@pytest.mark.parametrize('operation', ['add', 'remove'])
def test_changed_factor_membership_invalidates_totals(operation):
    old = confirmed_case()
    proposed = old.model_copy(deep=True)
    if operation == 'add':
        proposed.factors.append(Factor(id='shape', subject='方整', confirmed=True))
    else:
        proposed.factors.pop()
    saved = invalidate_confirmations(old, proposed)
    assert saved.factors[0].confirmed and not saved.totals_confirmed
    if operation == 'add':
        assert not saved.factors[-1].confirmed


def test_import_drops_asserted_confirmations_but_unchanged_content_can_be_confirmed():
    proposed = confirmed_case()
    saved = invalidate_confirmations(None, proposed)
    assert not any(f.confirmed for f in saved.factors) and not saved.totals_confirmed
    confirmed = invalidate_confirmations(saved, proposed)
    assert all(f.confirmed for f in confirmed.factors) and confirmed.totals_confirmed


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES', 'false')
    with TestClient(create_app(Settings(data_dir=tmp_path, reference_dir=tmp_path, ai_enabled=False))) as client:
        yield client


def test_api_rejects_stale_confirmation_then_allows_confirmation_of_saved_revision(client):
    created = client.post('/api/cases', json=confirmed_case().model_dump()).json()['case']
    assert not any(f['confirmed'] for f in created['factors'])
    for factor in created['factors']:
        factor['confirmed'] = True
    created['totals_confirmed'] = True
    url = '/api/cases/' + created['id']
    confirmed = client.put(url, json=created).json()['case']
    assert all(f['confirmed'] for f in confirmed['factors'])
    confirmed['factors'][0]['subject'] = '6'  # Deliberately retain the stale True flags.
    response = client.put(url, json=confirmed)
    assert response.status_code == 200
    saved = response.json()['case']
    assert not saved['factors'][0]['confirmed'] and saved['factors'][1]['confirmed']
    assert not saved['totals_confirmed']
    assert next(c for c in response.json()['review']['checks'] if c['id'] == 'width')['status'] == 'pending'
    assert client.put(url, json=confirmed).status_code == 409
    assert client.get(url).json()['case'] == saved
    audit_id = client.get(url + '/audit').json()[0]['id']
    assert client.get(url + '/audit/' + str(audit_id)).json() == saved
    saved['factors'][0]['confirmed'] = True
    saved['totals_confirmed'] = True
    again = client.put(url, json=saved).json()['case']
    assert all(f['confirmed'] for f in again['factors']) and again['totals_confirmed']


def test_api_ruleset_switch_invalidates_confirmations(client):
    created = client.post('/api/samples/original').json()['case']
    rules = client.get('/api/rulesets').json()[0]
    new_rules = client.post('/api/rulesets', json=rules).json()
    created['ruleset_id'] = new_rules['id']
    saved = client.put('/api/cases/' + created['id'], json=created).json()['case']
    assert not any(f['confirmed'] for f in saved['factors']) and not saved['totals_confirmed']


def test_suggested_correction_cannot_bypass_invalidation(client):
    created = client.post('/api/samples/errors').json()['case']
    url = '/api/cases/' + created['id']
    result = client.post(url + '/fix/road_width', json={'revision': created['revision']})
    assert result.status_code == 200
    saved = result.json()['case']
    road = next(f for f in saved['factors'] if f['id'] == 'road_width')
    assert road['entered_rate'] == 5 and not road['confirmed']
    assert not saved['totals_confirmed']
