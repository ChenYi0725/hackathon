"""Region-independent arithmetic for appraisal survey fields.

These functions calculate values only.  They know nothing about a locality,
factor ID, grade label, threshold, or price-adjustment matrix.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.domain.decimal_values import as_finite_decimal


def calculate_average_road_width(
    opened_road_widths_m: Sequence[Decimal],
) -> Decimal:
    """Calculate the unrounded mean width of the supplied opened roads."""

    if isinstance(opened_road_widths_m, (str, bytes)) or not isinstance(
        opened_road_widths_m, Sequence
    ):
        raise ValueError('已開闢道路寬度必須為數值序列。')
    if not opened_road_widths_m:
        raise ValueError('已開闢道路寬度不可為空。')

    widths: list[Decimal] = []
    for index, width in enumerate(opened_road_widths_m):
        number = as_finite_decimal(width, f'已開闢道路寬度[{index}]')
        if number < 0:
            raise ValueError(f'已開闢道路寬度[{index}]不得為負數。')
        widths.append(number)
    return sum(widths, Decimal('0')) / Decimal(len(widths))


def calculate_building_density(
    built_land_area_m2: Decimal,
    section_total_area_m2: Decimal,
) -> Decimal:
    """Calculate built area / section area * 100 without clamp or rounding."""

    built = as_finite_decimal(built_land_area_m2, '已建築使用土地面積')
    total = as_finite_decimal(section_total_area_m2, '區段總面積')
    if built < 0:
        raise ValueError('已建築使用土地面積不得為負數。')
    if total <= 0:
        raise ValueError('區段總面積必須大於 0。')
    if built > total:
        raise ValueError('已建築使用土地面積不得大於區段總面積。')
    return built / total * Decimal('100')


def calculate_straight_line_distance(
    x1: Decimal,
    y1: Decimal,
    x2: Decimal,
    y2: Decimal,
) -> Decimal:
    """Calculate planar straight-line distance without choosing its use case."""

    coordinates = tuple(
        as_finite_decimal(value, name)
        for name, value in (('x1', x1), ('y1', y1), ('x2', x2), ('y2', y2))
    )
    first_x, first_y, second_x, second_y = coordinates
    delta_x = second_x - first_x
    delta_y = second_y - first_y
    return (delta_x * delta_x + delta_y * delta_y).sqrt()
