from app.application.drafts import parse_case
from app.application.ruleset_imports import build_review_candidates

from tests.test_ruleset_imports import extraction_result


def imported_ruleset():
    ruleset = build_review_candidates(extraction_result())[0]
    ruleset['id'] = 'confirmed-test-rule'
    ruleset['requires_confirmation'] = False
    return ruleset


def test_question_uses_selected_ruleset_to_extract_locality_address_and_dynamic_row():
    ruleset = imported_ruleset()
    pages = [{
        'page': 1,
        'text': (
            '估價題目\n'
            '比準地：測試市甲區幸福路1號\n'
            '比較標的：測試市甲區和平路2號\n'
            '測試數值 85% 65% 1.25%\n'
        ),
    }]
    case = parse_case(pages, '測試題目', ruleset)
    factor = case.factors[0]
    assert case.locality == '測試市甲區'
    assert case.subject_address == '測試市甲區幸福路1號'
    assert case.comparable_address == '測試市甲區和平路2號'
    assert factor.subject == '85'
    assert factor.comparable == '65'
    assert factor.entered_rate == 1.25
    assert factor.evidence.method == 'ruleset-row-parser'


def test_question_locality_mismatch_is_preserved_for_applicability_review():
    ruleset = imported_ruleset()
    pages = [{
        'page': 1,
        'text': '比準地：另一縣乙區幸福路1號\n測試數值 85% 65% 1.25%',
    }]
    case = parse_case(pages, '不符題目', ruleset)
    assert case.locality == '另一縣乙區'
    assert any('與所選基準' in warning for warning in case.extraction_warnings)


def test_single_survey_percentage_is_not_mistaken_for_an_adjustment_rate():
    ruleset = imported_ruleset()
    pages = [{
        'page': 1,
        'text': '比準地：測試市甲區幸福路1號\n測試數值 85%',
    }]
    case = parse_case(pages, '單欄勘查值', ruleset)
    assert case.factors[0].entered_rate is None


def test_grade_table_row_without_percent_sign_keeps_two_grades_and_rate():
    ruleset = imported_ruleset()
    pages = [{
        'page': 1,
        'text': '比準地：測試市甲區幸福路1號\n測試數值 第一級 第三級 2.5',
    }]
    factor = parse_case(pages, '等級明細', ruleset).factors[0]
    assert (factor.subject_grade, factor.comparable_grade) == ('第一級', '第三級')
    assert factor.entered_rate == 2.5


def test_split_numeric_row_retains_values_and_verbatim_source():
    source = '測試數值\n85%\n65%\n1.25%'
    case = parse_case([{'page': 1, 'text': source}], '跨行題目', imported_ruleset())
    f = case.factors[0]
    assert (f.subject, f.comparable, f.entered_rate) == ('85', '65', 1.25)
    assert f.evidence.quote == source
    assert not f.confirmed


def test_split_grade_row_is_extracted_without_inventing_raw_values():
    source = '測試數值\n第一級\n第三級\n2.5%'
    f = parse_case([{'page': 1, 'text': source}], '跨行等級', imported_ruleset()).factors[0]
    assert (f.subject_grade, f.comparable_grade, f.entered_rate) == ('第一級', '第三級', 2.5)
    assert f.subject is None and f.comparable is None


def test_split_row_does_not_cross_unrelated_text_or_choose_multiple_comparables():
    for source in (
        '測試數值\n地址說明\n85%\n65%\n1.25%',
        '測試數值\n85%\n65%\n55%\n1.25%',
        '測試數值\n85\n65\n55',
    ):
        f = parse_case([{'page': 1, 'text': source}], '不明欄位', imported_ruleset()).factors[0]
        assert f.subject is None and f.comparable is None and f.entered_rate is None


def test_split_row_never_joins_across_pages():
    pages = [{'page': 1, 'text': '測試數值'}, {'page': 2, 'text': '85%\n65%\n1.25%'}]
    f = parse_case(pages, '跨頁', imported_ruleset()).factors[0]
    assert f.subject is None and f.entered_rate is None


def test_multi_comparable_table_stays_unfilled_with_explicit_warning():
    text = '表4 比較法調查估價表\n7 面積 100 200 2% 300 3%\n測試數值 85% 65% 1.25%'
    case = parse_case([{'page': 1, 'text': text}], '多比較標的', imported_ruleset())
    assert all(f.subject is None and f.entered_rate is None for f in case.factors)
    assert any('多筆已填比較標的' in w for w in case.extraction_warnings)
