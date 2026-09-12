"""Public domain APIs.

The generic factor API is independent from the legacy
``app.domain.shulin_residential`` compatibility package.
"""

from app.domain.calculations import (
    calculate_average_road_width,
    calculate_building_density,
    calculate_straight_line_distance,
)
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
    FactorInputType,
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
from app.domain.ruleset_models import (
    RulesetScope,
    StructuredFactorRule,
    StructuredRuleset,
)

__all__ = (
    'DistancePreference',
    'FactorInputType',
    'FactorRule',
    'FacilityDistanceRule',
    'FacilityValue',
    'GradeDefinition',
    'GradeResult',
    'GradingMethod',
    'ManualEvaluationRequired',
    'NumericRangeRule',
    'RulesetScope',
    'StructuredFactorRule',
    'StructuredRuleset',
    'calculate_adjustment_rate',
    'calculate_average_road_width',
    'calculate_building_density',
    'calculate_straight_line_distance',
    'evaluate_boolean',
    'evaluate_category',
    'evaluate_count',
    'evaluate_facility_distance',
    'evaluate_factor',
    'evaluate_numeric_ranges',
    'validate_adjustment_matrix',
    'validate_facility_distance_rule',
    'validate_factor_rule',
    'validate_grade_definitions',
    'validate_numeric_ranges',
)
