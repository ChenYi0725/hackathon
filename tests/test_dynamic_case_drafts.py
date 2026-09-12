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
