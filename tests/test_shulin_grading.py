"""Grade boundaries for the Shulin ordinary-residential schedule.

Boundary tables are generated from the published cut points, so each cut point
gets a "just below / exactly on / just above" case. `test_large_station_matches_
literal_table` pins one factor with a hand-written table as a check on the
generators themselves.
"""
from decimal import Decimal
import pytest
from app.domain.shulin_residential import thresholds as T
from app.domain.shulin_residential import (
    GRADE_SCHEMES,
    UNGRADED_SURVEY_FIELDS,
    BuildingRestriction,
    DrainageLevel,
    FacilityProximity,
    GradeLabel,
    GradeResult,
    ImprovementType,
    LandscapeLevel,
    LandUseCategory,
    RoadDevelopmentLevel,
    SunlightLevel,
    TerrainLevel,
    grade_average_road_width,
    grade_building_coverage_rate,
    grade_building_prohibition,
    grade_building_restriction,
    grade_building_site_improvement,
    grade_bus_stop_proximity,
    grade_drainage,
    grade_environment_pollution,
    grade_floor_area_ratio,
    grade_funeral_facility_proximity,
    grade_interchange,
    grade_land_use,
    grade_landscape,
    grade_large_station,
    grade_main_road_width,
    grade_market_proximity,
    grade_other_factor,
    grade_park_proximity,
    grade_parking_convenience,
    grade_road_development,
    grade_school_proximity,
    grade_service_facility_proximity,
    grade_slope,
    grade_sunlight,
    grade_terrain,
    grade_tourism_facility_proximity,
    grade_urban_planning,
    grade_utility_facility_proximity,
    grade_waste_facility_proximity,
)

E = GradeLabel.EXCELLENT
SB = GradeLabel.SLIGHTLY_BETTER
N = GradeLabel.NORMAL
SW = GradeLabel.SLIGHTLY_WORSE
P = GradeLabel.POOR


DELTA = Decimal('0.001')


def cuts(*values: str) -> tuple[Decimal, ...]:
    """Cut points transcribed independently from the schedule for use in tests."""
    return tuple(Decimal(v) for v in values)


def _lower_is_better(edges):
    """Cases for ascending cut points: `value < edges[0]` is grade 1."""
    cases = [(Decimal(0), 1)]
    for i, edge in enumerate(edges):
        cases += [(edge - DELTA, i + 1), (edge, i + 2), (edge + DELTA, i + 2)]
    return cases + [(edges[-1] * 2, len(edges) + 1)]


def _higher_is_better(edges):
    """Cases for descending cut points: `value >= edges[0]` is grade 1."""
    cases = [(edges[0] * 2, 1)]
    for i, edge in enumerate(edges):
        cases += [(edge + DELTA, i + 1), (edge, i + 1), (edge - DELTA, i + 2)]
    return cases + [(Decimal(0), len(edges) + 1)]


def _table(cases, grader, name):
    return [pytest.param(grader, v, i, id=f'{name}-{v}') for v, i in cases]


# --------------------------------------------------------------------------- #
# GradeResult itself
# --------------------------------------------------------------------------- #

XE = GradeLabel.EXTREMELY_EXCELLENT
XP = GradeLabel.EXTREMELY_POOR
SE = GradeLabel.SUPREMELY_EXCELLENT
SP = GradeLabel.SUPREMELY_POOR


@pytest.mark.parametrize(('index', 'count', 'label'), [
    (1, 2, E), (2, 2, P),
    (1, 3, E), (2, 3, N), (3, 3, P),
    (1, 5, E), (2, 5, SB), (3, 5, N), (4, 5, SW), (5, 5, P),
    (1, 7, XE), (2, 7, E), (3, 7, SB), (4, 7, N), (5, 7, SW), (6, 7, P), (7, 7, XP),
    (1, 9, SE), (2, 9, XE), (3, 9, E), (4, 9, SB), (5, 9, N),
    (6, 9, SW), (7, 9, P), (8, 9, XP), (9, 9, SP),
])
def test_grade_schemes(index, count, label):
    assert GradeResult.of(index, count) == GradeResult(index=index, count=count, label=label)


def test_supported_scheme_sizes():
    assert sorted(GRADE_SCHEMES) == [2, 3, 5, 7, 9]
    assert all(len(labels) == size for size, labels in GRADE_SCHEMES.items())


def test_nine_grade_scheme_labels_are_in_order():
    assert GRADE_SCHEMES[9] == (SE, XE, E, SB, N, SW, P, XP, SP)


@pytest.mark.parametrize('count', [2, 3, 5, 7, 9])
def test_every_scheme_has_unique_labels_best_first(count):
    labels = GRADE_SCHEMES[count]
    assert len(set(labels)) == count
    assert GradeResult.best(count).label is labels[0]
    assert GradeResult.worst(count).label is labels[-1]


@pytest.mark.parametrize(('index', 'count'), [
    (0, 5), (6, 5), (-1, 5), (1, 4), (1, 6), (1, 8), (1, 10), (1, 0), (10, 9),
    (True, 5), (1.0, 5), ('1', 5),
])
def test_grade_result_rejects_out_of_range(index, count):
    with pytest.raises(ValueError):
        GradeResult.of(index, count)


def test_grade_result_rejects_label_disagreeing_with_scheme():
    with pytest.raises(ValueError):
        GradeResult(index=1, count=5, label=P)
    with pytest.raises(ValueError):
        GradeResult(index=1, count=9, label=XE)


# --------------------------------------------------------------------------- #
# 土地使用管制
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(('in_urban_plan', 'index', 'label'), [(True, 1, E), (False, 2, P)])
def test_urban_planning(in_urban_plan, index, label):
    result = grade_urban_planning(in_urban_plan)
    assert (result.index, result.count, result.label) == (index, 2, label)


@pytest.mark.parametrize(('prohibited', 'index', 'label'), [(False, 1, E), (True, 2, P)])
def test_building_prohibition(prohibited, index, label):
    result = grade_building_prohibition(prohibited)
    assert (result.index, result.count, result.label) == (index, 2, label)


@pytest.mark.parametrize('grader', [grade_urban_planning, grade_building_prohibition])
@pytest.mark.parametrize('value', [1, 0, None, '', 'True'])
def test_boolean_graders_reject_non_bool(grader, value):
    with pytest.raises(ValueError):
        grader(value)


@pytest.mark.parametrize(('category', 'index', 'label'), [
    (LandUseCategory.COMMERCIAL_ZONE, 1, E),
    (LandUseCategory.MRT_JOINT_DEVELOPMENT_LAND, 1, E),
    (LandUseCategory.RESIDENTIAL_ZONE, 2, SB),
    (LandUseCategory.MARKET_LAND, 2, SB),
    (LandUseCategory.CLASS_A_BUILDING_LAND, 3, N),
    (LandUseCategory.CLASS_B_BUILDING_LAND, 3, N),
    (LandUseCategory.SPECIFIC_PURPOSE_ZONE, 3, N),
    (LandUseCategory.MULTI_PURPOSE_PUBLIC_FACILITY_LAND, 3, N),
    (LandUseCategory.INDUSTRIAL_ZONE, 4, SW),
    (LandUseCategory.CLASS_C_BUILDING_LAND, 4, SW),
    (LandUseCategory.CLASS_D_BUILDING_LAND, 4, SW),
    (LandUseCategory.OTHER_BUILDABLE_LAND, 5, P),
])
def test_land_use(category, index, label):
    result = grade_land_use(category)
    assert (result.index, result.count, result.label) == (index, 5, label)


def test_land_use_covers_every_declared_category():
    assert {c: grade_land_use(c).index for c in LandUseCategory}.keys() == set(LandUseCategory)


@pytest.mark.parametrize(('restriction', 'index', 'label'), [
    (BuildingRestriction.NO_RESTRICTION, 1, E),
    (BuildingRestriction.PARTIAL_RESTRICTION, 2, N),
    (BuildingRestriction.OVERALL_DEVELOPMENT_RESTRICTION, 3, P),
])
def test_building_restriction(restriction, index, label):
    result = grade_building_restriction(restriction)
    assert (result.index, result.count, result.label) == (index, 3, label)


# --------------------------------------------------------------------------- #
# Numeric factors
# --------------------------------------------------------------------------- #

COVERAGE_CUTS = cuts('80', '70', '60', '50')
FAR_CUTS = cuts('460', '360', '260', '180')
MAIN_ROAD_CUTS = cuts('28', '20', '12', '8')
AVG_ROAD_CUTS = cuts('20', '15', '10', '8')
SLOPE_CUTS = cuts('5', '10', '15', '20')

NUMERIC_TABLE = (
    _table(_higher_is_better(COVERAGE_CUTS), grade_building_coverage_rate, 'coverage')
    + _table(_higher_is_better(FAR_CUTS), grade_floor_area_ratio, 'far')
    + _table(_higher_is_better(MAIN_ROAD_CUTS), grade_main_road_width, 'main-road')
    + _table(_higher_is_better(AVG_ROAD_CUTS), grade_average_road_width, 'avg-road')
    + _table(_lower_is_better(SLOPE_CUTS), grade_slope, 'slope')
)


@pytest.mark.parametrize(('shipped', 'expected'), [
    (T.BUILDING_COVERAGE_RATE, COVERAGE_CUTS),
    (T.FLOOR_AREA_RATIO, FAR_CUTS),
    (T.MAIN_ROAD_WIDTH, MAIN_ROAD_CUTS),
    (T.AVERAGE_ROAD_WIDTH, AVG_ROAD_CUTS),
    (T.SLOPE_DEGREE, SLOPE_CUTS),
])
def test_shipped_numeric_cut_points_match_the_schedule(shipped, expected):
    assert shipped == expected
    assert all(isinstance(edge, Decimal) for edge in shipped)


@pytest.mark.parametrize(('grader', 'value', 'index'), NUMERIC_TABLE)
def test_numeric_grade_boundaries(grader, value, index):
    result = grader(value)
    assert (result.index, result.count) == (index, 5)


@pytest.mark.parametrize(('rate', 'label'), [
    (80, E), (75, SB), (65, N), (55, SW), (49.9, P),
])
def test_building_coverage_rate_labels(rate, label):
    assert grade_building_coverage_rate(rate).label is label


@pytest.mark.parametrize(('rate', 'label'), [
    (460, E), (400, SB), (300, N), (200, SW), (179, P),
])
def test_floor_area_ratio_labels(rate, label):
    assert grade_floor_area_ratio(rate).label is label


@pytest.mark.parametrize('grader', [
    grade_building_coverage_rate, grade_floor_area_ratio, grade_main_road_width,
    grade_average_road_width, grade_slope,
])
@pytest.mark.parametrize('value', [
    -0.001, -1, -100, Decimal('-0.001'), float('nan'), float('inf'), '10 m', 'abc', None, True,
])
def test_numeric_graders_reject_invalid(grader, value):
    with pytest.raises(ValueError):
        grader(value)


@pytest.mark.parametrize('grader,value,index', [
    (grade_building_coverage_rate, Decimal('79.9999999999999999999'), 2),
    (grade_building_coverage_rate, Decimal('80'), 1),
    (grade_floor_area_ratio, Decimal('459.9999999999999999999'), 2),
    (grade_slope, Decimal('4.9999999999999999999'), 1),
    (grade_slope, Decimal('5'), 2),
])
def test_decimal_inputs_land_on_the_published_boundary_exactly(grader, value, index):
    # float would round these to the boundary and shift the grade.
    assert grader(value).index == index


# --------------------------------------------------------------------------- #
# 交通運輸、公共建設: nearer is better
# --------------------------------------------------------------------------- #

POSITIVE_FACILITIES = (
    ('large-station', grade_large_station, cuts('500', '1000', '1500', '2000')),
    ('bus-stop', grade_bus_stop_proximity, cuts('200', '400', '600', '800')),
    ('interchange', grade_interchange, cuts('1000', '2000', '3000', '4000')),
    ('school', grade_school_proximity, cuts('300', '500', '800', '1000')),
    ('market', grade_market_proximity, cuts('300', '500', '800', '1000')),
    ('park', grade_park_proximity, cuts('300', '500', '800', '1000')),
    ('tourism', grade_tourism_facility_proximity, cuts('500', '1000', '1500', '2000')),
    ('parking', grade_parking_convenience, cuts('200', '400', '600', '1000')),
    ('service', grade_service_facility_proximity, cuts('500', '1000', '1500', '2000')),
)

NEGATIVE_FACILITIES = (
    ('utility', grade_utility_facility_proximity),
    ('funeral', grade_funeral_facility_proximity),
    ('waste', grade_waste_facility_proximity),
    ('pollution', grade_environment_pollution),
)

NUISANCE_CUTS = cuts('2000', '1500', '1000', '500')


def test_shipped_facility_cut_points_match_the_schedule():
    shipped = {
        'large-station': T.LARGE_STATION_DISTANCE, 'bus-stop': T.BUS_STOP_DISTANCE,
        'interchange': T.INTERCHANGE_DISTANCE, 'school': T.SCHOOL_DISTANCE,
        'market': T.MARKET_DISTANCE, 'park': T.PARK_DISTANCE,
        'tourism': T.TOURISM_FACILITY_DISTANCE, 'parking': T.PARKING_DISTANCE,
        'service': T.SERVICE_FACILITY_DISTANCE,
    }
    assert shipped == {name: edges for name, _, edges in POSITIVE_FACILITIES}
    assert T.NUISANCE_DISTANCE == NUISANCE_CUTS


@pytest.mark.parametrize(('grader', 'distance', 'index'), [
    param
    for name, grader, cuts in POSITIVE_FACILITIES
    for param in _table(_lower_is_better(cuts), grader, name)
])
def test_positive_facility_boundaries(grader, distance, index):
    result = grader(FacilityProximity(exists=True, in_section=False, distance_m=distance))
    assert (result.index, result.count) == (index, 5)


@pytest.mark.parametrize(('distance', 'label'), [
    (0, E), (499.999, E), (500, SB), (999.999, SB), (1000, N),
    (1499.999, N), (1500, SW), (1999.999, SW), (2000, P), (10000, P),
])
def test_large_station_matches_literal_table(distance, label):
    assert grade_large_station(
        FacilityProximity(exists=True, in_section=False, distance_m=distance)).label is label


@pytest.mark.parametrize('name,grader,cuts', POSITIVE_FACILITIES)
def test_positive_facility_absent_and_in_section(name, grader, cuts):
    assert grader(FacilityProximity(exists=False)).label is P
    assert grader(FacilityProximity(exists=True, in_section=True)).label is E
    # A facility inside the section grades best regardless of any recorded distance.
    assert grader(FacilityProximity(exists=True, in_section=True, distance_m=cuts[-1] * 2)).label is E


@pytest.mark.parametrize(('grader', 'distance', 'index'), [
    param
    for name, grader in NEGATIVE_FACILITIES
    for param in _table(_higher_is_better(NUISANCE_CUTS), grader, name)
])
def test_negative_facility_boundaries(grader, distance, index):
    result = grader(FacilityProximity(exists=True, in_section=False, distance_m=distance))
    assert (result.index, result.count) == (index, 5)


@pytest.mark.parametrize(('distance', 'label'), [
    (5000, E), (2000, E), (1999.999, SB), (1500, SB), (1499.999, N),
    (1000, N), (999.999, SW), (500, SW), (499.999, P), (0, P),
])
def test_waste_facility_matches_literal_table(distance, label):
    assert grade_waste_facility_proximity(
        FacilityProximity(exists=True, in_section=False, distance_m=distance)).label is label


@pytest.mark.parametrize('name,grader', NEGATIVE_FACILITIES)
def test_negative_facility_absent_and_in_section(name, grader):
    # Direction is the mirror image of the positive facilities.
    assert grader(FacilityProximity(exists=False)).label is E
    assert grader(FacilityProximity(exists=True, in_section=True)).label is P
    assert grader(FacilityProximity(exists=True, in_section=True, distance_m=9999)).label is P


@pytest.mark.parametrize('name,grader,cuts', POSITIVE_FACILITIES)
def test_positive_facility_rejects_non_proximity(name, grader, cuts):
    with pytest.raises(ValueError):
        grader(500)


@pytest.mark.parametrize('name,grader', NEGATIVE_FACILITIES)
def test_negative_facility_rejects_non_proximity(name, grader):
    with pytest.raises(ValueError):
        grader(500)


# --------------------------------------------------------------------------- #
# FacilityProximity invariants
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('kwargs', [
    dict(exists=True, in_section=False, distance_m=None),   # outside needs a distance
    dict(exists=False, distance_m=0),                       # 0 m must not stand for "absent"
    dict(exists=False, distance_m=500),
    dict(exists=False, in_section=True),                    # absent cannot be inside
    dict(exists=True, in_section=False, distance_m=-1),
    dict(exists=True, in_section=False, distance_m=float('nan')),
    dict(exists=True, in_section=False, distance_m=float('inf')),
    dict(exists=True, in_section=False, distance_m='500 公尺'),
    dict(exists=True, in_section=False, distance_m=Decimal('-1')),
    dict(exists=1, in_section=False, distance_m=500),
    dict(exists=True, in_section=1, distance_m=500),
])
def test_facility_proximity_rejects_contradictions(kwargs):
    with pytest.raises(ValueError):
        FacilityProximity(**kwargs)


@pytest.mark.parametrize('kwargs', [
    dict(exists=False),
    dict(exists=True, in_section=True),
    dict(exists=True, in_section=True, distance_m=0),
    dict(exists=True, in_section=False, distance_m=0),
    dict(exists=True, in_section=False, distance_m=1234.5),
    dict(exists=True, in_section=False, distance_m=Decimal('1234.5')),
])
def test_facility_proximity_accepts_valid(kwargs):
    assert FacilityProximity(**kwargs).exists == kwargs['exists']


# --------------------------------------------------------------------------- #
# 自然條件
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(('grader', 'level', 'index', 'label'), [
    (grade_sunlight, SunlightLevel.FULL, 1, E),
    (grade_sunlight, SunlightLevel.SLIGHT_SHADE, 2, SB),
    (grade_sunlight, SunlightLevel.PARTIAL_SHADE, 3, N),
    (grade_sunlight, SunlightLevel.CONSIDERABLE_SHADE, 4, SW),
    (grade_sunlight, SunlightLevel.MOSTLY_SHADED, 5, P),
    (grade_landscape, LandscapeLevel.EXTREMELY_WIDE_AND_BEAUTIFUL, 1, E),
    (grade_landscape, LandscapeLevel.WIDE_AND_BEAUTIFUL, 2, SB),
    (grade_landscape, LandscapeLevel.ACCEPTABLE, 3, N),
    (grade_landscape, LandscapeLevel.POOR, 4, SW),
    (grade_landscape, LandscapeLevel.EXTREMELY_POOR, 5, P),
    (grade_drainage, DrainageLevel.EXTREMELY_COMPLETE, 1, E),
    (grade_drainage, DrainageLevel.HIGHLY_COMPLETE, 2, SB),
    (grade_drainage, DrainageLevel.ORDINARY_COMPLETE, 3, N),
    (grade_drainage, DrainageLevel.INADEQUATE, 4, SW),
    (grade_drainage, DrainageLevel.EXTREMELY_INADEQUATE, 5, P),
    (grade_terrain, TerrainLevel.EXTREMELY_FLAT_AND_FIRM, 1, E),
    (grade_terrain, TerrainLevel.FLAT, 2, SB),
    (grade_terrain, TerrainLevel.GENTLE_SLOPE, 3, N),
    (grade_terrain, TerrainLevel.LOWLAND_OR_WETLAND, 4, SW),
    (grade_terrain, TerrainLevel.ISOLATED_AND_POOR, 5, P),
    (grade_road_development, RoadDevelopmentLevel.FULLY_PLANNED_AND_DEVELOPED, 1, E),
    (grade_road_development, RoadDevelopmentLevel.MOSTLY_PLANNED_AND_DEVELOPED, 2, SB),
    (grade_road_development, RoadDevelopmentLevel.PARTIALLY_PLANNED_AND_DEVELOPED, 3, N),
    (grade_road_development, RoadDevelopmentLevel.GRAVEL_ROAD, 4, SW),
    (grade_road_development, RoadDevelopmentLevel.NOT_PLANNED_OR_DEVELOPED, 5, P),
])
def test_categorical_grades(grader, level, index, label):
    result = grader(level)
    assert (result.index, result.count, result.label) == (index, 5, label)


CATEGORICAL_GRADERS = (
    (grade_sunlight, SunlightLevel),
    (grade_landscape, LandscapeLevel),
    (grade_drainage, DrainageLevel),
    (grade_terrain, TerrainLevel),
    (grade_road_development, RoadDevelopmentLevel),
    (grade_land_use, LandUseCategory),
    (grade_building_restriction, BuildingRestriction),
)


@pytest.mark.parametrize('grader,enum_type', CATEGORICAL_GRADERS)
@pytest.mark.parametrize('value', [None, 1, 0, GradeLabel.EXCELLENT, '不存在的類別', '', ['充分']])
def test_categorical_graders_reject_unknown_values(grader, enum_type, value):
    with pytest.raises(ValueError):
        grader(value)


@pytest.mark.parametrize('grader,enum_type', CATEGORICAL_GRADERS)
def test_categorical_graders_accept_the_printed_wording(grader, enum_type):
    # OCR drafts carry the schedule's own wording, so the raw value grades the
    # same as the enum member.
    for member in enum_type:
        assert grader(member.value) == grader(member)


# --------------------------------------------------------------------------- #
# 土地改良
# --------------------------------------------------------------------------- #

I = ImprovementType
ALL_ITEMS = tuple(I)


@pytest.mark.parametrize(('items', 'index', 'label'), [
    ((), 5, P),
    ((I.SITE_LEVELING,), 4, SW),
    ((I.SITE_LEVELING, I.DITCH_EXCAVATION), 3, N),
    ((I.SITE_LEVELING, I.DITCH_EXCAVATION, I.ROAD_PAVING), 2, SB),
    ((I.SITE_LEVELING, I.DITCH_EXCAVATION, I.ROAD_PAVING, I.PIPE_LAYING), 1, E),
    (ALL_ITEMS, 1, E),
    (ALL_ITEMS[:5], 1, E),
])
def test_building_site_improvement(items, index, label):
    result = grade_building_site_improvement(items)
    assert (result.index, result.count, result.label) == (index, 5, label)


@pytest.mark.parametrize(('items', 'index'), [
    ((I.SITE_LEVELING, I.SITE_LEVELING), 4),
    ((I.SITE_LEVELING, I.SITE_LEVELING, I.SITE_LEVELING, I.SITE_LEVELING), 4),
    ((I.SITE_LEVELING, I.SITE_LEVELING, I.ROAD_PAVING), 3),
])
def test_building_site_improvement_counts_unique_items(items, index):
    assert grade_building_site_improvement(items).index == index


def test_building_site_improvement_accepts_a_set():
    assert grade_building_site_improvement({I.SITE_LEVELING, I.ROAD_PAVING}).index == 3


@pytest.mark.parametrize('items', [
    ['整平或填挖基地'], [None], ['農地改良'], '整平或填挖基地', 3, None,
    [I.SITE_LEVELING, '灌溉'],
])
def test_building_site_improvement_rejects_invalid(items):
    with pytest.raises(ValueError):
        grade_building_site_improvement(items)


# --------------------------------------------------------------------------- #
# 其他影響因素
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(('label', 'index'), [
    (GradeLabel.EXTREMELY_EXCELLENT, 1),
    (GradeLabel.EXCELLENT, 2),
    (GradeLabel.SLIGHTLY_BETTER, 3),
    (GradeLabel.NORMAL, 4),
    (GradeLabel.SLIGHTLY_WORSE, 5),
    (GradeLabel.POOR, 6),
    (GradeLabel.EXTREMELY_POOR, 7),
])
def test_other_factor_uses_externally_decided_seven_grade_label(label, index):
    result = grade_other_factor(label)
    assert (result.index, result.count, result.label) == (index, 7, label)


@pytest.mark.parametrize('value', ['優', None, 1, 4])
def test_other_factor_rejects_non_label(value):
    with pytest.raises(ValueError):
        grade_other_factor(value)


# --------------------------------------------------------------------------- #
# Threshold table invariants
# --------------------------------------------------------------------------- #

HIGHER_IS_BETTER_TABLES = (
    ('coverage', T.BUILDING_COVERAGE_RATE),
    ('far', T.FLOOR_AREA_RATIO),
    ('main-road', T.MAIN_ROAD_WIDTH),
    ('avg-road', T.AVERAGE_ROAD_WIDTH),
    ('improvement-count', T.IMPROVEMENT_ITEM_COUNT),
    ('nuisance', T.NUISANCE_DISTANCE),
)

SMALLER_IS_BETTER_TABLES = (
    ('slope', T.SLOPE_DEGREE),
    ('large-station', T.LARGE_STATION_DISTANCE),
    ('bus-stop', T.BUS_STOP_DISTANCE),
    ('interchange', T.INTERCHANGE_DISTANCE),
    ('school', T.SCHOOL_DISTANCE),
    ('market', T.MARKET_DISTANCE),
    ('park', T.PARK_DISTANCE),
    ('tourism', T.TOURISM_FACILITY_DISTANCE),
    ('parking', T.PARKING_DISTANCE),
    ('service', T.SERVICE_FACILITY_DISTANCE),
)


@pytest.mark.parametrize('name,cuts', HIGHER_IS_BETTER_TABLES)
def test_higher_is_better_tables_descend_strictly(name, cuts):
    assert len(cuts) == 4
    assert all(a > b for a, b in zip(cuts, cuts[1:]))


@pytest.mark.parametrize('name,cuts', SMALLER_IS_BETTER_TABLES)
def test_smaller_is_better_tables_ascend_strictly(name, cuts):
    assert len(cuts) == 4
    assert all(a < b for a, b in zip(cuts, cuts[1:]))


def test_school_market_and_park_share_one_distance_table():
    assert T.SCHOOL_DISTANCE == T.MARKET_DISTANCE == T.PARK_DISTANCE


def test_ungraded_survey_fields_are_documented_and_have_no_grader():
    import app.domain.shulin_residential as pkg
    assert '風勢' in UNGRADED_SURVEY_FIELDS
    assert '土質' in UNGRADED_SURVEY_FIELDS
    assert '站牌密集程度' in UNGRADED_SURVEY_FIELDS
    exported = set(pkg.__all__)
    for name in ('grade_wind', 'grade_soil', 'grade_bus_stop_density', 'grade_settlement',
                 'grade_distribution_center', 'grade_consumer_market', 'grade_farmland_improvement',
                 'grade_customer_traffic', 'grade_shop_continuity', 'grade_building_type',
                 'grade_land_use_status', 'grade_department_store', 'grade_financial_institution'):
        assert name not in exported
        assert not hasattr(pkg, name)


def test_building_coverage_and_floor_area_ratio_are_graded_but_never_derived():
    import app.domain.shulin_residential as pkg
    # The statutory ratios come from the urban plan or the non-urban land-use
    # control regulations; only grading belongs here.
    assert hasattr(pkg, 'grade_building_coverage_rate')
    assert hasattr(pkg, 'grade_floor_area_ratio')
    for name in ('calculate_building_coverage_rate', 'calculate_floor_area_ratio',
                 'get_building_coverage_ratio', 'get_floor_area_ratio'):
        assert not hasattr(pkg, name)
