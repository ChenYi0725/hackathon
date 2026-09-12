"""Grade pair to adjustment rate, matrix invariants and sign direction.

Expected rates are `Decimal`, transcribed from the 價格修正率 tables of
《新北市樹林區普通住宅用地影響地價區域因素評價基準明細表》pages 4-26 to 4-30.
"""
from decimal import Decimal
import pytest
from app.domain.shulin_residential import (
    GradeLabel,
    GradeResult,
    calculate_adjustment_rate,
    grade_building_coverage_rate,
    grade_large_station,
    grade_urban_planning,
    FacilityProximity,
)
from app.domain.shulin_residential import matrices as M

FIVE_GRADE_MATRICES = (
    ('land-use', M.LAND_USE_MATRIX),
    ('coverage', M.BUILDING_COVERAGE_MATRIX),
    ('far', M.FLOOR_AREA_RATIO_MATRIX),
    ('main-road', M.MAIN_ROAD_WIDTH_MATRIX),
    ('avg-road', M.AVERAGE_ROAD_WIDTH_MATRIX),
    ('large-station', M.LARGE_STATION_MATRIX),
    ('bus-stop', M.BUS_STOP_MATRIX),
    ('interchange', M.INTERCHANGE_MATRIX),
    ('road-development', M.ROAD_DEVELOPMENT_MATRIX),
    ('sunlight', M.SUNLIGHT_MATRIX),
    ('landscape', M.LANDSCAPE_MATRIX),
    ('slope', M.SLOPE_MATRIX),
    ('drainage', M.DRAINAGE_MATRIX),
    ('terrain', M.TERRAIN_MATRIX),
    ('site-improvement', M.SITE_IMPROVEMENT_MATRIX),
    ('school', M.SCHOOL_MATRIX),
    ('market', M.MARKET_MATRIX),
    ('park', M.PARK_MATRIX),
    ('tourism', M.TOURISM_FACILITY_MATRIX),
    ('parking', M.PARKING_MATRIX),
    ('service', M.SERVICE_FACILITY_MATRIX),
    ('utility', M.UTILITY_FACILITY_MATRIX),
    ('funeral', M.FUNERAL_FACILITY_MATRIX),
    ('waste', M.WASTE_FACILITY_MATRIX),
    ('pollution', M.ENVIRONMENT_POLLUTION_MATRIX),
)

ALL_MATRICES = (
    ('urban-planning', M.URBAN_PLANNING_MATRIX, 2),
    ('prohibition', M.BUILDING_PROHIBITION_MATRIX, 2),
    ('restriction', M.BUILDING_RESTRICTION_MATRIX, 3),
    ('other-factor', M.OTHER_FACTOR_MATRIX, 7),
) + tuple((name, matrix, 5) for name, matrix in FIVE_GRADE_MATRICES)


# --------------------------------------------------------------------------- #
# Shipped matrix invariants
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('name,matrix,count', ALL_MATRICES)
def test_matrix_is_square_and_sized_to_its_scheme(name, matrix, count):
    assert len(matrix) == count
    assert all(len(row) == count for row in matrix)


@pytest.mark.parametrize('name,matrix,count', ALL_MATRICES)
def test_same_grade_adjustment_is_zero(name, matrix, count):
    for i in range(1, count + 1):
        grade = GradeResult.of(i, count)
        assert calculate_adjustment_rate(grade, grade, matrix) == 0


@pytest.mark.parametrize('name,matrix,count', ALL_MATRICES)
def test_matrix_is_antisymmetric(name, matrix, count):
    # Swapping target and benchmark must only flip the sign.
    for i in range(1, count + 1):
        for j in range(1, count + 1):
            target, benchmark = GradeResult.of(i, count), GradeResult.of(j, count)
            assert (calculate_adjustment_rate(target, benchmark, matrix)
                    == -calculate_adjustment_rate(benchmark, target, matrix))


@pytest.mark.parametrize('name,matrix,count', ALL_MATRICES)
def test_better_target_than_benchmark_is_positive(name, matrix, count):
    # Grade index 1 is the best, so a lower target index must not be penalised.
    best, worst = GradeResult.of(1, count), GradeResult.of(count, count)
    assert calculate_adjustment_rate(best, worst, matrix) > 0
    assert calculate_adjustment_rate(worst, best, matrix) < 0


# --------------------------------------------------------------------------- #
# Documented cell values
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(('target', 'benchmark', 'expected'), [
    (1, 1, 0), (1, 5, 20), (5, 1, -20), (2, 4, 10), (4, 2, -10), (3, 4, 5), (2, 3, 5),
])
def test_land_use_matrix_values(target, benchmark, expected):
    rate = calculate_adjustment_rate(
        GradeResult.of(target, 5), GradeResult.of(benchmark, 5), M.LAND_USE_MATRIX)
    assert rate == expected


@pytest.mark.parametrize(('target', 'benchmark', 'expected'), [
    (1, 2, '6.25'), (1, 5, '25'), (5, 1, '-25'), (2, 5, '18.75'), (4, 3, '-6.25'),
])
def test_floor_area_ratio_matrix_values(target, benchmark, expected):
    rate = calculate_adjustment_rate(
        GradeResult.of(target, 5), GradeResult.of(benchmark, 5), M.FLOOR_AREA_RATIO_MATRIX)
    assert rate == Decimal(expected)


@pytest.mark.parametrize(('target', 'benchmark', 'expected'), [
    (1, 2, '3.33'), (1, 3, '6.67'), (1, 4, '10'), (1, 5, '13.33'), (1, 6, '16.67'),
    (1, 7, '20'), (7, 1, '-20'), (3, 6, '10'), (6, 3, '-10'), (2, 5, '10'), (4, 6, '6.67'),
])
def test_other_factor_matrix_keeps_printed_values(target, benchmark, expected):
    # 6.67 / 13.33 / 16.67 must stay as printed, not be regenerated as n * 3.33.
    rate = calculate_adjustment_rate(
        GradeResult.of(target, 7), GradeResult.of(benchmark, 7), M.OTHER_FACTOR_MATRIX)
    assert rate == Decimal(expected)


def test_other_factor_matrix_is_not_a_multiple_of_a_single_step():
    assert M.OTHER_FACTOR_MATRIX[0][2] == Decimal('6.67')
    assert M.OTHER_FACTOR_MATRIX[0][2] != Decimal('3.33') * 2
    assert M.OTHER_FACTOR_MATRIX[0][4] == Decimal('13.33')
    assert M.OTHER_FACTOR_MATRIX[0][5] == Decimal('16.67')


@pytest.mark.parametrize(('target', 'benchmark', 'expected'), [
    (1, 1, 0), (1, 2, 20), (2, 1, -20),
])
def test_urban_planning_matrix_values(target, benchmark, expected):
    rate = calculate_adjustment_rate(
        GradeResult.of(target, 2), GradeResult.of(benchmark, 2), M.URBAN_PLANNING_MATRIX)
    assert rate == expected


@pytest.mark.parametrize(('target', 'benchmark', 'expected'), [
    (1, 2, 50), (2, 1, -50),
])
def test_building_prohibition_matrix_values(target, benchmark, expected):
    rate = calculate_adjustment_rate(
        GradeResult.of(target, 2), GradeResult.of(benchmark, 2), M.BUILDING_PROHIBITION_MATRIX)
    assert rate == expected


@pytest.mark.parametrize(('target', 'benchmark', 'expected'), [
    (1, 2, 25), (1, 3, 50), (3, 1, -50), (2, 3, 25), (3, 2, -25),
])
def test_building_restriction_matrix_values(target, benchmark, expected):
    rate = calculate_adjustment_rate(
        GradeResult.of(target, 3), GradeResult.of(benchmark, 3), M.BUILDING_RESTRICTION_MATRIX)
    assert rate == expected


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def test_mixed_grade_scheme_sizes_are_rejected():
    with pytest.raises(ValueError):
        calculate_adjustment_rate(GradeResult.of(1, 5), GradeResult.of(1, 3), M.LAND_USE_MATRIX)


@pytest.mark.parametrize('matrix', [
    (),                                             # no rows
    ((0.0, 1.0), (-1.0, 0.0)),                      # 2x2 against a 5-grade pair
    tuple([(0.0,) * 5] * 4),                        # too few rows
    tuple([(0.0,) * 5] * 6),                        # too many rows
    ((0.0,) * 5, (0.0,) * 4, (0.0,) * 5, (0.0,) * 5, (0.0,) * 5),   # ragged
    ('abcde', 'abcde', 'abcde', 'abcde', 'abcde'),  # rows must not be strings
    (((0.0,) * 5),) * 5 + ((0.0,) * 5,),            # 6 rows
])
def test_matrix_dimension_validation(matrix):
    with pytest.raises(ValueError):
        calculate_adjustment_rate(GradeResult.of(1, 5), GradeResult.of(2, 5), matrix)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), None, 'abc', '', object(), True])
def test_non_finite_matrix_cells_are_rejected(bad):
    matrix = [list(row) for row in M.LAND_USE_MATRIX]
    matrix[2][3] = bad
    with pytest.raises(ValueError):
        calculate_adjustment_rate(GradeResult.of(1, 5), GradeResult.of(2, 5), matrix)


@pytest.mark.parametrize(('target', 'benchmark'), [
    (1, GradeResult.of(1, 5)),
    (GradeResult.of(1, 5), 1),
    (None, GradeResult.of(1, 5)),
    (GradeLabel.EXCELLENT, GradeResult.of(1, 5)),
])
def test_non_grade_arguments_are_rejected(target, benchmark):
    with pytest.raises(ValueError):
        calculate_adjustment_rate(target, benchmark, M.LAND_USE_MATRIX)


def test_matrix_accepts_plain_lists():
    matrix = [list(row) for row in M.LAND_USE_MATRIX]
    assert calculate_adjustment_rate(GradeResult.of(1, 5), GradeResult.of(5, 5), matrix) == 20


# --------------------------------------------------------------------------- #
# Layer composition
# --------------------------------------------------------------------------- #

def test_grading_then_pricing_a_coverage_difference():
    target = grade_building_coverage_rate(50)     # 稍劣, 4/5
    benchmark = grade_building_coverage_rate(80)  # 優, 1/5
    assert (target.index, benchmark.index) == (4, 1)
    assert calculate_adjustment_rate(target, benchmark, M.BUILDING_COVERAGE_MATRIX) == Decimal('-7.5')
    assert calculate_adjustment_rate(benchmark, target, M.BUILDING_COVERAGE_MATRIX) == Decimal('7.5')


def test_grading_then_pricing_a_station_difference():
    target = grade_large_station(FacilityProximity(exists=True, in_section=True))
    benchmark = grade_large_station(FacilityProximity(exists=False))
    assert (target.label, benchmark.label) == (GradeLabel.EXCELLENT, GradeLabel.POOR)
    assert calculate_adjustment_rate(target, benchmark, M.LARGE_STATION_MATRIX) == 10


def test_urban_planning_outside_plan_is_penalised_against_inside():
    outside = grade_urban_planning(False)
    inside = grade_urban_planning(True)
    assert calculate_adjustment_rate(outside, inside, M.URBAN_PLANNING_MATRIX) == -20
    assert calculate_adjustment_rate(inside, outside, M.URBAN_PLANNING_MATRIX) == 20


# --------------------------------------------------------------------------- #
# Decimal representation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('name,matrix,count', ALL_MATRICES)
def test_matrix_cells_are_decimal_never_float(name, matrix, count):
    for row in matrix:
        for cell in row:
            assert isinstance(cell, Decimal), (name, cell)
            assert not isinstance(cell, float)


@pytest.mark.parametrize('name,matrix,count', ALL_MATRICES)
def test_adjustment_rate_returns_decimal(name, matrix, count):
    rate = calculate_adjustment_rate(
        GradeResult.of(1, count), GradeResult.of(count, count), matrix)
    assert isinstance(rate, Decimal)


def test_repeated_decimal_values_stay_exact_when_summed():
    # Three 6.67 cells sum to exactly 20.01; the float equivalent drifts, which is
    # what would corrupt a 總修正數 built from several factors.
    rate = calculate_adjustment_rate(
        GradeResult.of(1, 7), GradeResult.of(3, 7), M.OTHER_FACTOR_MATRIX)
    assert rate == Decimal('6.67')
    assert sum([rate] * 3) == Decimal('20.01')
    assert sum([6.67] * 3) != 20.01


def test_matrix_accepts_decimal_int_float_and_numeric_string_cells():
    for cells in (Decimal('20'), 20, 20.0, '20'):
        matrix = [list(row) for row in M.LAND_USE_MATRIX]
        matrix[0][4] = cells
        rate = calculate_adjustment_rate(GradeResult.of(1, 5), GradeResult.of(5, 5), matrix)
        assert rate == Decimal('20')
        assert isinstance(rate, Decimal)


def test_nine_grade_scheme_works_with_a_caller_supplied_matrix():
    # No Shulin row uses 9 grades; the generic lookup must still handle one.
    step = Decimal('2.5')
    matrix = tuple(tuple(step * (j - i) for j in range(9)) for i in range(9))
    best, worst = GradeResult.of(1, 9), GradeResult.of(9, 9)
    assert calculate_adjustment_rate(best, worst, matrix) == Decimal('20')
    assert calculate_adjustment_rate(worst, best, matrix) == Decimal('-20')
    assert calculate_adjustment_rate(best, best, matrix) == 0
    assert calculate_adjustment_rate(GradeResult.of(4, 9), GradeResult.of(6, 9), matrix) == Decimal('5')


def test_nine_grade_pair_rejects_a_seven_grade_matrix():
    with pytest.raises(ValueError):
        calculate_adjustment_rate(GradeResult.of(1, 9), GradeResult.of(9, 9), M.OTHER_FACTOR_MATRIX)
