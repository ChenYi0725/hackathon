from app.application.drafts import parse_case
from app.domain.engine import review
from app.domain.rules import default_rules
from app.domain.sample import sample_case
from app.interfaces.exports import export_case
from tests.test_dynamic_case_drafts import imported_ruleset


def test_forms_include_grade_only_fields_and_zero_rate_without_mutation():
    rules = imported_ruleset()
    case = parse_case([{'page': 1, 'text': '測試數值 第一級 第三級 0%'}], '合成', rules)
    before = case.model_dump()
    html = export_case(case, review(case, rules), rules, 'forms', 'synthetic').body.decode()
    assert '等級：第一級' in html and '等級：第三級' in html
    assert '<td>0.0%</td>' in html
    assert '匯入限制與待確認事項' in html
    assert case.model_dump() == before


def test_forms_show_original_and_recomputed_values_separately():
    case = sample_case()
    case.totals.normal_price = 100
    case.totals.time_rate = 2
    case.totals.adjusted_price = None
    case.totals_confirmed = True
    before = case.model_dump()
    rules = default_rules()
    for kind in ('forms', 'report'):
        html = export_case(case, review(case, rules), rules, kind, 'synthetic').body.decode()
        assert '102.0' in html and '待補' in html
    assert case.model_dump() == before


def test_unconfirmed_calculations_remain_explicit_and_export_escapes_warnings():
    case = sample_case()
    case.totals.normal_price = 100
    case.totals.time_rate = 2
    case.totals.adjusted_price = None
    case.totals_confirmed = False
    case.extraction_warnings = ['<script>bad()</script>']
    rules = default_rules()
    html = export_case(case, review(case, rules), rules, 'forms', 'synthetic').body.decode()
    assert '102.0' not in html
    assert '待確認／資料不足' in html
    assert '<script>bad()</script>' not in html and '&lt;script&gt;' in html
