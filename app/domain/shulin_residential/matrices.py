"""Price-adjustment matrices transcribed from the 價格修正率 column of
《新北市樹林區普通住宅用地影響地價區域因素評價基準明細表》pages 4-26 to 4-30.

Direction matches the schedule's own row/column headings and the existing project
convention in `app/domain/rules.py`: row = 目標區段, column = 基準區段, values are
percentage points.

Every cell is a `Decimal` built from the printed string, never via `float`, per
`app/domain/AGENTS.md`. Rows are written out as they are printed, including the
sign, so a reviewer can diff a row against the source page directly; nothing is
regenerated from a step, which is what keeps 3.33 / 6.67 / 13.33 / 16.67 in the
其他影響因素 table exact.
"""
from decimal import Decimal

Matrix = tuple[tuple[Decimal, ...], ...]


def _matrix(*rows: str) -> Matrix:
    """Build a square matrix from the printed rows of the schedule."""
    return tuple(tuple(Decimal(cell) for cell in row.split()) for row in rows)


# ------------------------------------------------------- 土地使用管制, p. 4-26
URBAN_PLANNING_MATRIX: Matrix = _matrix(
    '  0  +20',
    '-20    0',
)

LAND_USE_MATRIX: Matrix = _matrix(
    '  0   +5  +10  +15  +20',
    ' -5    0   +5  +10  +15',
    '-10   -5    0   +5  +10',
    '-15  -10   -5    0   +5',
    '-20  -15  -10   -5    0',
)

BUILDING_COVERAGE_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

FLOOR_AREA_RATIO_MATRIX: Matrix = _matrix(
    '     0  +6.25  +12.50  +18.75  +25',
    ' -6.25      0   +6.25  +12.50  +18.75',
    ' -12.5  -6.25       0   +6.25  +12.50',
    '-18.75  -12.5   -6.25       0   +6.25',
    '   -25 -18.75   -12.5   -6.25       0',
)

BUILDING_PROHIBITION_MATRIX: Matrix = _matrix(
    '  0  +50',
    '-50    0',
)

BUILDING_RESTRICTION_MATRIX: Matrix = _matrix(
    '  0  +25  +50',
    '-25    0  +25',
    '-50  -25    0',
)

# --------------------------------------------------------- 交通運輸, p. 4-27
MAIN_ROAD_WIDTH_MATRIX: Matrix = _matrix(
    '     0  +3.75    +7.5  +11.25  +15',
    ' -3.75      0   +3.75    +7.5  +11.25',
    '  -7.5  -3.75       0   +3.75   +7.5',
    '-11.25   -7.5   -3.75       0   +3.75',
    '   -15 -11.25    -7.5   -3.75      0',
)

AVERAGE_ROAD_WIDTH_MATRIX: Matrix = _matrix(
    '  0   +3   +6   +9  +12',
    ' -3    0   +3   +6   +9',
    ' -6   -3    0   +3   +6',
    ' -9   -6   -3    0   +3',
    '-12   -9   -6   -3    0',
)

LARGE_STATION_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

BUS_STOP_MATRIX: Matrix = _matrix(
    ' 0  +1  +2  +3  +4',
    '-1   0  +1  +2  +3',
    '-2  -1   0  +1  +2',
    '-3  -2  -1   0  +1',
    '-4  -3  -2  -1   0',
)

INTERCHANGE_MATRIX: Matrix = _matrix(
    ' 0  +1  +2  +3  +4',
    '-1   0  +1  +2  +3',
    '-2  -1   0  +1  +2',
    '-3  -2  -1   0  +1',
    '-4  -3  -2  -1   0',
)

ROAD_DEVELOPMENT_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

# --------------------------------------------------------- 自然條件, p. 4-28
SUNLIGHT_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

LANDSCAPE_MATRIX: Matrix = _matrix(
    '    0  +1.25  +2.5  +3.75   +5',
    '-1.25      0  +1.25  +2.5  +3.75',
    ' -2.5  -1.25      0  +1.25  +2.5',
    '-3.75   -2.5  -1.25      0  +1.25',
    '   -5  -3.75   -2.5  -1.25     0',
)

SLOPE_MATRIX: Matrix = _matrix(
    '     0  +3.75    +7.5  +11.25  +15',
    ' -3.75      0   +3.75    +7.5  +11.25',
    '  -7.5  -3.75       0   +3.75   +7.5',
    '-11.25   -7.5   -3.75       0   +3.75',
    '   -15 -11.25    -7.5   -3.75      0',
)

DRAINAGE_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

TERRAIN_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

# --------------------------------------------------------- 土地改良, p. 4-28
SITE_IMPROVEMENT_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

# --------------------------------------------------------- 公共建設, p. 4-29
SCHOOL_MATRIX: Matrix = _matrix(
    ' 0  +2  +4  +6  +8',
    '-2   0  +2  +4  +6',
    '-4  -2   0  +2  +4',
    '-6  -4  -2   0  +2',
    '-8  -6  -4  -2   0',
)

MARKET_MATRIX: Matrix = SCHOOL_MATRIX

PARK_MATRIX: Matrix = SCHOOL_MATRIX

TOURISM_FACILITY_MATRIX: Matrix = _matrix(
    '   0  +1.5    +3  +4.5   +6',
    '-1.5     0  +1.5    +3  +4.5',
    '  -3  -1.5     0  +1.5   +3',
    '-4.5    -3  -1.5     0  +1.5',
    '  -6  -4.5    -3  -1.5    0',
)

PARKING_MATRIX: Matrix = TOURISM_FACILITY_MATRIX

SERVICE_FACILITY_MATRIX: Matrix = TOURISM_FACILITY_MATRIX

# --------------------------------------------------------- 特殊設施, p. 4-30
UTILITY_FACILITY_MATRIX: Matrix = _matrix(
    '    0  +2.5    +5  +7.5  +10',
    ' -2.5     0  +2.5    +5  +7.5',
    '   -5  -2.5     0  +2.5   +5',
    ' -7.5    -5  -2.5     0  +2.5',
    '  -10  -7.5    -5  -2.5    0',
)

FUNERAL_FACILITY_MATRIX: Matrix = UTILITY_FACILITY_MATRIX

WASTE_FACILITY_MATRIX: Matrix = _matrix(
    '     0  +3.75    +7.5  +11.25  +15',
    ' -3.75      0   +3.75    +7.5  +11.25',
    '  -7.5  -3.75       0   +3.75   +7.5',
    '-11.25   -7.5   -3.75       0   +3.75',
    '   -15 -11.25    -7.5   -3.75      0',
)

# --------------------------------------------------------- 環境污染, p. 4-30
#: 水污染、噪音污染、廢氣污染、廢棄物污染等之有無及接近程度，合併為單一修正項目。
ENVIRONMENT_POLLUTION_MATRIX: Matrix = _matrix(
    '    0   +5  +10  +15  +20',
    '   -5    0   +5  +10  +15',
    '  -10   -5    0   +5  +10',
    '  -15  -10   -5    0   +5',
    '  -20  -15  -10   -5    0',
)

# ----------------------------------------------------- 其他影響因素, p. 4-30
#: 7-grade 極優／優／稍優／普通／稍劣／劣／極劣. Printed values are kept verbatim;
#: do not regenerate as grade_difference * 3.33.
OTHER_FACTOR_MATRIX: Matrix = _matrix(
    '     0    3.33    6.67      10   13.33   16.67   20',
    ' -3.33       0    3.33    6.67      10   13.33   16.67',
    ' -6.67   -3.33       0    3.33    6.67      10   13.33',
    '   -10   -6.67   -3.33       0    3.33    6.67   10',
    '-13.33     -10   -6.67   -3.33       0    3.33   6.67',
    '-16.67  -13.33     -10   -6.67   -3.33       0   3.33',
    '   -20  -16.67  -13.33     -10   -6.67   -3.33    0',
)
