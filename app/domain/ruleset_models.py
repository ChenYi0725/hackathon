"""Structured, executable rulesets produced from confirmed source material."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from app.domain.factor_rules import (
    FactorRule,
    GradingMethod,
)


class RulesetScope(str, Enum):
    REGIONAL = 'regional'
    INDIVIDUAL = 'individual'


@dataclass(frozen=True)
class StructuredFactorRule:
    """Executable factor rule plus source wording needed for confirmation."""

    name: str
    source_page: int
    criteria: tuple[tuple[str, str], ...]
    rule: FactorRule
    group: str = ''

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('因素名稱不可為空白。')
        if isinstance(self.source_page, bool) or not isinstance(self.source_page, int):
            raise ValueError('因素來源頁碼必須為整數。')
        if self.source_page < 1:
            raise ValueError('因素來源頁碼必須從 1 開始。')
        if not isinstance(self.rule, FactorRule):
            raise ValueError('因素必須包含 FactorRule。')


@dataclass(frozen=True)
class StructuredRuleset:
    """One locality/use/scope ruleset; no locality-specific Python is required."""

    id: str
    version: str
    title: str
    locality: str
    land_use: str
    scope: RulesetScope
    factors: tuple[StructuredFactorRule, ...]
    source_name: str

    def __post_init__(self) -> None:
        for field, value in (
            ('ruleset ID', self.id),
            ('ruleset version', self.version),
            ('標題', self.title),
            ('地區', self.locality),
            ('用地類別', self.land_use),
            ('來源名稱', self.source_name),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{field}不可為空白。')
        if not isinstance(self.scope, RulesetScope):
            raise ValueError('ruleset scope 無效。')
        if not self.factors:
            raise ValueError('structured ruleset 至少需要一項因素。')
        ids = [factor.rule.id for factor in self.factors]
        if len(ids) != len(set(ids)):
            raise ValueError('structured ruleset 的因素 ID 不可重複。')

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation with Decimal values as strings."""

        return {
            'id': self.id,
            'version': self.version,
            'title': self.title,
            'locality': self.locality,
            'land_use': self.land_use,
            'scope': self.scope.value,
            'source_name': self.source_name,
            'factors': [
                {
                    'id': factor.rule.id,
                    'name': factor.name,
                    'group': factor.group,
                    'source_page': factor.source_page,
                    'criteria': [
                        {'label': label, 'text': text}
                        for label, text in factor.criteria
                    ],
                    **_factor_rule_dict(factor.rule),
                }
                for factor in self.factors
            ],
        }


def _factor_rule_dict(rule: FactorRule) -> dict[str, Any]:
    result: dict[str, Any] = {
        'input_type': rule.input_type.value,
        'grading_method': rule.grading_method.value,
        'grades': [
            {'index': grade.index, 'label': grade.label} for grade in rule.grades
        ],
        'matrix': (
            None
            if rule.matrix is None
            else [[_decimal_text(cell) for cell in row] for row in rule.matrix]
        ),
    }
    if rule.ranges is not None:
        result['ranges'] = [_range_dict(item) for item in rule.ranges]
        result['allow_gaps'] = rule.allow_gaps
    if rule.category_mapping is not None:
        result['category_mapping'] = dict(rule.category_mapping)
    if rule.grading_method is GradingMethod.BOOLEAN:
        result['true_grade_index'] = rule.true_grade_index
        result['false_grade_index'] = rule.false_grade_index
    if rule.facility_rule is not None:
        facility = rule.facility_rule
        result['facility_rule'] = {
            'nonexistent_grade_index': facility.nonexistent_grade_index,
            'in_section_grade_index': facility.in_section_grade_index,
            'preference': facility.preference.value,
            'allow_gaps': facility.allow_gaps,
            'ranges': [_range_dict(item) for item in facility.ranges],
        }
    return result


def _range_dict(rule) -> dict[str, Any]:
    return {
        'grade_index': rule.grade_index,
        'min_value': None if rule.min_value is None else _decimal_text(rule.min_value),
        'min_inclusive': rule.min_inclusive,
        'max_value': None if rule.max_value is None else _decimal_text(rule.max_value),
        'max_inclusive': rule.max_inclusive,
    }


def _decimal_text(value: Decimal) -> str:
    return format(value, 'f')
