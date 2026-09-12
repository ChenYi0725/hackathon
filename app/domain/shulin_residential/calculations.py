"""Arithmetic that 表3 地價區段勘查表 itself defines.

Only formulas printed in the handbook are implemented. Results are returned
unrounded and unclamped; the display layer decides presentation, and callers
feeding these values into the Decimal-based totals in `app/domain/engine.py`
should convert with `Decimal(str(value))` as that module already does.
"""
import math
from collections.abc import Sequence

from app.domain.shulin_residential.validation import (
    require_non_negative,
    require_positive,
)


def calculate_average_road_width(opened_road_widths_m: Sequence[float]) -> float:
    """區段內道路平均寬度 = Σ已開闢道路寬度 ÷ 已開闢道路條數。

    Only roads that are already opened (已開闢) belong in the input; planned but
    unopened roads are excluded by the caller.

    Args:
        opened_road_widths_m: Width of each opened road, in metres.

    Returns:
        The mean width in metres, unrounded.

    Raises:
        ValueError: If the sequence is empty (never divides by zero) or any
            width is negative, non-numeric or non-finite.
    """
    if isinstance(opened_road_widths_m, (str, bytes)) or not isinstance(
        opened_road_widths_m, Sequence
    ):
        raise ValueError('已開闢道路寬度必須為數值序列。')
    widths = list(opened_road_widths_m)
    if not widths:
        raise ValueError('已開闢道路條數為 0，無法計算平均寬度。')
    total = sum(require_non_negative(w, f'已開闢道路寬度[{i}]') for i, w in enumerate(widths))
    return total / len(widths)


def calculate_building_density(built_land_area_m2: float, section_total_area_m2: float) -> float:
    """建築密度 = 已建築使用土地面積 ÷ 區段總面積 × 100。

    This is a 表3 record field for the Shulin ordinary-residential case, not one
    of its regional-factor adjustment items.

    Args:
        built_land_area_m2: Already-built land area, in square metres.
        section_total_area_m2: Total section area, in square metres.

    Returns:
        The density as a percentage, unrounded.

    Raises:
        ValueError: If the built area is negative, the section area is not
            greater than zero, or the built area exceeds the section area. The
            excess case is rejected rather than clamped.
    """
    built = require_non_negative(built_land_area_m2, '已建築使用土地面積')
    total = require_positive(section_total_area_m2, '區段總面積')
    if built > total:
        raise ValueError('已建築使用土地面積不得大於區段總面積。')
    return built / total * 100


def calculate_straight_line_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Straight-line distance between two points on a metre plane.

    Provided because 接近交流道之程度 is the item the schedule states is measured
    as a straight-line distance. The handbook does not prescribe a measuring
    method for the other facility items, so do not apply this helper to them
    without a documented basis.

    Args:
        x1: First point's X coordinate, in metres.
        y1: First point's Y coordinate, in metres.
        x2: Second point's X coordinate, in metres.
        y2: Second point's Y coordinate, in metres.

    Returns:
        The distance in metres, unrounded.

    Raises:
        ValueError: If any coordinate is non-numeric or non-finite.
    """
    for name, value in (('x1', x1), ('y1', y1), ('x2', x2), ('y2', y2)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f'座標 {name} 必須為有限數值。')
    return math.hypot(float(x2) - float(x1), float(y2) - float(y1))
