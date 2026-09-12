"""新北市樹林區普通住宅用地：表3 地價區段勘查表衍生欄位、優劣等級與價格修正率。

Grade bands and price-adjustment matrices are transcribed from, and have been
checked against,《新北市樹林區普通住宅用地影響地價區域因素評價基準明細表》
pages 4-26 to 4-30. Adjustment rates are `Decimal`, per `app/domain/AGENTS.md`.

Pure domain code, following `app/domain/AGENTS.md`: no imports of application,
infrastructure or interfaces, no network, file or AI access.

The three responsibilities are kept in separate layers so each stays testable:

```text
raw data --calculations--> derived value --grading--> GradeResult
GradeResult x GradeResult + matrix --adjustments--> adjustment rate (%)
```

Typical use:

```python
average = calculate_average_road_width([6.0, 8.0])
target = grade_average_road_width(average)
benchmark = grade_average_road_width(12.0)
rate = calculate_adjustment_rate(target, benchmark, AVERAGE_ROAD_WIDTH_MATRIX)
```

建蔽率 and 容積率 are graded but never derived here; the statutory ratios come
from the urban plan or the non-urban land-use control regulations. 表3 fields the
Shulin ordinary-residential schedule does not list as evaluation items are
recorded but not graded, see `grading.UNGRADED_SURVEY_FIELDS`.

`GRADE_SCHEMES` covers the 2／3／5／7-grade schemes used by this ruleset.
"""
from app.domain.shulin_residential.adjustments import calculate_adjustment_rate
from app.domain.shulin_residential.calculations import (
    calculate_average_road_width,
    calculate_building_density,
    calculate_straight_line_distance,
)
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
from app.domain.shulin_residential.grading import (
    UNGRADED_SURVEY_FIELDS,
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
from app.domain.shulin_residential.models import (
    GRADE_SCHEMES,
    FacilityProximity,
    GradeResult,
)

RULESET_ID = 'shulin-residential-v1'
LOCALITY = '新北市樹林區'
LAND_USE = '普通住宅用地'

__all__ = [
    'RULESET_ID', 'LOCALITY', 'LAND_USE',
    'GRADE_SCHEMES', 'GradeResult', 'FacilityProximity', 'GradeLabel',
    'BuildingRestriction', 'DrainageLevel', 'ImprovementType', 'LandscapeLevel',
    'LandUseCategory', 'RoadDevelopmentLevel', 'SunlightLevel', 'TerrainLevel',
    'calculate_average_road_width', 'calculate_building_density',
    'calculate_straight_line_distance', 'calculate_adjustment_rate',
    'UNGRADED_SURVEY_FIELDS',
    'grade_urban_planning', 'grade_land_use', 'grade_building_coverage_rate',
    'grade_floor_area_ratio', 'grade_building_prohibition', 'grade_building_restriction',
    'grade_main_road_width', 'grade_average_road_width', 'grade_large_station',
    'grade_bus_stop_proximity', 'grade_interchange', 'grade_road_development',
    'grade_sunlight', 'grade_landscape', 'grade_slope', 'grade_drainage', 'grade_terrain',
    'grade_building_site_improvement',
    'grade_school_proximity', 'grade_market_proximity', 'grade_park_proximity',
    'grade_tourism_facility_proximity', 'grade_parking_convenience',
    'grade_service_facility_proximity',
    'grade_utility_facility_proximity', 'grade_funeral_facility_proximity',
    'grade_waste_facility_proximity', 'grade_environment_pollution', 'grade_other_factor',
]
