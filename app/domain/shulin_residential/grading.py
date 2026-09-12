"""Raw survey data to 優劣等級 for the Shulin ordinary-residential schedule.

Each public function answers one row of
《新北市樹林區普通住宅用地影響地價區域因素評價基準明細表》pages 4-26 to 4-30 and
returns a `GradeResult`. Grading never prices a difference: pair the result with
the matching matrix from `matrices.py` via `adjustments.calculate_adjustment_rate`.

Measured values are compared as `Decimal` so a value sitting exactly on a printed
boundary grades deterministically; `int`, `float` and `Decimal` inputs are all
accepted.

Thresholds are never accepted from callers; they live in `thresholds.py`.
Factors the Shulin ordinary-residential schedule does not list are intentionally
absent, see `UNGRADED_SURVEY_FIELDS`.
"""
from collections.abc import Collection, Sequence
from decimal import Decimal

from app.domain.shulin_residential import thresholds as T
from app.domain.shulin_residential.enums import (
    BuildingRestriction,
    DrainageLevel,
    GradeLabel,
    ImprovementType,
    LandscapeLevel,
    LandUseCategory,
    RoadDevelopmentLevel,
    SunlightLevel,
    TerrainLevel,
)
from app.domain.shulin_residential.models import (
    GRADE_SCHEMES,
    FacilityProximity,
    GradeResult,
)
from app.domain.shulin_residential.validation import (
    require_bool,
    require_non_negative_decimal,
)

Numeric = Decimal | float | int

#: 表3 fields kept as survey records only: the Shulin ordinary-residential
#: schedule does not list them as evaluation items, so no grading rule exists
#: for them here and none is invented.
UNGRADED_SURVEY_FIELDS: tuple[str, ...] = (
    '接近聚落程度', '接近運銷中心程度', '接近消費市場程度', '風勢', '土質', '農地改良',
    '電力資源', '產業用水及設施', '污廢水及廢棄物處理設施（公共建設欄）', '百貨公司',
    '金融機構', '娛樂設施', '大型展示中心或觀光飯店', '顧客通行量', '店舖毗連狀態',
    '建築型態', '土地利用現況', '站牌密集程度',
)


# --------------------------------------------------------------------------- #
# Shared classification helpers
# --------------------------------------------------------------------------- #

def _grade_higher_is_better(
    value: Numeric, cut_points: Sequence[Decimal], field: str
) -> GradeResult:
    """Grade a value where larger is better; `cut_points` descend."""
    number = require_non_negative_decimal(value, field)
    count = len(cut_points) + 1
    for i, edge in enumerate(cut_points):
        if number >= edge:
            return GradeResult.of(i + 1, count)
    return GradeResult.worst(count)


def _grade_smaller_is_better(
    value: Numeric, cut_points: Sequence[Decimal], field: str
) -> GradeResult:
    """Grade a value where smaller is better; `cut_points` ascend."""
    number = require_non_negative_decimal(value, field)
    count = len(cut_points) + 1
    for i, edge in enumerate(cut_points):
        if number < edge:
            return GradeResult.of(i + 1, count)
    return GradeResult.worst(count)


def _grade_from_groups(value, enum_type, groups: Sequence[Sequence], field: str) -> GradeResult:
    """Grade a category by which group of `groups` contains it; group 0 is best.

    Accepts either an `enum_type` member or the exact schedule wording behind it,
    so drafts carrying the printed text can be graded without the caller mapping
    strings by hand. Anything else raises.
    """
    try:
        member = enum_type(value)
    except (ValueError, TypeError, KeyError):
        raise ValueError(f'{field} 不是本基準已定義的類別：{value!r}') from None
    for i, group in enumerate(groups):
        if member in group:
            return GradeResult.of(i + 1, len(groups))
    raise ValueError(f'{field} 未列於本基準的等級分組：{value!r}')


def _grade_positive_facility_distance(
    proximity: FacilityProximity, cut_points: Sequence[Decimal], field: str
) -> GradeResult:
    """Grade a facility whose nearness raises land value (學校、市場、車站等).

    Absent facility grades worst, a facility inside the section grades best, and
    otherwise the recorded distance is classified with `cut_points`.
    """
    if not isinstance(proximity, FacilityProximity):
        raise ValueError(f'{field} 必須為 FacilityProximity。')
    count = len(cut_points) + 1
    if not proximity.exists:
        return GradeResult.worst(count)
    if proximity.in_section:
        return GradeResult.best(count)
    return _grade_smaller_is_better(proximity.distance_m, cut_points, field)


def _grade_negative_facility_distance(
    proximity: FacilityProximity, cut_points: Sequence[Decimal], field: str
) -> GradeResult:
    """Grade a facility whose nearness lowers land value (特殊設施、污染源).

    Absent facility grades best, a facility inside the section grades worst, and
    otherwise the recorded distance is classified with `cut_points`, which
    descend because greater distance is better.
    """
    if not isinstance(proximity, FacilityProximity):
        raise ValueError(f'{field} 必須為 FacilityProximity。')
    count = len(cut_points) + 1
    if not proximity.exists:
        return GradeResult.best(count)
    if proximity.in_section:
        return GradeResult.worst(count)
    return _grade_higher_is_better(proximity.distance_m, cut_points, field)


# --------------------------------------------------------------------------- #
# 土地使用管制
# --------------------------------------------------------------------------- #

def grade_urban_planning(in_urban_plan: bool) -> GradeResult:
    """都市計畫內外。都市計畫內為優，都市計畫外為劣（2 級制）。"""
    return GradeResult.best(2) if require_bool(in_urban_plan, '都市計畫內外') else GradeResult.worst(2)


_LAND_USE_GROUPS: tuple[tuple[LandUseCategory, ...], ...] = (
    (LandUseCategory.COMMERCIAL_ZONE, LandUseCategory.MRT_JOINT_DEVELOPMENT_LAND),
    (LandUseCategory.RESIDENTIAL_ZONE, LandUseCategory.MARKET_LAND),
    (LandUseCategory.CLASS_A_BUILDING_LAND, LandUseCategory.CLASS_B_BUILDING_LAND,
     LandUseCategory.SPECIFIC_PURPOSE_ZONE, LandUseCategory.MULTI_PURPOSE_PUBLIC_FACILITY_LAND),
    (LandUseCategory.INDUSTRIAL_ZONE, LandUseCategory.CLASS_C_BUILDING_LAND,
     LandUseCategory.CLASS_D_BUILDING_LAND),
    (LandUseCategory.OTHER_BUILDABLE_LAND,),
)


def grade_land_use(category: LandUseCategory) -> GradeResult:
    """使用分區／使用地類別（5 級制）。"""
    return _grade_from_groups(category, LandUseCategory, _LAND_USE_GROUPS, '使用分區或使用地類別')


def grade_building_coverage_rate(rate: Numeric) -> GradeResult:
    """建蔽率（5 級制）。

    Takes the statutory coverage ratio that has already been obtained from the
    urban plan or the non-urban land-use control regulations; this function does
    not derive it from areas.

    Args:
        rate: The statutory building coverage ratio, in percent.
    """
    return _grade_higher_is_better(rate, T.BUILDING_COVERAGE_RATE, '建蔽率')


def grade_floor_area_ratio(rate: Numeric) -> GradeResult:
    """容積率（5 級制）。Takes an already-obtained statutory ratio, in percent."""
    return _grade_higher_is_better(rate, T.FLOOR_AREA_RATIO, '容積率')


def grade_building_prohibition(prohibited: bool) -> GradeResult:
    """有無禁止建築。無禁建為優，有禁建為劣（2 級制）。"""
    return GradeResult.worst(2) if require_bool(prohibited, '有無禁止建築') else GradeResult.best(2)


_BUILDING_RESTRICTION_GROUPS: tuple[tuple[BuildingRestriction, ...], ...] = (
    (BuildingRestriction.NO_RESTRICTION,),
    (BuildingRestriction.PARTIAL_RESTRICTION,),
    (BuildingRestriction.OVERALL_DEVELOPMENT_RESTRICTION,),
)


def grade_building_restriction(restriction: BuildingRestriction) -> GradeResult:
    """有無限制建築（3 級制）。無限制為優、部分限制為普通、限制整體開發為劣。"""
    return _grade_from_groups(restriction, BuildingRestriction, _BUILDING_RESTRICTION_GROUPS, '有無限制建築')


# --------------------------------------------------------------------------- #
# 交通運輸
# --------------------------------------------------------------------------- #

def grade_main_road_width(width_m: Numeric) -> GradeResult:
    """主要道路寬度（5 級制），單位公尺。"""
    return _grade_higher_is_better(width_m, T.MAIN_ROAD_WIDTH, '主要道路寬度')


def grade_average_road_width(width_m: Numeric) -> GradeResult:
    """區段內道路平均寬度（5 級制），單位公尺。

    Expects the value produced by
    `calculations.calculate_average_road_width`; deriving the average and
    grading it stay separate steps.
    """
    return _grade_higher_is_better(width_m, T.AVERAGE_ROAD_WIDTH, '區段內道路平均寬度')


def grade_large_station(proximity: FacilityProximity) -> GradeResult:
    """接近大型車站之程度（5 級制）。"""
    return _grade_positive_facility_distance(proximity, T.LARGE_STATION_DISTANCE, '大型車站距離')


def grade_bus_stop_proximity(proximity: FacilityProximity) -> GradeResult:
    """站牌之接近程度（5 級制），依距離分級。

    The Shulin ordinary-residential schedule grades this row by distance. It
    provides no 密集程度（非常密集／密集／不密集）to grade mapping, so bus-stop
    density is deliberately not graded here.
    """
    return _grade_positive_facility_distance(proximity, T.BUS_STOP_DISTANCE, '站牌距離')


def grade_interchange(proximity: FacilityProximity) -> GradeResult:
    """接近交流道之程度（5 級制）。本項距離依明細表採直線距離。"""
    return _grade_positive_facility_distance(proximity, T.INTERCHANGE_DISTANCE, '交流道距離')


_ROAD_DEVELOPMENT_GROUPS: tuple[tuple[RoadDevelopmentLevel, ...], ...] = (
    (RoadDevelopmentLevel.FULLY_PLANNED_AND_DEVELOPED,),
    (RoadDevelopmentLevel.MOSTLY_PLANNED_AND_DEVELOPED,),
    (RoadDevelopmentLevel.PARTIALLY_PLANNED_AND_DEVELOPED,),
    (RoadDevelopmentLevel.GRAVEL_ROAD,),
    (RoadDevelopmentLevel.NOT_PLANNED_OR_DEVELOPED,),
)


def grade_road_development(level: RoadDevelopmentLevel) -> GradeResult:
    """區段內道路規劃及闢建程度（5 級制）。"""
    return _grade_from_groups(level, RoadDevelopmentLevel, _ROAD_DEVELOPMENT_GROUPS, '區段內道路規劃及闢建程度')


# --------------------------------------------------------------------------- #
# 自然條件
# --------------------------------------------------------------------------- #

_SUNLIGHT_GROUPS = tuple((level,) for level in (
    SunlightLevel.FULL, SunlightLevel.SLIGHT_SHADE, SunlightLevel.PARTIAL_SHADE,
    SunlightLevel.CONSIDERABLE_SHADE, SunlightLevel.MOSTLY_SHADED))

_LANDSCAPE_GROUPS = tuple((level,) for level in (
    LandscapeLevel.EXTREMELY_WIDE_AND_BEAUTIFUL, LandscapeLevel.WIDE_AND_BEAUTIFUL,
    LandscapeLevel.ACCEPTABLE, LandscapeLevel.POOR, LandscapeLevel.EXTREMELY_POOR))

_DRAINAGE_GROUPS = tuple((level,) for level in (
    DrainageLevel.EXTREMELY_COMPLETE, DrainageLevel.HIGHLY_COMPLETE,
    DrainageLevel.ORDINARY_COMPLETE, DrainageLevel.INADEQUATE,
    DrainageLevel.EXTREMELY_INADEQUATE))

_TERRAIN_GROUPS = tuple((level,) for level in (
    TerrainLevel.EXTREMELY_FLAT_AND_FIRM, TerrainLevel.FLAT, TerrainLevel.GENTLE_SLOPE,
    TerrainLevel.LOWLAND_OR_WETLAND, TerrainLevel.ISOLATED_AND_POOR))


def grade_sunlight(level: SunlightLevel) -> GradeResult:
    """日照（5 級制）。"""
    return _grade_from_groups(level, SunlightLevel, _SUNLIGHT_GROUPS, '日照')


def grade_landscape(level: LandscapeLevel) -> GradeResult:
    """景觀（5 級制）。"""
    return _grade_from_groups(level, LandscapeLevel, _LANDSCAPE_GROUPS, '景觀')


def grade_slope(degree: Numeric) -> GradeResult:
    """傾斜度（5 級制），單位度。平均坡度越小越優。"""
    return _grade_smaller_is_better(degree, T.SLOPE_DEGREE, '傾斜度')


def grade_drainage(level: DrainageLevel) -> GradeResult:
    """排水之良否（5 級制）。"""
    return _grade_from_groups(level, DrainageLevel, _DRAINAGE_GROUPS, '排水之良否')


def grade_terrain(level: TerrainLevel) -> GradeResult:
    """地勢（5 級制）。"""
    return _grade_from_groups(level, TerrainLevel, _TERRAIN_GROUPS, '地勢')


# --------------------------------------------------------------------------- #
# 土地改良
# --------------------------------------------------------------------------- #

def grade_building_site_improvement(completed_items: Collection[ImprovementType]) -> GradeResult:
    """建築基地改良或其他改良（5 級制），依已完成改良項目的種類數分級。

    Duplicate entries count once. 農地改良 belongs to a different row and must
    not be passed in, which the `ImprovementType` enum enforces.

    Args:
        completed_items: The completed improvement types.
    """
    if isinstance(completed_items, (str, bytes)) or not isinstance(completed_items, Collection):
        raise ValueError('已完成改良項目必須為集合。')
    unique = set()
    for item in completed_items:
        if not isinstance(item, ImprovementType):
            raise ValueError(f'改良項目不是已定義的類別：{item!r}')
        unique.add(item)
    return _grade_higher_is_better(len(unique), T.IMPROVEMENT_ITEM_COUNT, '已完成改良項目數')


# --------------------------------------------------------------------------- #
# 公共建設
# --------------------------------------------------------------------------- #

def grade_school_proximity(proximity: FacilityProximity) -> GradeResult:
    """接近學校之程度（5 級制）。"""
    return _grade_positive_facility_distance(proximity, T.SCHOOL_DISTANCE, '學校距離')


def grade_market_proximity(proximity: FacilityProximity) -> GradeResult:
    """接近市場之程度（5 級制）。"""
    return _grade_positive_facility_distance(proximity, T.MARKET_DISTANCE, '市場距離')


def grade_park_proximity(proximity: FacilityProximity) -> GradeResult:
    """接近公園、廣場、徒步區之程度（5 級制）。"""
    return _grade_positive_facility_distance(proximity, T.PARK_DISTANCE, '公園廣場徒步區距離')


def grade_tourism_facility_proximity(proximity: FacilityProximity) -> GradeResult:
    """接近觀光遊憩設施之程度（5 級制）。"""
    return _grade_positive_facility_distance(proximity, T.TOURISM_FACILITY_DISTANCE, '觀光遊憩設施距離')


def grade_parking_convenience(proximity: FacilityProximity) -> GradeResult:
    """停車場地之便利程度（5 級制）。"""
    return _grade_positive_facility_distance(proximity, T.PARKING_DISTANCE, '停車場地距離')


def grade_service_facility_proximity(proximity: FacilityProximity) -> GradeResult:
    """接近服務性設施之程度（5 級制），例如郵局、醫院、機關。"""
    return _grade_positive_facility_distance(proximity, T.SERVICE_FACILITY_DISTANCE, '服務性設施距離')


# --------------------------------------------------------------------------- #
# 特殊設施
# --------------------------------------------------------------------------- #

def grade_utility_facility_proximity(proximity: FacilityProximity) -> GradeResult:
    """電業設施及公用氣體燃料設施（5 級制），例如變電所、高壓鐵塔、瓦斯槽、儲油槽。越遠越優。"""
    return _grade_negative_facility_distance(proximity, T.NUISANCE_DISTANCE, '電業及公用氣體燃料設施距離')


def grade_funeral_facility_proximity(proximity: FacilityProximity) -> GradeResult:
    """殯葬設施（5 級制），例如墓地、殯儀館、火葬場、納骨塔。越遠越優。"""
    return _grade_negative_facility_distance(proximity, T.NUISANCE_DISTANCE, '殯葬設施距離')


def grade_waste_facility_proximity(proximity: FacilityProximity) -> GradeResult:
    """廢棄物處理設施（5 級制），例如污水處理場、垃圾場、掩埋場、焚化爐。越遠越優。"""
    return _grade_negative_facility_distance(proximity, T.NUISANCE_DISTANCE, '廢棄物處理設施距離')


# --------------------------------------------------------------------------- #
# 環境污染
# --------------------------------------------------------------------------- #

def grade_environment_pollution(proximity: FacilityProximity) -> GradeResult:
    """環境污染（5 級制）：水、噪音、廢氣、廢棄物等污染源之有無及接近程度。

    The schedule prices these pollution sources as one combined item, so this
    returns a single grade instead of one grade per pollution type; grading each
    type separately would apply the adjustment repeatedly.

    `proximity` must be the representative record decided upstream. This
    function does not choose among multiple sources, and in particular does not
    assume the nearest one applies.
    """
    return _grade_negative_facility_distance(proximity, T.NUISANCE_DISTANCE, '環境污染源距離')


# --------------------------------------------------------------------------- #
# 其他影響因素
# --------------------------------------------------------------------------- #

def grade_other_factor(label: GradeLabel) -> GradeResult:
    """其他影響因素（7 級制），採外部已判定的等級。

    Covers 寧適度、人文素質、明星學區、淹水程度、地震帶、重大工程規劃、聯外動線
    and similar. The schedule gives no measurable criteria, so the grade is not
    inferred from raw data here: the caller supplies the decided label and this
    function only places it in the 7-grade scheme.

    Args:
        label: One of the seven labels 極優／優／稍優／普通／稍劣／劣／極劣.
    """
    if not isinstance(label, GradeLabel):
        raise ValueError('其他影響因素等級必須為 GradeLabel。')
    scheme = GRADE_SCHEMES[7]
    if label not in scheme:
        raise ValueError('其他影響因素等級必須為極優、優、稍優、普通、稍劣、劣或極劣。')
    return GradeResult.of(scheme.index(label) + 1, 7)
