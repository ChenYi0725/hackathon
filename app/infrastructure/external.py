"""Official facility candidates and explicit synthetic diagnostics; no Google data retained."""
import math
from datetime import datetime, timezone
import httpx
from pyproj import Geod

PARKS = 'https://data.ntpc.gov.tw/api/datasets/5fe3a136-29cc-4695-a17e-6636a32c3342/json'


def measure(query):
    if query.get('method') != 'straight_line' or query.get('crs') not in ('EPSG:4326', 'EPSG:3826'):
        raise ValueError('僅支援明確 CRS 的直線距離；不以直線距離冒充步行路程。')
    points = []
    for key in ('start', 'end'):
        point = query.get(key, {})
        if point.get('role') not in ('entrance', 'boundary', 'survey_point'):
            raise ValueError('需入口、邊界或實測起訖點；POI 中心點不可代替。')
        xy = point.get('coordinates')
        if not isinstance(xy, list) or len(xy) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in xy):
            raise ValueError('缺少有效起訖座標。')
        if query['crs'] == 'EPSG:4326' and not (-180 <= xy[0] <= 180 and -90 <= xy[1] <= 90):
            raise ValueError('經緯度超出範圍；座標順序為經度、緯度。')
        points.append(xy)
    if query['crs'] == 'EPSG:4326':
        distance = abs(Geod(ellps='WGS84').inv(*points[0], *points[1])[2])
        method = 'WGS84 ellipsoid geodesic'
    else:
        distance = math.dist(*points)
        method = 'TWD97 TM2 zone 121 planar Euclidean'
    return dict(distance_m=distance, unit='m', method=method, crs=query['crs'], start=query['start'], end=query['end'])


class OfficialEvidenceAdapter:
    def __init__(self, client=None):
        self.client = client

    def query(self, query):
        mode = query.get('mode', 'live')
        base = dict(mode=mode, check_status='pending', data_date=None, source=PARKS,
                    message='官方候選清冊不能證明案件時點存在、入口位置或沒有設施。')
        if mode == 'mock':
            status = query.get('scenario', 'no_match')
            if status not in ('no_match', 'unauthorized', 'timeout', 'unavailable'):
                raise ValueError('未知 mock 情境。')
            return dict(base, status=status, source='synthetic-fixture', message='合成診斷：' + status + '；不作真實查證通過依據。', candidates=[])
        if mode == 'geometry':
            measured = measure(query)
            return dict(base, source=query.get('source', 'manual'), status='measured', geometry=measured,
                        measured_value=measured['distance_m'], data_date=query.get('data_date'),
                        message='程式已完成直線距離計算；起訖位置、來源及案件日期仍須人工核對。')
        if mode != 'live':
            raise ValueError('mode 必須為 live、mock 或 geometry。')
        if query.get('dataset', 'parks') != 'parks':
            return dict(base, status='unsupported', message='此官方資料 adapter 尚未支援該資料集。', candidates=[])
        name = str(query.get('name', '')).strip()
        if not name or len(name) > 100:
            raise ValueError('請提供 1–100 字的公園名稱查詢條件。')
        client = self.client or httpx.Client(timeout=8, follow_redirects=False)
        try:
            candidates = []
            truncated = True
            for page in range(3):
                response = client.get(PARKS, params=dict(page=page, size=100))
                if response.status_code in (401, 403):
                    return dict(base, status='unauthorized', message='官方 API 未授權；不代表沒有設施。', candidates=[])
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError('response too large')
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError('invalid schema')
                for row in rows:
                    if not isinstance(row, dict) or 'name' not in row:
                        raise ValueError('invalid schema')
                    if name in str(row['name']):
                        candidates.append({k: row.get(k) for k in ('seqno', 'name', 'area', 'address', 'areacode')})
                if len(rows) < 100:
                    truncated = False
                    break
            return dict(base, status='candidates' if candidates else 'incomplete' if truncated else 'no_match',
                        candidates=candidates[:100], truncated=truncated, retrieved_at=datetime.now(timezone.utc).isoformat())
        except httpx.TimeoutException:
            return dict(base, status='timeout', message='官方 API 逾時，其他表內檢核可繼續。', candidates=[])
        except (httpx.HTTPError, ValueError):
            return dict(base, status='unavailable', message='官方 API 失敗或格式不符，不能認定沒有設施。', candidates=[])
        finally:
            if self.client is None:
                client.close()
