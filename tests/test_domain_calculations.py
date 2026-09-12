"""Exact, locality-neutral arithmetic used before ruleset evaluation."""

from decimal import Decimal, getcontext

import pytest

from app.domain.calculations import (
    calculate_average_road_width,
    calculate_building_density,
    calculate_straight_line_distance,
)

D = Decimal


@pytest.mark.parametrize(
    ('widths', 'expected'),
    [
        ([D('6')], D('6')),
        ([D('4'), D('8')], D('6')),
        ([D('2.5'), D('7.5')], D('5.0')),
        ([D('3'), D('3'), D('4')], D('10') / D('3')),
    ],
)
def test_average_road_width_uses_decimal_without_rounding(widths, expected):
    result = calculate_average_road_width(widths)
    assert result == expected
    assert isinstance(result, Decimal)


@pytest.mark.parametrize(
    'widths',
    [
        [],
        (),
        [D('-0.001')],
        [D('NaN')],
        [D('Infinity')],
        [1.5],
        [True],
        None,
        '4,8',
        (value for value in (D('4'), D('8'))),
    ],
)
def test_average_road_width_rejects_invalid_input(widths):
    with pytest.raises(ValueError):
        calculate_average_road_width(widths)


@pytest.mark.parametrize(
    ('built', 'total', 'expected'),
    [
        (D('0'), D('100'), D('0')),
        (D('70'), D('100'), D('70')),
        (D('100'), D('100'), D('100')),
        (D('1'), D('3'), D('100') / D('3')),
        (D('1234.5'), D('10000'), D('12.345')),
    ],
)
def test_building_density_uses_decimal_without_rounding(built, total, expected):
    result = calculate_building_density(built, total)
    assert result == expected
    assert isinstance(result, Decimal)


@pytest.mark.parametrize(
    ('built', 'total'),
    [
        (D('-0.001'), D('100')),
        (D('10'), D('0')),
        (D('10'), D('-1')),
        (D('100.001'), D('100')),
        (D('NaN'), D('100')),
        (D('10'), D('Infinity')),
        (10.5, D('100')),
    ],
)
def test_building_density_rejects_invalid_input(built, total):
    with pytest.raises(ValueError):
        calculate_building_density(built, total)


@pytest.mark.parametrize(
    ('coordinates', 'expected'),
    [
        ((D('0'), D('0'), D('3'), D('4')), D('5')),
        ((D('-2'), D('-2'), D('1'), D('2')), D('5')),
        ((D('1'), D('1'), D('1'), D('1')), D('0')),
    ],
)
def test_straight_line_distance(coordinates, expected):
    assert calculate_straight_line_distance(*coordinates) == expected


def test_straight_line_distance_keeps_decimal_context_precision():
    result = calculate_straight_line_distance(D('0'), D('0'), D('1'), D('1'))
    assert result == D('2').sqrt()
    assert len(result.as_tuple().digits) == getcontext().prec
    assert result != D('1.41')


@pytest.mark.parametrize(
    'coordinates',
    [
        (D('NaN'), D('0'), D('1'), D('1')),
        (D('0'), D('Infinity'), D('1'), D('1')),
        (D('0'), D('0'), 1.0, D('1')),
        (D('0'), D('0'), None, D('1')),
        (True, D('0'), D('1'), D('1')),
    ],
)
def test_straight_line_distance_rejects_inexact_or_invalid_coordinates(coordinates):
    with pytest.raises(ValueError):
        calculate_straight_line_distance(*coordinates)
