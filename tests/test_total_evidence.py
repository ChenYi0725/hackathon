"""Totals must point to recorded source pages, not template page numbers."""
import csv
import io
import json
import pytest
from fastapi.testclient import TestClient
from app.application.drafts import parse_case
from app.domain.confirmation import invalidate_confirmations
from app.domain.engine import review
from app.domain.models import Case, Evidence
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.settings import Settings
from app.interfaces.exports import export_case
from app.interfaces.http import create_app


@pytest.fixture
def repo(tmp_path):
    repository = SQLiteReviewRepository(tmp_path)
    repository.initialize()
    return repository


def test_parser_and_exports_use_recorded_pages_not_template_positions(repo):
    rules = repo.get_rules('jinshan-commercial-v1')
    pages = [dict(page=1, text='表 4 比較法調查估價表\n合計  0%\n土地正常單價  1000\n試算價格  1000  100%'),
             dict(page=4, text='影響地價區域因素分析明細表\n=(1) 合計  2%')]
    case = parse_case(pages, '合成頁碼', rules)
    case.document_id = repo.save_document(b'%PDF synthetic', 'synthetic.pdf', pages)
    assert case.totals.individual == 0 and case.totals.regional_detail == 2
    assert case.total_evidence['individual'].page == 1
    assert case.total_evidence['regional_detail'].page == 4
    result = review(case, rules)
    checks = {c['id']: c for c in result['checks']}
    assert checks['norm_individual']['page'] == 1
    assert checks['norm_regional_detail']['page'] == 4
    assert checks['trial']['page'] == 1
    assert checks['absolute']['page'] is None
    report = export_case(case, result, rules, 'report', 'synthetic').body.decode()
    assert '原文 p.4' in report and '未記錄來源頁碼' in report
    rows = list(csv.reader(io.StringIO(export_case(case, result, rules, 'csv', 'synthetic').body.decode('utf-8-sig'))))
    assert next(row for row in rows if row[0] == '調整百分率絕對值加總')[5] == ''


def test_legacy_case_load_keeps_values_and_revision_without_inventing_sources(repo):
    case = repo.save_case(Case(title='舊合成案件', totals={'individual': 2}), 'legacy', new=True)
    # Simulate the actual JSON shape written by the previous application version.
    with repo.db() as db:
        row = db.execute('SELECT body FROM cases WHERE id=?', (case.id,)).fetchone()
    old = json.loads(row[0]); old.pop('total_evidence')
    with repo.db() as db:
        db.execute('UPDATE cases SET body=? WHERE id=?', (json.dumps(old), case.id))
    restored = repo.get_case(case.id)
    before = repo.audit(case.id)
    result = review(restored, repo.get_rules(case.ruleset_id))
    assert restored.total_evidence == {} and restored.totals.individual == 2
    assert all(c.get('page') is None for c in result['checks'] if c.get('total_field'))
    assert repo.audit(case.id) == before and restored.revision == case.revision


@pytest.mark.parametrize('change', ['value', 'document', 'remove_document', 'citation'])
def test_changed_total_or_source_requires_confirmation_and_clears_stale_citation(change):
    old = Case(title='合成', document_id='source', totals={'individual': 0}, totals_confirmed=True,
               total_evidence={'individual': Evidence(page=1, quote='合計 0%')})
    proposed = old.model_copy(deep=True)
    if change == 'value': proposed.totals.individual = 2
    if change == 'document': proposed.document_id = 'other'
    if change == 'remove_document': proposed.document_id = None
    if change == 'citation': proposed.total_evidence['individual'].page = 2
    saved = invalidate_confirmations(old, proposed)
    assert not saved.totals_confirmed
    assert bool(saved.total_evidence) == (change == 'citation')
    assert old.total_evidence['individual'].page == 1
    unchanged = invalidate_confirmations(old, old)
    assert unchanged.totals_confirmed and unchanged.total_evidence == old.total_evidence


def test_http_rejects_nonexistent_source_and_json_import_discards_detached_citations(tmp_path, monkeypatch):
    monkeypatch.setenv('SEED_EXAMPLES', 'false')
    with TestClient(create_app(Settings(data_dir=tmp_path, reference_dir=tmp_path, ai_enabled=False))) as client:
        repository = SQLiteReviewRepository(tmp_path)
        document_id = repository.save_document(b'%PDF synthetic', 'synthetic.pdf', [dict(page=1, text='合計 0%')])
        data = dict(title='合成', document_id=document_id, totals={'individual': 0},
                    total_evidence={'individual': dict(page=3, quote='合計 0%')})
        assert client.post('/api/cases', json=data).status_code == 400
        data['total_evidence']['individual']['page'] = 1
        response = client.post('/api/cases', json=data)
        assert response.status_code == 200
        data['document_id'] = None
        imported = client.post('/api/cases', json=data).json()['case']
        assert imported['total_evidence'] == {} and imported['totals']['individual'] == 0


def test_workflow_keeps_each_comparisons_total_source_separate(repo):
    from app.domain.models import Comparison
    from app.domain.workflow import calculate
    case = Case(title='多標的來源', document_id='first', totals={'individual': 0},
                total_evidence={'individual': Evidence(page=1, quote='合計 0%')},
                additional_comparisons=[Comparison(id='second', totals={'individual': 2})])
    rules = repo.get_rules(case.ruleset_id)
    rows = {r['id']: r for r in calculate(case, rules, [])['checks']}
    assert rows['norm_individual']['page'] == 1
    assert rows['norm_individual']['evidence']['document_id'] == 'first'
    assert rows['second:norm_individual']['page'] is None
    case.field_sources['comparisons.second.totals.individual'] = Evidence(document_id='second-doc', page=4, quote='合計 2%')
    rows = {r['id']: r for r in calculate(case, rules, [])['checks']}
    assert rows['second:norm_individual']['page'] == 4
    assert rows['second:norm_individual']['evidence']['document_id'] == 'second-doc'


@pytest.mark.parametrize('secondary', [False, True])
@pytest.mark.parametrize('replace_source', [False, True])
def test_manual_total_edit_drops_old_source_but_cell_adoption_keeps_new_source(secondary, replace_source):
    from app.domain.models import Comparison
    old = Case(title='總計來源', document_id='pdf', document_ids=['pdf', 'xlsx'], totals={'individual': 0},
               additional_comparisons=[Comparison(id='second', totals={'individual': 0})])
    key = ('comparisons.second.' if secondary else '') + 'totals.individual'
    old.field_sources[key] = Evidence(document_id='pdf', page=1, quote='合計 0%')
    proposed = old.model_copy(deep=True)
    target = proposed.additional_comparisons[0] if secondary else proposed
    target.totals.individual = 2
    if replace_source:
        proposed.field_sources[key] = Evidence(document_id='xlsx', sheet='明細', cell='B2', quote='2', method='xlsx-cell')
    saved = invalidate_confirmations(old, proposed)
    assert (key in saved.field_sources) == replace_source
    assert key in old.field_sources
    assert key in invalidate_confirmations(old, old).field_sources
