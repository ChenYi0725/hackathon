"""Generic grading and price-adjustment evaluation driven only by ruleset data."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.domain.decimal_values import as_finite_decimal
from app.domain.factor_rules import (
    AdjustmentMatrix,
    FactorRule,
    FacilityDistanceRule,
    FacilityValue,
    GradeDefinition,
    GradeResult,
    GradingMethod,
    NumericRangeRule,
    validate_adjustment_matrix,
    validate_facility_distance_rule,
    validate_factor_rule,
    validate_grade_definitions,
    validate_numeric_ranges,
)


class ManualEvaluationRequired(ValueError):
    """Raised when a ruleset explicitly requires an externally decided grade."""


def evaluate_numeric_ranges(
    value: Decimal,
    ranges: Sequence[NumericRangeRule],
    grades: Sequence[GradeDefinition],
    *,
    allow_gaps: bool = False,
) -> GradeResult:
    """Evaluate a finite decimal against ruleset-defined intervals."""

    number = as_finite_decimal(value, '分級輸入值')
    grade_definitions = validate_grade_definitions(grades)
    ordered = validate_numeric_ranges(ranges, grade_definitions, allow_gaps=allow_gaps)
    matches = [rule for rule in ordered if _contains(rule, number)]
    if len(matches) != 1:
        raise ValueError('輸入值未能對應唯一數值級距。')
    return _grade_result(matches[0].grade_index, grade_definitions)


def evaluate_category(
    value: str,
    category_mapping: Mapping[str, int],
    grades: Sequence[GradeDefinition],
) -> GradeResult:
    """Evaluate an exact category string using only a ruleset mapping."""

    grade_definitions = validate_grade_definitions(grades)
    if not isinstance(value, str):
        raise ValueError('分類輸入值必須為字串。')
    if not isinstance(category_mapping, Mapping) or not category_mapping:
        raise ValueError('分類對照必須為非空白 mapping。')
    valid_indexes = {grade.index for grade in grade_definitions}
    for category, grade_index in category_mapping.items():
        if not isinstance(category, str) or not category.strip():
            raise ValueError('分類值必須為非空白字串。')
        if (
            isinstance(grade_index, bool)
            or not isinstance(grade_index, int)
            or grade_index not in valid_indexes
        ):
            raise ValueError(f'分類值引用不存在的等級序號：{grade_index!r}。')
    if value not in category_mapping:
        raise ValueError(f'分類值未定義於 ruleset：{value!r}。')
    return _grade_result(category_mapping[value], grade_definitions)


def evaluate_boolean(
    value: bool,
    true_grade_index: int,
    false_grade_index: int,
    grades: Sequence[GradeDefinition],
) -> GradeResult:
    """Evaluate a boolean using ruleset-provided true and false grades."""

    grade_definitions = validate_grade_definitions(grades)
    if not isinstance(value, bool):
        raise ValueError('布林分級輸入必須為 bool。')
    valid_indexes = {grade.index for grade in grade_definitions}
    if any(
        isinstance(index, bool)
        or not isinstance(index, int)
        or index not in valid_indexes
        for index in (true_grade_index, false_grade_index)
    ):
        raise ValueError('布林分級引用不存在的等級序號。')
    return _grade_result(
        true_grade_index if value else false_grade_index,
        grade_definitions,
    )


def evaluate_count(
    count: int,
    ranges: Sequence[NumericRangeRule],
    grades: Sequence[GradeDefinition],
    *,
    allow_gaps: bool = False,
) -> GradeResult:
    """Evaluate a non-negative integer count through generic numeric ranges."""

    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError('計數分級輸入必須為整數。')
    if count < 0:
        raise ValueError('計數分級輸入不得為負數。')
    return evaluate_numeric_ranges(
        Decimal(count), ranges, grades, allow_gaps=allow_gaps
    )


def evaluate_facility_distance(
    value: FacilityValue,
    rule: FacilityDistanceRule,
    grades: Sequence[GradeDefinition],
) -> GradeResult:
    """Evaluate facility states and distance with no facility-specific constants."""

    if not isinstance(value, FacilityValue):
        raise ValueError('設施輸入必須為 FacilityValue。')
    grade_definitions = validate_grade_definitions(grades)
    validate_facility_distance_rule(rule, grade_definitions)
    if not value.exists:
        return _grade_result(rule.nonexistent_grade_index, grade_definitions)
    if value.in_section:
        return _grade_result(rule.in_section_grade_index, grade_definitions)
    assert value.distance_m is not None
    return evaluate_numeric_ranges(
        value.distance_m,
        rule.ranges,
        grade_definitions,
        allow_gaps=rule.allow_gaps,
    )


def calculate_adjustment_rate(
    target_grade: GradeResult,
    benchmark_grade: GradeResult,
    matrix: AdjustmentMatrix,
) -> Decimal:
    """Look up target-row/benchmark-column rate without rounding."""

    if not isinstance(target_grade, GradeResult) or not isinstance(
        benchmark_grade, GradeResult
    ):
        raise ValueError('目標與基準等級都必須為 GradeResult。')
    normalized = validate_adjustment_matrix(matrix)
    size = len(normalized)
    for name, grade in (
        ('目標區段等級', target_grade),
        ('基準區段等級', benchmark_grade),
    ):
        if grade.index > size:
            raise ValueError(f'{name}序號超出修正率矩陣範圍。')
    return normalized[target_grade.index - 1][benchmark_grade.index - 1]


def evaluate_factor(raw_value: Any, rule: FactorRule) -> GradeResult:
    """Dispatch only by grading method; factor ID and locality are opaque data."""

    validate_factor_rule(rule)
    method = rule.grading_method
    if method is GradingMethod.NUMERIC_RANGE:
        assert rule.ranges is not None
        return evaluate_numeric_ranges(
            raw_value, rule.ranges, rule.grades, allow_gaps=rule.allow_gaps
        )
    if method is GradingMethod.CATEGORICAL:
        assert rule.category_mapping is not None
        return evaluate_category(raw_value, rule.category_mapping, rule.grades)
    if method is GradingMethod.BOOLEAN:
        assert rule.true_grade_index is not None
        assert rule.false_grade_index is not None
        return evaluate_boolean(
            raw_value,
            rule.true_grade_index,
            rule.false_grade_index,
            rule.grades,
        )
    if method is GradingMethod.COUNT:
        assert rule.ranges is not None
        return evaluate_count(
            raw_value, rule.ranges, rule.grades, allow_gaps=rule.allow_gaps
        )
    if method is GradingMethod.FACILITY_DISTANCE:
        assert rule.facility_rule is not None
        return evaluate_facility_distance(raw_value, rule.facility_rule, rule.grades)
    if method is GradingMethod.MANUAL:
        raise ManualEvaluationRequired(
            f'因素 {rule.id!r} 需要上游或人工提供已決定的等級。'
        )
    raise ValueError(f'不支援的分級方式：{method!r}。')


def _contains(rule: NumericRangeRule, value: Decimal) -> bool:
    if rule.min_value is not None:
        if value < rule.min_value or (
            value == rule.min_value and not rule.min_inclusive
        ):
            return False
    if rule.max_value is not None:
        if value > rule.max_value or (
            value == rule.max_value and not rule.max_inclusive
        ):
            return False
    return True


def _grade_result(
    grade_index: int, grades: Sequence[GradeDefinition]
) -> GradeResult:
    for grade in grades:
        if grade.index == grade_index:
            return GradeResult(index=grade.index, label=grade.label)
    raise ValueError(f'規則引用不存在的等級序號：{grade_index}。')
