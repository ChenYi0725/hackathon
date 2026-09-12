"""Ruleset-driven grading works unchanged across unrelated rule definitions."""

from decimal import Decimal

import pytest

from app.domain.factor_evaluation import (
    ManualEvaluationRequired,
    calculate_adjustment_rate,
    evaluate_boolean,
    evaluate_category,
    evaluate_count,
    evaluate_facility_distance,
    evaluate_factor,
    evaluate_numeric_ranges,
)
from app.domain.factor_rules import (
    DistancePreference,
    FactorRule,
    FacilityDistanceRule,
    FacilityValue,
    GradeDefinition,
    GradeResult,
    NumericRangeRule,
)

D = Decimal

GRADES_A = tuple(
    GradeDefinition(index=index, label=label)
    for index, label in enumerate(('A-最佳', 'A-中等', 'A-最低'), start=1)
)
RANGES_A = (
    NumericRangeRule(grade_index=1, min_value=D('80')),
    NumericRangeRule(grade_index=2, min_value=D('60'), max_value=D('80')),
    NumericRangeRule(grade_index=3, max_value=D('60')),
)
MATRIX_A = (
    (D('0'), D('5'), D('10')),
    (D('-5'), D('0'), D('5')),
    (D('-10'), D('-5'), D('0')),
)
RULESET_A_FACTOR = FactorRule(
    id='factor-x',
    input_type='numeric',
    grading_method='numeric_range',
    grades=GRADES_A,
    ranges=RANGES_A,
    matrix=MATRIX_A,
)

GRADES_B = tuple(
    GradeDefinition(index=index, label=label)
    for index, label in enumerate(('B-第一', 'B-第二', 'B-第三', 'B-第四'), start=1)
)
RANGES_B = (
    NumericRangeRule(grade_index=1, min_value=D('90')),
    NumericRangeRule(grade_index=2, min_value=D('70'), max_value=D('90')),
    NumericRangeRule(grade_index=3, min_value=D('50'), max_value=D('70')),
    NumericRangeRule(grade_index=4, max_value=D('50')),
)
MATRIX_B = (
    (D('0'), D('2'), D('4'), D('6')),
    (D('-2'), D('0'), D('2'), D('4')),
    (D('-4'), D('-2'), D('0'), D('2')),
    (D('-6'), D('-4'), D('-2'), D('0')),
)
RULESET_B_FACTOR = FactorRule(
    id='factor-x',
    input_type='numeric',
    grading_method='numeric_range',
    grades=GRADES_B,
    ranges=RANGES_B,
    matrix=MATRIX_B,
)


@pytest.mark.parametrize(
    ('rule', 'value', 'expected_index', 'expected_label'),
    [
        (RULESET_A_FACTOR, D('79.999'), 2, 'A-中等'),
        (RULESET_A_FACTOR, D('80'), 1, 'A-最佳'),
        (RULESET_A_FACTOR, D('80.001'), 1, 'A-最佳'),
        (RULESET_A_FACTOR, D('59.999'), 3, 'A-最低'),
        (RULESET_A_FACTOR, D('60'), 2, 'A-中等'),
        (RULESET_A_FACTOR, D('60.001'), 2, 'A-中等'),
        (RULESET_B_FACTOR, D('89.999'), 2, 'B-第二'),
        (RULESET_B_FACTOR, D('90'), 1, 'B-第一'),
        (RULESET_B_FACTOR, D('90.001'), 1, 'B-第一'),
        (RULESET_B_FACTOR, D('69.999'), 3, 'B-第三'),
        (RULESET_B_FACTOR, D('70'), 2, 'B-第二'),
        (RULESET_B_FACTOR, D('70.001'), 2, 'B-第二'),
        (RULESET_B_FACTOR, D('49.999'), 4, 'B-第四'),
        (RULESET_B_FACTOR, D('50'), 3, 'B-第三'),
        (RULESET_B_FACTOR, D('50.001'), 3, 'B-第三'),
    ],
)
def test_same_evaluate_factor_handles_two_rulesets_without_engine_changes(
    rule, value, expected_index, expected_label
):
    assert evaluate_factor(value, rule) == GradeResult(expected_index, expected_label)


def test_same_raw_value_can_grade_differently_under_different_rulesets():
    assert evaluate_factor(D('80'), RULESET_A_FACTOR).index == 1
    assert evaluate_factor(D('80'), RULESET_B_FACTOR).index == 2


def test_ruleset_factor_composes_grade_then_adjustment_lookup():
    target = evaluate_factor(D('80'), RULESET_A_FACTOR)
    benchmark = evaluate_factor(D('59.999'), RULESET_A_FACTOR)
    assert calculate_adjustment_rate(target, benchmark, RULESET_A_FACTOR.matrix) == D('10')
    assert calculate_adjustment_rate(benchmark, target, RULESET_A_FACTOR.matrix) == D('-10')
    assert calculate_adjustment_rate(target, target, RULESET_A_FACTOR.matrix) == D('0')


def test_evaluate_category_uses_exact_ruleset_mapping():
    grades = (
        GradeDefinition(1, '推薦'),
        GradeDefinition(2, '一般'),
        GradeDefinition(3, '不推薦'),
    )
    mapping = {'類型甲': 2, '類型乙': 1, '類型丙': 3}
    assert evaluate_category('類型甲', mapping, grades) == GradeResult(2, '一般')
    with pytest.raises(ValueError, match='未定義'):
        evaluate_category('未列類型', mapping, grades)


@pytest.mark.parametrize(
    ('value', 'expected'),
    [(True, GradeResult(3, '否決')), (False, GradeResult(1, '通過'))],
)
def test_evaluate_boolean_uses_ruleset_indexes(value, expected):
    grades = (
        GradeDefinition(1, '通過'),
        GradeDefinition(2, '待定'),
        GradeDefinition(3, '否決'),
    )
    assert evaluate_boolean(value, 3, 1, grades) == expected


@pytest.mark.parametrize(
    ('count', 'expected_index'),
    [(0, 3), (1, 2), (2, 2), (3, 1), (4, 1)],
)
def test_evaluate_count_reuses_ruleset_ranges(count, expected_index):
    grades = tuple(GradeDefinition(index, str(index)) for index in range(1, 4))
    ranges = (
        NumericRangeRule(1, min_value=D('3')),
        NumericRangeRule(2, min_value=D('1'), max_value=D('3')),
        NumericRangeRule(3, min_value=D('0'), max_value=D('1')),
    )
    assert evaluate_count(count, ranges, grades).index == expected_index


@pytest.mark.parametrize('count', [-1, D('1'), 1.0, True])
def test_evaluate_count_rejects_non_count_values(count):
    with pytest.raises(ValueError):
        evaluate_count(count, RANGES_A, GRADES_A)


FACILITY_GRADES = (
    GradeDefinition(1, '近距級'),
    GradeDefinition(2, '中距級'),
    GradeDefinition(3, '遠距級'),
)
CLOSER_RULE = FacilityDistanceRule(
    nonexistent_grade_index=3,
    in_section_grade_index=1,
    ranges=(
        NumericRangeRule(1, max_value=D('500')),
        NumericRangeRule(2, min_value=D('500'), max_value=D('1000')),
        NumericRangeRule(3, min_value=D('1000')),
    ),
    preference=DistancePreference.CLOSER_IS_BETTER,
)


@pytest.mark.parametrize(
    ('distance', 'expected_index'),
    [
        (D('499.999'), 1),
        (D('500'), 2),
        (D('500.001'), 2),
        (D('999.999'), 2),
        (D('1000'), 3),
        (D('1000.001'), 3),
    ],
)
def test_facility_distance_boundaries_come_from_fixture_rule(distance, expected_index):
    value = FacilityValue(exists=True, in_section=False, distance_m=distance)
    assert evaluate_facility_distance(value, CLOSER_RULE, FACILITY_GRADES).index == expected_index


@pytest.mark.parametrize(
    ('value', 'expected_index'),
    [
        (FacilityValue(exists=False, in_section=False), 3),
        (FacilityValue(exists=True, in_section=True), 1),
        (FacilityValue(exists=True, in_section=True, distance_m=D('9999')), 1),
    ],
)
def test_facility_special_states_are_ruleset_controlled(value, expected_index):
    assert evaluate_facility_distance(value, CLOSER_RULE, FACILITY_GRADES).index == expected_index


def test_farther_is_better_is_also_data_driven():
    rule = FacilityDistanceRule(
        nonexistent_grade_index=1,
        in_section_grade_index=3,
        ranges=(
            NumericRangeRule(3, max_value=D('500')),
            NumericRangeRule(2, min_value=D('500'), max_value=D('1000')),
            NumericRangeRule(1, min_value=D('1000')),
        ),
        preference=DistancePreference.FARTHER_IS_BETTER,
    )
    near = FacilityValue(True, False, D('100'))
    far = FacilityValue(True, False, D('1200'))
    assert evaluate_facility_distance(near, rule, FACILITY_GRADES).index == 3
    assert evaluate_facility_distance(far, rule, FACILITY_GRADES).index == 1
    assert evaluate_facility_distance(FacilityValue(False, False), rule, FACILITY_GRADES).index == 1


@pytest.mark.parametrize(
    'arguments',
    [
        {'exists': False, 'in_section': True},
        {'exists': False, 'in_section': False, 'distance_m': D('0')},
        {'exists': True, 'in_section': False, 'distance_m': None},
        {'exists': True, 'in_section': False, 'distance_m': D('-0.001')},
        {'exists': True, 'in_section': False, 'distance_m': 1.5},
    ],
)
def test_facility_value_rejects_ambiguous_or_invalid_states(arguments):
    with pytest.raises(ValueError):
        FacilityValue(**arguments)


def test_evaluate_factor_dispatches_category_boolean_count_and_facility():
    category_rule = FactorRule(
        id='opaque-1',
        input_type='category',
        grading_method='categorical',
        grades=GRADES_A,
        category_mapping={'任意分類': 2},
    )
    boolean_rule = FactorRule(
        id='opaque-2',
        input_type='boolean',
        grading_method='boolean',
        grades=GRADES_A,
        true_grade_index=1,
        false_grade_index=3,
    )
    count_rule = FactorRule(
        id='opaque-3',
        input_type='count',
        grading_method='count',
        grades=GRADES_A,
        ranges=RANGES_A,
    )
    facility_rule = FactorRule(
        id='opaque-4',
        input_type='facility',
        grading_method='facility_distance',
        grades=FACILITY_GRADES,
        facility_rule=CLOSER_RULE,
    )
    assert evaluate_factor('任意分類', category_rule).index == 2
    assert evaluate_factor(True, boolean_rule).index == 1
    assert evaluate_factor(80, count_rule).index == 1
    assert evaluate_factor(FacilityValue(False, False), facility_rule).index == 3


def test_manual_factor_never_guesses_a_grade():
    rule = FactorRule(
        id='human-decision',
        input_type='manual',
        grading_method='manual',
        grades=GRADES_A,
        matrix=MATRIX_A,
    )
    with pytest.raises(ManualEvaluationRequired, match='需要上游或人工'):
        evaluate_factor('任何原始內容', rule)


@pytest.mark.parametrize('value', [D('NaN'), D('Infinity'), 79.999, True, None])
def test_numeric_evaluation_rejects_non_finite_or_inexact_values(value):
    with pytest.raises(ValueError):
        evaluate_numeric_ranges(value, RANGES_A, GRADES_A)
