"""Versioned review envelope; human dispositions never change technical checks."""
import hashlib
import json
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from app.domain.applicability import valuation_day
from app.domain.engine import review
from app.domain.models import Evidence

ENGINE_VERSION = "core-2"


def factor_source(case, factor, side, prefix=""):
    source = case.field_sources.get(prefix + "factors." + factor.id + "." + side)
    if source is None:
        source = factor.evidence
        # A single Excel cell is not evidence for every value in the factor row.
        if source.cell or source.sheet:
            return Evidence(page=source.page)
    source = source.model_copy(deep=True)
    if not source.document_id and source.method != "manual" and not source.cell:
        source.document_id = case.document_id
    return source


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def calculate_single(case, rules, evidence):
    result = review(case, rules)
    problems = []
    if rules.get('approval_state') != 'published':
        problems.append('適用基準尚未人工發布，僅能預檢。')
    try:
        day = valuation_day(case.valuation_date)
        if not rules.get('valid_from') or not rules.get('valid_to'):
            problems.append('基準缺少已確認適用期間。')
        elif not valuation_day(rules['valid_from']) <= day <= valuation_day(rules['valid_to']):
            problems.append('估價日不在此版本的適用期間。')
    except ValueError:
        problems.append('估價基準日格式缺漏或錯誤。')
    if not case.subject_section or not case.comparable_section:
        problems.append('比準地／比較標的地價區段尚未識別。')
    if problems:
        result['checks'].insert(0, dict(id='governance', title='基準與案件完整性', status='pending',
                                      message=' '.join(problems), actual=None, expected=None))
        # Arithmetic checks remain available; draft normative comparisons cannot pass.
        for row in result['checks']:
            if row['status'] == 'pass' and (row.get('factor_id') or row['id'].startswith('norm_')):
                row.update(status='pending', message=row['message'] + ' 基準適用性尚待確認。')
    for item in evidence:
        result['checks'].append(dict(id='external_' + item['id'], title='外部事實佐證：' + item['factor_id'],
                                    status=item.get('check_status', 'pending'),
                                    message=item['message'], actual=item.get('entered_value'),
                                    expected=item.get('measured_value'), external=item))
    for rule in rules['rules']:
        if rule.get('external_required') and not any(e['factor_id'] == rule['id'] for e in evidence):
            result['checks'].append(dict(id='external_required_' + rule['id'], title='必要外部佐證：' + rule['name'],
                                         status='missing', message='此版本要求外部佐證，目前尚未查證；表內檢核可獨立進行。', actual=None, expected=None))
    for row in result['checks']:
        row['ruleset_id'], row['ruleset_version'] = rules['id'], rules['version']
        row['rule_source'] = rules['source']
        factor = next((f for f in case.factors if f.id == row.get('factor_id')), None)
        if factor:
            row['inputs'] = dict(subject=factor.subject, comparable=factor.comparable,
                                 entered_rate=factor.entered_rate)
            row['evidence'] = factor.evidence.model_dump()
            row['input_sources'] = {side: factor_source(case, factor, side).model_dump()
                                    for side in ('subject', 'comparable', 'entered_rate', 'subject_grade', 'comparable_grade')}
            row['formula'] = 'matrix[classify(subject)][classify(comparable)]'
            row['unit'] = 'percentage_point'
        else:
            row['inputs'] = case.totals.model_dump()
            if row.get('total_field') and 'totals.' + row['total_field'] in case.field_sources:
                row['evidence'] = case.field_sources['totals.' + row['total_field']].model_dump()
            row['formula'] = {
                'cross': 'regional_carried == regional_detail',
                'absolute': 'abs(time_rate) + sum(abs(entered_factor_rates))',
                'adjusted': 'normal_price * (1 + time_rate / 100)',
                'trial': 'adjusted_price * (1 + regional_carried / 100) * (1 + individual / 100)',
                'weight': 'weight == 100',
            }.get(row['id'], 'sum(entered_rates)' if row['id'].startswith('sum_') else 'sum(matrix_rates)' if row['id'].startswith('norm_') else 'preconditions')
            row['calculation_source'] = 'app/domain/engine.py'
            if row['id'].startswith(('sum_', 'norm_')) or row['id'] == 'absolute':
                row['inputs']['factor_rates'] = {f.id: f.entered_rate for f in case.factors}
            if row['id'] in ('adjusted', 'trial'):
                row['rounding'] = dict(mode='ROUND_HALF_UP', quantum='1', currency='TWD/m2')
        row['formula_id'] = 'matrix-lookup-v1' if factor else row['id'] + '-v1'
    result['counts'] = {s: Counter(r['status'] for r in result['checks'])[s]
                        for s in ('pass', 'error', 'pending', 'missing')}
    result['complete'] = not any(result['counts'][s] for s in ('error', 'pending', 'missing'))
    return result


def calculate(case, rules, evidence):
    result = calculate_single(case, rules, [e for e in evidence if e.get('comparison_id', 'primary') == 'primary'])
    if not case.additional_comparisons:
        return result
    result['checks'] = [dict(row, comparison_id='primary') for row in result['checks'] if row['id'] != 'weight']
    comparisons = [dict(id='primary', name=case.comparable_name, computed=result['computed'])]
    weights = [case.totals.weight]
    prices = [case.totals.trial_price]
    confirmed = case.totals_confirmed
    for comparison in case.additional_comparisons:
        view = case.model_copy(update=dict(comparable_name=comparison.name, comparable_section=comparison.section,
                                         factors=comparison.factors, totals=comparison.totals,
                                         totals_confirmed=comparison.totals_confirmed, additional_comparisons=[],
                                         field_sources={key.removeprefix('comparisons.'+comparison.id+'.'):value
                                                        for key,value in case.field_sources.items() if key.startswith('comparisons.'+comparison.id+'.')}))
        sub = calculate_single(view, rules, [e for e in evidence if e.get('comparison_id') == comparison.id])
        comparisons.append(dict(id=comparison.id, name=comparison.name, computed=sub['computed']))
        for row in sub['checks']:
            if row['id'] == 'weight':continue
            result['checks'].append(dict(row, id=comparison.id + ':' + row['id'],
                                         title=(comparison.name or comparison.id) + ' · ' + row['title'], comparison_id=comparison.id))
        weights.append(comparison.totals.weight)
        prices.append(comparison.totals.trial_price)
        confirmed &= comparison.totals_confirmed
        for factor in comparison.factors:
            primary = next((f for f in case.factors if f.id == factor.id), None)
            if primary and primary.confirmed and factor.confirmed and primary.subject != factor.subject:
                result['checks'].append(dict(id=comparison.id+':subject_conflict_'+factor.id, title='跨比較表比準地條件不一致',
                    status='error', message='同一比準地在不同比較表的已確認條件不同，請核對原始書表。',
                    actual=factor.subject, expected=primary.subject, comparison_id=comparison.id,
                    formula_id='subject-consistency-v1', ruleset_id=rules['id'],ruleset_version=rules['version'],rule_source=rules['source']))
    total = sum((Decimal(str(w)) for w in weights), Decimal(0)) if all(w is not None for w in weights) else None
    weight_status = 'pending' if not confirmed or total is None else 'pass' if total == 100 else 'error'
    result['checks'].append(dict(id='weights', title='比較標的權重加總', status=weight_status,
        message='各比較標的原填權重應合計 100%；缺漏不得補零。', actual=float(total) if total is not None else None,
        expected=100, formula_id='weight-sum-v1', ruleset_id=rules['id'], ruleset_version=rules['version'], rule_source=rules['source']))
    aggregate = None
    formula_ready = rules.get('aggregation_formula') == 'weighted-trial-v1' and bool(rules.get('aggregation_source'))
    all_pass = all(r['status'] == 'pass' for r in result['checks'])
    if formula_ready and all_pass and all(p is not None for p in prices):
        aggregate = sum((Decimal(str(p)) * Decimal(str(w)) / 100 for p,w in zip(prices,weights)), Decimal(0)).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
    result['checks'].append(dict(id='aggregate', title='全案加權試算', status='pass' if aggregate is not None else 'pending',
        message='各已驗證試算價格 × 權重後加總，依已發布 weighted-trial-v1 四捨五入至元。' if formula_ready else '本規則未定義並確認多標的加權公式來源，保留待確認。',
        actual=None, expected=float(aggregate) if aggregate is not None else None, formula_id='weighted-trial-v1',
        ruleset_id=rules['id'],ruleset_version=rules['version'],rule_source=rules.get('aggregation_source',rules['source'])))
    result['comparisons'] = comparisons
    result['aggregate'] = str(aggregate) if aggregate is not None else None
    result['counts'] = {s: Counter(r['status'] for r in result['checks'])[s] for s in ('pass','error','pending','missing')}
    result['complete'] = all(r['status'] == 'pass' for r in result['checks'])
    return result
