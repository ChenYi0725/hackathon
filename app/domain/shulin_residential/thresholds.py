"""Grade cut points transcribed from the 備註 column of
《新北市樹林區普通住宅用地影響地價區域因素評價基準明細表》pages 4-26 to 4-30.

Values are `Decimal` built from strings so that a measured value lands on the
published boundary exactly, per `app/domain/AGENTS.md`.

Two conventions are used, both holding `count - 1` cut points for a
`count`-grade scheme:

- `HIGHER_IS_BETTER`: strictly descending. `value >= t[0]` is grade 1, and a
  value below every cut point falls into the last grade.
- `SMALLER_IS_BETTER`: strictly ascending. `value < t[0]` is grade 1, and a
  value at or above every cut point falls into the last grade.

Callers never pass thresholds in; the Shulin rules live here.
"""
from decimal import Decimal


def _cuts(*values: str) -> tuple[Decimal, ...]:
    """Build a cut-point tuple from the printed figures, never via float."""
    return tuple(Decimal(v) for v in values)


# --- 土地使用管制, p. 4-26 (higher is better) ---
#: 優 80%以上／稍優 70%以上未滿80%／普通 60%以上未滿70%／稍劣 50%以上未滿60%／劣 未滿50%
BUILDING_COVERAGE_RATE = _cuts('80', '70', '60', '50')
#: 優 460%以上／稍優 360%以上未滿460%／普通 260%以上未滿360%／稍劣 180%以上未滿260%／劣 未滿180%
FLOOR_AREA_RATIO = _cuts('460', '360', '260', '180')

# --- 交通運輸, p. 4-27 ---
#: 主要道路寬度：優 28m以上／稍優 20m以上未滿28m／普通 12m以上未滿20m／稍劣 8m以上未滿12m／劣 未滿8m
MAIN_ROAD_WIDTH = _cuts('28', '20', '12', '8')
#: 區段內已開闢道路平均寬度：優 20m以上／稍優 15m以上未滿20m／普通 10m以上未滿15m／稍劣 8m以上未滿10m／劣 未滿8m
AVERAGE_ROAD_WIDTH = _cuts('20', '15', '10', '8')
#: 接近大型車站：優 區段內有或未滿500m ... 劣 2000m以上或無
LARGE_STATION_DISTANCE = _cuts('500', '1000', '1500', '2000')
#: 站牌之接近程度：優 區段內有站牌或未滿200m ... 劣 800m以上或無
BUS_STOP_DISTANCE = _cuts('200', '400', '600', '800')
#: 接近交流道：以各地價區段至交流道直線距離計算。優 區段內有或未滿1000m ... 劣 4000m以上或無
INTERCHANGE_DISTANCE = _cuts('1000', '2000', '3000', '4000')

# --- 自然條件, p. 4-28 ---
#: 傾斜度：優 平均坡度未滿5度 ... 劣 平均坡度20度以上
SLOPE_DEGREE = _cuts('5', '10', '15', '20')

# --- 土地改良, p. 4-28 (higher is better, unique completed item count) ---
#: 建築基地改良或其他改良：優 四項以上／稍優 三項／普通 二項／稍劣 一項／劣 無
IMPROVEMENT_ITEM_COUNT = _cuts('4', '3', '2', '1')

# --- 公共建設, p. 4-29 (smaller is better, m) ---
#: 接近學校（國小、國中、高中或大專院校）：優 區段內有或未滿300m ... 劣 1000m以上或無
SCHOOL_DISTANCE = _cuts('300', '500', '800', '1000')
#: 接近市場（傳統市場、超級市場或超大型購物中心）：同學校級距
MARKET_DISTANCE = _cuts('300', '500', '800', '1000')
#: 接近鄰里公園、一般公園、廣場、徒步區：同學校級距
PARK_DISTANCE = _cuts('300', '500', '800', '1000')
#: 接近觀光遊憩設施：優 區段內有或未滿500m ... 劣 2000m以上或無
TOURISM_FACILITY_DISTANCE = _cuts('500', '1000', '1500', '2000')
#: 停車場地之便利程度：優 區段內有停車位或未滿200m ... 稍劣 600m以上未滿1000m／劣 1000m以上或無
PARKING_DISTANCE = _cuts('200', '400', '600', '1000')
#: 接近服務性設施（郵局、醫院、機關等）：優 區段內有或未滿500m ... 劣 2000m以上或無
SERVICE_FACILITY_DISTANCE = _cuts('500', '1000', '1500', '2000')

# --- 特殊設施及環境污染, p. 4-30 (farther is better, m) ---
#: 優 2000m以上或無／稍優 1500m以上未滿2000m／普通 1000m以上未滿1500m／
#: 稍劣 500m以上未滿1000m／劣 區段內有或距離未滿500m。
#: Shared by 電業及公用氣體燃料設施、殯葬設施、廢棄物處理設施 and 環境污染;
#: the four rows differ only in their price-adjustment matrix.
NUISANCE_DISTANCE = _cuts('2000', '1500', '1000', '500')
