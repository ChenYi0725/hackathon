"""Typed, locality-neutral rules for deterministic factor grading."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeAlias

from app.domain.decimal_values import as_finite_decimal

MatrixCell: TypeAlias = Decimal | int | str
AdjustmentMatrix: TypeAlias = Sequence[Sequence[MatrixCell]]


class FactorInputType(str, Enum):
    NUMERIC = 'numeric'
    CATEGORY = 'category'
    BOOLEAN = 'boolean'
    COUNT = 'count'
    FACILITY = 'facility'
    MANUAL = 'manual'


class GradingMethod(str, Enum):
    NUMERIC_RANGE = 'numeric_range'
    CATEGORICAL = 'categorical'
    BOOLEAN = 'boolean'
    COUNT = 'count'
    FACILITY_DISTANCE = 'facility_distance'
    MANUAL = 'manual'


class DistancePreference(str, Enum):
    CLOSER_IS_BETTER = 'closer_is_better'
    FARTHER_IS_BETTER = 'farther_is_better'


@dataclass(frozen=True)
class GradeDefinition:
    """One 1-based grade position and its ruleset-provided label."""

    index: int
    label: str

    def __post_init__(self) -> None:
        _validate_positive_index(self.index, '等級序號')
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError('等級標籤不可為空白。')


@dataclass(frozen=True)
class GradeResult:
    """The grade chosen by an evaluator; labels are never inferred globally."""

    index: int
    label: str

    def __post_init__(self) -> None:
        _validate_positive_index(self.index, '等級序號')
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError('等級標籤不可為空白。')


@dataclass(frozen=True)
class NumericRangeRule:
    """A grade interval with independently configurable boundary inclusion."""

    grade_index: int
    min_value: Decimal | None = None
    min_inclusive: bool = True
    max_value: Decimal | None = None
    max_inclusive: bool = False

    def __post_init__(self) -> None:
        _validate_positive_index(self.grade_index, '級距等級序號')
        if not isinstance(self.min_inclusive, bool) or not isinstance(
            self.max_inclusive, bool
        ):
            raise ValueError('級距邊界設定必須為布林值。')
        minimum = (
            None
            if self.min_value is None
            else as_finite_decimal(self.min_value, '級距下限')
        )
        maximum = (
            None
            if self.max_value is None
            else as_finite_decimal(self.max_value, '級距上限')
        )
        object.__setattr__(self, 'min_value', minimum)
        object.__setattr__(self, 'max_value', maximum)
        if minimum is not None and maximum is not None:
            if minimum > maximum:
                raise ValueError('級距下限不得大於上限。')
            if minimum == maximum and not (
                self.min_inclusive and self.max_inclusive
            ):
                raise ValueError('相同上下限的級距必須同時包含該邊界。')


@dataclass(frozen=True)
class FacilityValue:
    """Upstream-provided existence, section, and representative-distance data."""

    exists: bool
    in_section: bool
    distance_m: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.exists, bool) or not isinstance(self.in_section, bool):
            raise ValueError('設施有無與是否位於區段內必須為布林值。')
        if not self.exists:
            if self.in_section:
                raise ValueError('設施不存在時不得標記為位於區段內。')
            if self.distance_m is not None:
                raise ValueError('設施不存在時不得填距離。')
            return
        if self.distance_m is None:
            if not self.in_section:
                raise ValueError('區段外的設施必須提供代表距離。')
            return
        distance = as_finite_decimal(self.distance_m, '設施代表距離')
        if distance < 0:
            raise ValueError('設施代表距離不得為負數。')
        object.__setattr__(self, 'distance_m', distance)


@dataclass(frozen=True)
class FacilityDistanceRule:
    """Ruleset data controlling every special state and distance interval."""

    nonexistent_grade_index: int
    in_section_grade_index: int
    ranges: Sequence[NumericRangeRule]
    preference: DistancePreference | str
    allow_gaps: bool = False

    def __post_init__(self) -> None:
        _validate_positive_index(self.nonexistent_grade_index, '設施不存在等級序號')
        _validate_positive_index(self.in_section_grade_index, '區段內等級序號')
        if not isinstance(self.allow_gaps, bool):
            raise ValueError('是否允許級距空隙必須為布林值。')
        try:
            preference = DistancePreference(self.preference)
        except (TypeError, ValueError):
            raise ValueError('設施距離偏好設定無效。') from None
        ranges = _as_range_tuple(self.ranges, '設施距離級距')
        object.__setattr__(self, 'preference', preference)
        object.__setattr__(self, 'ranges', ranges)


@dataclass(frozen=True)
class FactorRule:
    """One executable factor definition supplied by a structured ruleset."""

    id: str
    input_type: FactorInputType | str
    grading_method: GradingMethod | str
    grades: Sequence[GradeDefinition]
    ranges: Sequence[NumericRangeRule] | None = None
    category_mapping: Mapping[str, int] | None = None
    true_grade_index: int | None = None
    false_grade_index: int | None = None
    facility_rule: FacilityDistanceRule | None = None
    matrix: AdjustmentMatrix | None = None
    allow_gaps: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError('因素 ID 不可為空白。')
        if not isinstance(self.allow_gaps, bool):
            raise ValueError('是否允許級距空隙必須為布林值。')
        try:
            input_type = FactorInputType(self.input_type)
        except (TypeError, ValueError):
            raise ValueError('因素輸入型別無效。') from None
        try:
            grading_method = GradingMethod(self.grading_method)
        except (TypeError, ValueError):
            raise ValueError('因素分級方式無效。') from None

        grades = validate_grade_definitions(self.grades)
        ranges = (
            None if self.ranges is None else _as_range_tuple(self.ranges, '數值級距')
        )
        mapping = None
        if self.category_mapping is not None:
            if not isinstance(self.category_mapping, Mapping):
                raise ValueError('分類對照必須為 mapping。')
            mapping = MappingProxyType(dict(self.category_mapping))
        matrix = (
            None
            if self.matrix is None
            else validate_adjustment_matrix(self.matrix, len(grades))
        )

        object.__setattr__(self, 'input_type', input_type)
        object.__setattr__(self, 'grading_method', grading_method)
        object.__setattr__(self, 'grades', grades)
        object.__setattr__(self, 'ranges', ranges)
        object.__setattr__(self, 'category_mapping', mapping)
        object.__setattr__(self, 'matrix', matrix)
        validate_factor_rule(self)


def validate_grade_definitions(
    grades: Sequence[GradeDefinition],
) -> tuple[GradeDefinition, ...]:
    """Validate a ruleset-defined grade scale without fixing its length."""

    if isinstance(grades, (str, bytes)) or not isinstance(grades, Sequence):
        raise ValueError('等級定義必須為序列。')
    result = tuple(grades)
    if not result or any(not isinstance(grade, GradeDefinition) for grade in result):
        raise ValueError('至少需要一個 GradeDefinition。')
    indexes = [grade.index for grade in result]
    expected = list(range(1, len(result) + 1))
    if sorted(indexes) != expected:
        raise ValueError('等級序號必須唯一且連續，從 1 開始。')
    labels = [grade.label for grade in result]
    if len(set(labels)) != len(labels):
        raise ValueError('等級標籤不可重複。')
    return tuple(sorted(result, key=lambda grade: grade.index))


def validate_numeric_ranges(
    ranges: Sequence[NumericRangeRule],
    grades: Sequence[GradeDefinition],
    *,
    allow_gaps: bool = False,
) -> tuple[NumericRangeRule, ...]:
    """Reject unknown grades, overlaps, and disallowed gaps without repair."""

    if not isinstance(allow_gaps, bool):
        raise ValueError('是否允許級距空隙必須為布林值。')
    grade_definitions = validate_grade_definitions(grades)
    result = _as_range_tuple(ranges, '數值級距')
    if not result:
        raise ValueError('數值分級至少需要一個級距。')
    valid_indexes = {grade.index for grade in grade_definitions}
    for rule in result:
        if rule.grade_index not in valid_indexes:
            raise ValueError(f'級距引用不存在的等級序號：{rule.grade_index}。')

    ordered = tuple(sorted(result, key=_range_sort_key))
    for previous, current in zip(ordered, ordered[1:]):
        previous_max = previous.max_value
        current_min = current.min_value
        if previous_max is None or current_min is None:
            raise ValueError('數值級距不可重疊。')
        if previous_max > current_min:
            raise ValueError('數值級距不可重疊。')
        if previous_max == current_min:
            if previous.max_inclusive and current.min_inclusive:
                raise ValueError('數值級距不可在同一邊界重疊。')
            if not previous.max_inclusive and not current.min_inclusive and not allow_gaps:
                raise ValueError('數值級距在共同邊界留有空隙。')
        elif not allow_gaps:
            raise ValueError('數值級距之間不可留有空隙。')
    return ordered


def validate_facility_distance_rule(
    rule: FacilityDistanceRule,
    grades: Sequence[GradeDefinition],
) -> FacilityDistanceRule:
    """Validate facility state grades, distance coverage, and preference order."""

    if not isinstance(rule, FacilityDistanceRule):
        raise ValueError('設施規則必須為 FacilityDistanceRule。')
    grade_definitions = validate_grade_definitions(grades)
    valid_indexes = {grade.index for grade in grade_definitions}
    for grade_index in (
        rule.nonexistent_grade_index,
        rule.in_section_grade_index,
    ):
        if grade_index not in valid_indexes:
            raise ValueError('設施特殊狀態引用不存在的等級序號。')
    ordered = validate_numeric_ranges(
        rule.ranges,
        grade_definitions,
        allow_gaps=rule.allow_gaps,
    )
    indexes = [item.grade_index for item in ordered]
    if rule.preference is DistancePreference.CLOSER_IS_BETTER:
        if indexes != sorted(indexes):
            raise ValueError('距離越近越佳時，距離增加不得得到更佳等級。')
    elif indexes != sorted(indexes, reverse=True):
        raise ValueError('距離越遠越佳時，距離增加不得得到更差等級。')
    return rule


def validate_adjustment_matrix(
    matrix: AdjustmentMatrix,
    grade_count: int | None = None,
) -> tuple[tuple[Decimal, ...], ...]:
    """Return a finite Decimal square matrix, optionally sized to a grade scale."""

    if isinstance(matrix, (str, bytes)) or not isinstance(matrix, Sequence):
        raise ValueError('修正率矩陣必須為二維序列。')
    rows = tuple(matrix)
    if not rows:
        raise ValueError('修正率矩陣不可為空。')
    size = len(rows)
    if grade_count is not None and size != grade_count:
        raise ValueError(f'修正率矩陣尺寸必須符合 {grade_count} 個等級。')
    normalized: list[tuple[Decimal, ...]] = []
    for row_index, row in enumerate(rows):
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
            raise ValueError(f'修正率矩陣第 {row_index + 1} 列必須為序列。')
        cells = tuple(row)
        if len(cells) != size:
            raise ValueError('修正率矩陣必須為非空的正方形矩陣。')
        normalized.append(
            tuple(
                as_finite_decimal(cell, f'修正率矩陣[{row_index + 1}][{column_index + 1}]')
                for column_index, cell in enumerate(cells)
            )
        )
    return tuple(normalized)


def validate_factor_rule(rule: FactorRule) -> FactorRule:
    """Validate that one factor carries exactly the data its method needs."""

    if not isinstance(rule, FactorRule):
        raise ValueError('因素規則必須為 FactorRule。')
    grades = validate_grade_definitions(rule.grades)
    valid_indexes = {grade.index for grade in grades}
    expected_inputs = {
        GradingMethod.NUMERIC_RANGE: FactorInputType.NUMERIC,
        GradingMethod.CATEGORICAL: FactorInputType.CATEGORY,
        GradingMethod.BOOLEAN: FactorInputType.BOOLEAN,
        GradingMethod.COUNT: FactorInputType.COUNT,
        GradingMethod.FACILITY_DISTANCE: FactorInputType.FACILITY,
        GradingMethod.MANUAL: FactorInputType.MANUAL,
    }
    if rule.input_type is not expected_inputs[rule.grading_method]:
        raise ValueError('因素輸入型別與分級方式不相容。')

    if rule.grading_method in (GradingMethod.NUMERIC_RANGE, GradingMethod.COUNT):
        if rule.ranges is None:
            raise ValueError('數值或計數分級必須提供級距。')
        validate_numeric_ranges(rule.ranges, grades, allow_gaps=rule.allow_gaps)
    elif rule.grading_method is GradingMethod.CATEGORICAL:
        if rule.category_mapping is None or not rule.category_mapping:
            raise ValueError('分類分級必須提供非空白對照。')
        for value, grade_index in rule.category_mapping.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError('分類值必須為非空白字串。')
            if (
                isinstance(grade_index, bool)
                or not isinstance(grade_index, int)
                or grade_index not in valid_indexes
            ):
                raise ValueError(f'分類值引用不存在的等級序號：{grade_index!r}。')
    elif rule.grading_method is GradingMethod.BOOLEAN:
        for field, grade_index in (
            ('true_grade_index', rule.true_grade_index),
            ('false_grade_index', rule.false_grade_index),
        ):
            if (
                isinstance(grade_index, bool)
                or not isinstance(grade_index, int)
                or grade_index not in valid_indexes
            ):
                raise ValueError(f'{field} 必須引用已定義等級。')
    elif rule.grading_method is GradingMethod.FACILITY_DISTANCE:
        facility_rule = rule.facility_rule
        if facility_rule is None:
            raise ValueError('設施距離分級必須提供 FacilityDistanceRule。')
        validate_facility_distance_rule(facility_rule, grades)

    if rule.matrix is not None:
        validate_adjustment_matrix(rule.matrix, len(grades))
    return rule


def _validate_positive_index(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f'{field} 必須為從 1 開始的整數。')


def _as_range_tuple(
    ranges: Sequence[NumericRangeRule], field: str
) -> tuple[NumericRangeRule, ...]:
    if isinstance(ranges, (str, bytes)) or not isinstance(ranges, Sequence):
        raise ValueError(f'{field}必須為序列。')
    result = tuple(ranges)
    if any(not isinstance(item, NumericRangeRule) for item in result):
        raise ValueError(f'{field}只能包含 NumericRangeRule。')
    return result


def _range_sort_key(rule: NumericRangeRule) -> tuple[int, Decimal]:
    if rule.min_value is None:
        return (0, Decimal('0'))
    return (1, rule.min_value)
