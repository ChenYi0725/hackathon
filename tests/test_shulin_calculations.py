"""表3 arithmetic: averages, building density and the straight-line helper."""
import math
import pytest
from app.domain.shulin_residential import (
    calculate_average_road_width,
    calculate_building_density,
    calculate_straight_line_distance,
)


@pytest.mark.parametrize(('widths', 'expected'), [
    ([6], 6),
    ([4, 8], 6),
    ([3, 5, 10], 6),
    ([2.5, 7.5], 5),
    ([6, 6, 6, 6], 6),
    ([1, 2], 1.5),
])
def test_average_road_width(widths, expected):
    assert calculate_average_road_width(widths) == pytest.approx(expected)


def test_average_road_width_is_not_rounded():
    # 10/3 must survive unrounded; the display layer decides presentation.
    assert calculate_average_road_width([3, 3, 4]) == pytest.approx(10 / 3)
    assert calculate_average_road_width([3, 3, 4]) != 3.33


def test_average_road_width_counts_only_supplied_opened_roads():
    # A planned but unopened road is excluded by the caller, so it must not
    # change the divisor.
    assert calculate_average_road_width([8, 4]) == 6
    assert calculate_average_road_width([8, 4, 0]) == 4


@pytest.mark.parametrize('widths', [
    [], (), [-1], [8, -0.1], [8, float('nan')], [float('inf')], ['6'], [None], [True],
    None, 6, '6,8', (width for width in (6, 8)),
])
def test_average_road_width_rejects_invalid(widths):
    with pytest.raises(ValueError):
        calculate_average_road_width(widths)


@pytest.mark.parametrize(('built', 'total', 'expected'), [
    (70, 100, 70),
    (0, 100, 0),
    (100, 100, 100),
    (50, 200, 25),
    (1, 3, 100 / 3),
    (1234.5, 10000, 12.345),
])
def test_building_density(built, total, expected):
    assert calculate_building_density(built, total) == pytest.approx(expected)


def test_building_density_is_not_rounded():
    assert calculate_building_density(1, 3) != 33.33


@pytest.mark.parametrize(('built', 'total'), [
    (10, 0),            # divide by zero guard
    (10, -100),
    (-1, 100),
    (101, 100),         # excess is rejected, never clamped to 100
    (float('nan'), 100),
    (10, float('inf')),
    ('10', 100),
    (10, None),
])
def test_building_density_rejects_invalid(built, total):
    with pytest.raises(ValueError):
        calculate_building_density(built, total)


@pytest.mark.parametrize(('args', 'expected'), [
    ((0, 0, 3, 4), 5),
    ((0, 0, 0, 0), 0),
    ((1, 1, 1, 1), 0),
    ((-2, -2, 1, 2), 5),
    ((0, 0, 0, 1500), 1500),
    ((10, 0, 0, 0), 10),
])
def test_straight_line_distance(args, expected):
    assert calculate_straight_line_distance(*args) == pytest.approx(expected)


def test_straight_line_distance_is_symmetric():
    assert calculate_straight_line_distance(1, 2, 4, 6) == calculate_straight_line_distance(4, 6, 1, 2)


@pytest.mark.parametrize('args', [
    (float('nan'), 0, 1, 1),
    (0, float('inf'), 1, 1),
    (0, 0, '1', 1),
    (0, 0, 1, None),
    (True, 0, 1, 1),
])
def test_straight_line_distance_rejects_invalid(args):
    with pytest.raises(ValueError):
        calculate_straight_line_distance(*args)


def test_straight_line_distance_matches_pythagoras_reference():
    # Independent reference value rather than a copy of the implementation.
    assert calculate_straight_line_distance(0, 0, 1, 1) == pytest.approx(math.sqrt(2))
