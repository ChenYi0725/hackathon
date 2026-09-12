"""Executable rules are rejected rather than silently repaired."""

from decimal import Decimal

import pytest

from app.domain.factor_evaluation import calculate_adjustment_rate
from app.domain.factor_rules import (
    DistancePreference,
    FactorRule,
    FacilityDistanceRule,
    GradeDefinition,
    GradeResult,
    NumericRangeRule,
    validate_adjustment_matrix,
    validate_numeric_ranges,
)

D = Decimal
GRADES = (
    GradeDefinition(1, '一'),
    GradeDefinition(2, '二'),
    GradeDefinition(3, '三'),
)


@pytest.mark.parametrize(
    'ranges',
    [
        (
            NumericRangeRule(1, min_value=D('0'), max_value=D('10'), max_inclusive=True),
            NumericRangeRule(2, min_value=D('10'), max_value=D('20')),
        ),
        (
            NumericRangeRule(1, min_value=D('0'), max_value=D('11')),
            NumericRangeRule(2, min_value=D('10'), max_value=D('20')),
        ),
        (
            NumericRangeRule(1, max_value=None),
            NumericRangeRule(2, min_value=D('10')),
        ),
    ],
)
def test_numeric_range_overlap_is_rejected(ranges):
    with pytest.raises(ValueError, match='重疊'):
        validate_numeric_ranges(ranges, GRADES)


@pytest.mark.parametrize(
    'ranges',
    [
        (
            NumericRangeRule(1, min_value=D('0'), max_value=D('10')),
            NumericRangeRule(2, min_value=D('11'), max_value=D('20')),
        ),
        (
            NumericRangeRule(1, min_value=D('0'), max_value=D('10')),
            NumericRangeRule(
                2,
                min_value=D('10'),
                min_inclusive=False,
                max_value=D('20'),
            ),
        ),
    ],
)
def test_numeric_range_gap_follows_ruleset_policy(ranges):
    with pytest.raises(ValueError, match='空隙'):
        validate_numeric_ranges(ranges, GRADES, allow_gaps=False)
    assert validate_numeric_ranges(ranges, GRADES, allow_gaps=True)


def test_touching_ranges_are_valid_when_exactly_one_side_includes_boundary():
    ranges = (
        NumericRangeRule(1, min_value=D('0'), max_value=D('10')),
        NumericRangeRule(2, min_value=D('10'), max_value=D('20')),
    )
    assert validate_numeric_ranges(ranges, GRADES) == ranges


@pytest.mark.parametrize(
    'kwargs',
    [
        {'grade_index': 1, 'min_value': D('2'), 'max_value': D('1')},
        {'grade_index': 1, 'min_value': D('1'), 'max_value': D('1')},
        {
            'grade_index': 1,
            'min_value': D('1'),
            'min_inclusive': False,
            'max_value': D('1'),
            'max_inclusive': True,
        },
        {'grade_index': 0},
        {'grade_index': True},
    ],
)
def test_invalid_or_empty_range_is_rejected(kwargs):
    with pytest.raises(ValueError):
        NumericRangeRule(**kwargs)


def test_range_grade_index_must_exist():
    with pytest.raises(ValueError, match='不存在'):
        validate_numeric_ranges((NumericRangeRule(4),), GRADES)


@pytest.mark.parametrize(
    'matrix',
    [
        (),
        ((D('0'), D('1')),),
        ((D('0'), D('1')), (D('-1'),)),
        ('01', '10'),
        ((D('0'), D('NaN')), (D('-1'), D('0'))),
        ((D('0'), D('Infinity')), (D('-1'), D('0'))),
        ((D('0'), 1.5), (D('-1'), D('0'))),
        None,
    ],
)
def test_adjustment_matrix_dimension_and_cell_validation(matrix):
    with pytest.raises(ValueError):
        validate_adjustment_matrix(matrix)


@pytest.mark.parametrize('size', [2, 3, 7, 9])
def test_adjustment_matrix_supports_arbitrary_grade_counts(size):
    matrix = tuple(
        tuple(D(column - row) for column in range(size))
        for row in range(size)
    )
    normalized = validate_adjustment_matrix(matrix, grade_count=size)
    assert len(normalized) == size
    assert all(len(row) == size for row in normalized)


def test_adjustment_matrix_direction_and_same_grade():
    matrix = (
        ('0', '3.33', '6.67'),
        ('-3.33', '0', '3.33'),
        ('-6.67', '-3.33', '0'),
    )
    best = GradeResult(1, '最佳')
    worst = GradeResult(3, '最低')
    assert calculate_adjustment_rate(best, worst, matrix) == D('6.67')
    assert calculate_adjustment_rate(worst, best, matrix) == D('-6.67')
    assert calculate_adjustment_rate(best, best, matrix) == D('0')


def test_adjustment_grade_index_must_fit_matrix():
    with pytest.raises(ValueError, match='超出'):
        calculate_adjustment_rate(
            GradeResult(4, '超界'),
            GradeResult(1, '一'),
            ((D('0'), D('1')), (D('-1'), D('0'))),
        )


@pytest.mark.parametrize(
    'kwargs',
    [
        {
            'id': 'bad-category',
            'input_type': 'category',
            'grading_method': 'categorical',
            'grades': GRADES,
            'category_mapping': {'甲': 4},
        },
        {
            'id': 'bad-boolean',
            'input_type': 'boolean',
            'grading_method': 'boolean',
            'grades': GRADES,
            'true_grade_index': 1,
            'false_grade_index': 4,
        },
        {
            'id': 'missing-range',
            'input_type': 'numeric',
            'grading_method': 'numeric_range',
            'grades': GRADES,
        },
        {
            'id': 'type-method-mismatch',
            'input_type': 'boolean',
            'grading_method': 'numeric_range',
            'grades': GRADES,
            'ranges': (NumericRangeRule(1),),
        },
        {
            'id': 'bad-matrix-size',
            'input_type': 'manual',
            'grading_method': 'manual',
            'grades': GRADES,
            'matrix': ((D('0'), D('1')), (D('-1'), D('0'))),
        },
    ],
)
def test_factor_rule_rejects_non_executable_configuration(kwargs):
    with pytest.raises(ValueError):
        FactorRule(**kwargs)


def test_facility_preference_rejects_non_monotonic_grade_order():
    bad_facility_rule = FacilityDistanceRule(
        nonexistent_grade_index=3,
        in_section_grade_index=1,
        ranges=(
            NumericRangeRule(2, max_value=D('10')),
            NumericRangeRule(1, min_value=D('10')),
        ),
        preference=DistancePreference.CLOSER_IS_BETTER,
    )
    with pytest.raises(ValueError, match='距離增加'):
        FactorRule(
            id='facility-x',
            input_type='facility',
            grading_method='facility_distance',
            grades=GRADES,
            facility_rule=bad_facility_rule,
        )


@pytest.mark.parametrize(
    'grades',
    [
        (GradeDefinition(1, '一'), GradeDefinition(3, '三')),
        (GradeDefinition(1, '重複'), GradeDefinition(2, '重複')),
        (),
    ],
)
def test_grade_scale_must_be_nonempty_unique_and_contiguous(grades):
    with pytest.raises(ValueError):
        FactorRule(
            id='grade-scale',
            input_type='manual',
            grading_method='manual',
            grades=grades,
        )
