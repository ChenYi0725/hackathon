"""Paddle layout boxes compile to rules without locality-specific Python."""

from decimal import Decimal

import pytest

from app.domain.factor_evaluation import evaluate_factor
from app.domain.factor_rules import FacilityValue, GradingMethod
from app.domain.ruleset_models import RulesetScope
from app.infrastructure.ruleset_table import (
    PaddleLayoutRulesetExtractor,
    RulesetTableExtractionError,
)

D = Decimal


def ocr_line(text, x, y, width=160, height=18, confidence=0.99):
    return {
        'text': text,
        'bbox': [x, y, x + width, y + height],
        'confidence': confidence,
    }


def vertical(text, x, start_y):
    return [ocr_line(character, x, start_y + offset * 20, width=20) for offset, character in enumerate(text)]


def matrix_lines(matrix, start_y):
    return [
        ocr_line(' '.join(str(value) for value in row), 330, start_y + index * 30, width=280)
        for index, row in enumerate(matrix)
    ]


def criterion_lines(criteria, start_y):
    return [
        ocr_line(f'{label}：{text}', 700, start_y + index * 30, width=270)
        for index, (label, text) in enumerate(criteria)
    ]


def regional_page(
    *,
    locality='測試市甲區',
    first_threshold='80',
    second_threshold='60',
    page_number=1,
):
    title = f'{locality}住宅用地影響地價區域因素評價基準明細表'
    matrix = ((0, 5, 10), (-5, 0, 5), (-10, -5, 0))
    lines = [
        ocr_line(title, 180, 20, width=650),
        ocr_line('主要項目', 120, 80),
        ocr_line('細項', 210, 80),
        ocr_line('價格修正率', 330, 80),
        ocr_line('備註', 700, 80),
        *vertical('數值因素', 215, 165),
        ocr_line('宗地(比', 235, 180, width=20),
        *matrix_lines(matrix, 200),
        *criterion_lines(
            (
                ('優', f'{first_threshold}%以上'),
                ('普通', f'{second_threshold}%以上未滿{first_threshold}%'),
                ('劣', f'未滿{second_threshold}%'),
            ),
            200,
        ),
        *vertical('分類因素', 215, 455),
        *matrix_lines(matrix, 500),
        *criterion_lines(
            (
                ('優', '第一類、第二類'),
                ('普通', '第三類'),
                ('劣', '第四類'),
            ),
            500,
        ),
        *vertical('設施因素', 215, 755),
        *matrix_lines(matrix, 800),
        *criterion_lines(
            (
                ('優', '區段內有設施或距離未滿500m'),
                ('普通', '500m以上未滿1000m'),
                ('劣', '1000m以上或無'),
            ),
            800,
        ),
    ]
    return {
        'page': page_number,
        'width': 1000,
        'height': 1400,
        'method': 'paddleocr',
        'text': '',
        'lines': lines,
    }


def extract(page, locality='測試市甲區'):
    return PaddleLayoutRulesetExtractor().extract(
        [page],
        source_name='合成評價基準明細表.pdf',
        expected_locality=locality,
    )


def test_extracts_numeric_category_and_facility_rules_from_layout():
    result = extract(regional_page())
    assert result.requires_confirmation is True
    assert result.warnings == ()
    assert len(result.rulesets) == 1
    ruleset = result.rulesets[0]
    assert ruleset.locality == '測試市甲區'
    assert ruleset.land_use == '住宅用地'
    assert ruleset.scope is RulesetScope.REGIONAL
    assert [factor.name for factor in ruleset.factors] == ['數值因素', '分類因素', '設施因素']

    numeric, category, facility = (factor.rule for factor in ruleset.factors)
    assert numeric.grading_method is GradingMethod.NUMERIC_RANGE
    assert evaluate_factor(D('79.999'), numeric).index == 2
    assert evaluate_factor(D('80'), numeric).index == 1
    assert category.grading_method is GradingMethod.CATEGORICAL
    assert evaluate_factor('第二類', category).index == 1
    assert facility.grading_method is GradingMethod.FACILITY_DISTANCE
    assert evaluate_factor(FacilityValue(False, False), facility).index == 3
    assert evaluate_factor(FacilityValue(True, True), facility).index == 1
    assert evaluate_factor(FacilityValue(True, False, D('500')), facility).index == 2


def test_factor_name_uses_detail_column_and_excludes_adjacent_subject_header():
    result = extract(regional_page())
    assert result.rulesets[0].factors[0].name == '數值因素'


def test_second_locality_and_thresholds_need_no_parser_change():
    first = extract(regional_page())
    second = extract(
        regional_page(
            locality='另一縣乙區',
            first_threshold='90',
            second_threshold='70',
        ),
        locality='另一縣乙區',
    )
    first_numeric = first.rulesets[0].factors[0].rule
    second_numeric = second.rulesets[0].factors[0].rule
    assert evaluate_factor(D('80'), first_numeric).index == 1
    assert evaluate_factor(D('80'), second_numeric).index == 2
    assert second.rulesets[0].locality == '另一縣乙區'
    assert second.rulesets[0].id != first.rulesets[0].id


def test_other_locality_can_supply_a_different_grade_count_and_matrix():
    matrix = (
        (0, 2, 4, 6),
        (-2, 0, 2, 4),
        (-4, -2, 0, 2),
        (-6, -4, -2, 0),
    )
    page = {
        'page': 1,
        'width': 1000,
        'height': 900,
        'method': 'paddleocr',
        'text': '',
        'lines': [
            ocr_line('不同縣丙區商業用地影響地價區域因素評價基準明細表', 150, 20, width=700),
            ocr_line('細項', 210, 80, width=30),
            *vertical('可變級數因素', 215, 165),
            *matrix_lines(matrix, 200),
            *criterion_lines(
                (
                    ('第一級', '90%以上'),
                    ('第二級', '70%以上未滿90%'),
                    ('第三級', '50%以上未滿70%'),
                    ('第四級', '未滿50%'),
                ),
                200,
            ),
        ],
    }

    result = extract(page, locality='不同縣丙區')
    rule = result.rulesets[0].factors[0].rule
    assert len(rule.grades) == 4
    assert len(rule.matrix) == 4
    assert evaluate_factor(D('80'), rule).index == 2


def test_invalid_facility_numbers_are_manual_without_claiming_state_is_missing():
    page = regional_page()
    last_criterion = next(
        line for line in page['lines'] if line['text'] == '劣：1000m以上或無'
    )
    last_criterion['text'] = '劣：11000m以上或無'

    result = extract(page)
    rule = result.rulesets[0].factors[2].rule
    assert rule.grading_method is GradingMethod.MANUAL
    assert any('未猜測或修復來源數字' in warning for warning in result.warnings)


def test_output_is_json_safe_and_keeps_decimal_strings():
    payload = extract(regional_page()).to_dict()
    factor = payload['rulesets'][0]['factors'][0]
    assert factor['matrix'][0] == ['0', '5', '10']
    assert factor['ranges'][0]['min_value'] == '80'
    assert factor['grading_method'] == 'numeric_range'
    assert payload['requires_confirmation'] is True


def test_same_document_can_return_regional_and_individual_rulesets():
    regional = regional_page(page_number=1)
    individual = regional_page(page_number=2)
    individual['lines'][0]['text'] = '測試市甲區住宅用地影響地價個別因素評價基準明細表'
    result = PaddleLayoutRulesetExtractor().extract(
        [regional, individual],
        source_name='兩種因素.pdf',
        expected_locality='測試市甲區',
    )
    assert {ruleset.scope for ruleset in result.rulesets} == {
        RulesetScope.REGIONAL,
        RulesetScope.INDIVIDUAL,
    }


def test_manual_wording_is_preserved_without_guessing():
    page = regional_page()
    for line in page['lines']:
        if line['text'].startswith(('優：', '普通：', '劣：')) and line['bbox'][1] >= 500:
            label = line['text'].split('：', 1)[0]
            line['text'] = f'{label}：詳備註人工判定'
    result = extract(page)
    manual = result.rulesets[0].factors[1].rule
    assert manual.grading_method is GradingMethod.MANUAL
    assert any('未自動推測' in warning for warning in result.warnings)


def test_common_simplified_ocr_glyphs_are_normalized_without_changing_numbers():
    page = regional_page()
    for line in page['lines']:
        line['text'] = line['text'].replace('未滿', '未满').replace('區段內', '区段内')
    result = extract(page)
    numeric = result.rulesets[0].factors[0].rule
    facility = result.rulesets[0].factors[2].rule
    assert numeric.grading_method is GradingMethod.NUMERIC_RANGE
    assert evaluate_factor(D('60'), numeric).index == 2
    assert facility.grading_method is GradingMethod.FACILITY_DISTANCE
    assert evaluate_factor(FacilityValue(True, False, D('1000')), facility).index == 3


def test_repeated_category_fragments_use_complete_source_rows():
    page = regional_page()
    replacements = {
        '優：第一類、第二類': '優：視野極寬廣、景觀極優美',
        '普通：第三類': '普通：視野、景觀尚可',
        '劣：第四類': '劣：視野、景觀極差',
    }
    for line in page['lines']:
        line['text'] = replacements.get(line['text'], line['text'])
    result = extract(page)
    category = result.rulesets[0].factors[1].rule
    assert category.grading_method is GradingMethod.CATEGORICAL
    assert evaluate_factor('視野、景觀尚可', category).index == 2
    assert any('完整原文' in warning for warning in result.warnings)


def test_criteria_that_only_restate_grade_labels_remain_manual():
    page = regional_page()
    replacements = {
        '優：第一類、第二類': '優：外部判定優',
        '普通：第三類': '普通：外部判定普通',
        '劣：第四類': '劣：外部判定劣',
    }
    for line in page['lines']:
        line['text'] = replacements.get(line['text'], line['text'])
    result = extract(page)
    rule = result.rulesets[0].factors[1].rule
    assert rule.grading_method is GradingMethod.MANUAL
    assert any('外部提供' in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ('mutate', 'message'),
    [
        (lambda page: page.update(lines=[]), 'line boxes'),
        (lambda page: page.update(width=0), '頁面尺寸'),
        (lambda page: page['lines'][0].update(bbox=[0, 0, 0, 0]), 'bbox'),
    ],
)
def test_invalid_paddle_layout_is_rejected(mutate, message):
    page = regional_page()
    mutate(page)
    with pytest.raises(RulesetTableExtractionError, match=message):
        extract(page)


def test_title_must_match_user_supplied_locality():
    with pytest.raises(RulesetTableExtractionError, match='不屬於輸入地區'):
        extract(regional_page(), locality='錯誤市丙區')


def test_matrix_with_missing_ocr_cell_is_not_repaired():
    page = regional_page()
    first_matrix_row = next(line for line in page['lines'] if line['text'] == '0 5 10')
    first_matrix_row['text'] = '0 5'
    with pytest.raises(RulesetTableExtractionError, match='等級標籤|完整的修正率矩陣'):
        extract(page)


def test_note_superscript_number_is_not_a_matrix_cell():
    page = regional_page()
    for line in page['lines']:
        if line['text'].startswith(('優：', '普通：', '劣：')):
            line['bbox'][0] = 620
    # Separate text-layer superscripts can sit inside the broad matrix search area.
    page['lines'].append(ocr_line('2', 660, 202, width=5, height=8))
    result = extract(page)
    assert len(result.rulesets[0].factors) == 3
    assert result.rulesets[0].factors[0].rule.matrix[0] == (D('0'), D('5'), D('10'))


def test_wrapped_criterion_above_centered_label_belongs_to_that_grade():
    page = regional_page()
    page['lines'] = [line for line in page['lines']
                     if line['text'] not in {'優：第一類、第二類', '普通：第三類', '劣：第四類'}]
    page['lines'].extend([
        ocr_line('優：第一類', 700, 500),
        ocr_line('普通：', 700, 535, width=45),
        ocr_line('跨行條件上半', 780, 525, width=160, height=10),
        ocr_line('跨行條件下半', 780, 540, width=160, height=10),
        ocr_line('劣：第四類', 700, 570),
    ])
    result = extract(page)
    criteria = dict(result.rulesets[0].factors[1].criteria)
    assert criteria['優'] == '第一類'
    assert criteria['普通'] == '跨行條件上半跨行條件下半'


def test_title_over_detail_column_is_not_part_of_factor_name():
    page = regional_page()
    page['lines'][0]['bbox'] = [210, 20, 850, 140]
    assert extract(page).rulesets[0].factors[0].name == '數值因素'
