"""新北市各行政區查估資料查詢函式；僅使用 Python 標準函式庫，import 不會連線。

命令列：
    python ntpc_shulin_api.py --area 樹林區 --school-year 111 --out-dir opendata
    python ntpc_shulin_api.py --area 金山區 --school-year 111
    python ntpc_shulin_api.py --area 板橋區 --include-heavy   # 併抓公車站位、工廠登記
    python ntpc_shulin_api.py --list-areas                   # 列出 29 個行政區

在 Python 中呼叫：
    from ntpc_shulin_api import (
        search_ntpc_datasets, search_all_ntpc_datasets, search_district_datasets,
        fetch_ntpc_dataset, fetch_valuation_factors, save_json, summarize,
    )
    report = fetch_valuation_factors("金山區", school_year=111)
    print(summarize(report))
    save_json(report, "金山區查估因素.json")   # UTF-8 中文 JSON

涵蓋範圍對應表3 地價區段勘查表與表5-1 影響地價區域因素分析明細表：
    交通運輸(2)  大型車站、站牌、交流道
    公共建設(5)  學校、市場、公園廣場徒步區、觀光遊憩設施、停車場地、服務性設施
    特殊設施(6)  電業及公用氣體燃料設施、殯葬設施、廢棄物處理設施
    環境污染(7)  水污染、噪音污染、廢氣污染、廢棄物污染、其他污染
    工商活動     百貨公司、金融機構、娛樂設施、大型展示中心或觀光飯店、
                 顧客之通行量、店舖之叫座狀態
    其他         電力資源、產業用水及設施、寺廟等周邊環境設施

沒有開放資料的欄位不會回傳空清單就算了，而是標記 status="no_open_data_source"
且 survey_required=True，避免誤把「查無資料」當成勘查表上的「無」。

資料來源：
    新北市資料開放平臺 OpenAPI：https://data.ntpc.gov.tw/api/v1/openapi/units/{機關代碼}
    各級學校名錄（教育部統計處）：https://stats.moe.gov.tw/files/
注意：學校可指定學年度；其餘 NTPC 資料集為 API 取得當下版本，不能視為特定年度歷史
資料。「普通住宅用地」是查估情境，不是這些 API 的篩選參數，也不能據此認定任何地號的
法定使用分區。行政區不等於地價區段。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID


NTPC_BASE = "https://data.ntpc.gov.tw"
CITY_NAME = "新北市"
LAND_UNIT_ID = "1110000"  # Swagger 的機關 API ID，非畫面分類代碼 1002。

# 實測可用的機關代碼（掃描 1000000~1440000 得到）。
NTPC_UNITS = {
    "1010000": "民政局", "1020000": "財政局", "1030000": "經濟發展局",
    "1040000": "觀光旅遊局", "1050000": "教育局", "1060000": "工務局",
    "1070000": "水利局", "1080000": "農業局", "1090000": "城鄉發展局",
    "1100000": "社會局", "1110000": "地政局", "1120000": "勞工局",
    "1130000": "交通局", "1140000": "新聞局", "1150000": "法制局",
    "1160000": "研究發展考核委員會", "1170000": "原住民族行政局",
    "1180000": "主計處", "1190000": "人事處", "1200000": "政風處",
    "1210000": "客家事務局", "1220000": "環境保護局", "1230000": "文化局",
    "1240000": "衛生局", "1250000": "警察局", "1260000": "消防局",
    "1280000": "捷運工程局",
}

# 新北市 29 個行政區。改制前為臺北縣轄下的市、鎮、鄉，舊資料仍可能沿用。
NTPC_DISTRICTS = (
    "板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "土城區",
    "蘆洲區", "樹林區", "汐止區", "鶯歌區", "三峽區", "淡水區", "瑞芳區",
    "五股區", "泰山區", "林口區", "深坑區", "石碇區", "坪林區", "三芝區",
    "石門區", "八里區", "平溪區", "雙溪區", "貢寮區", "金山區", "萬里區",
    "烏來區",
)

MARKET_DATASET_ID = "785be91a-caaf-4e1c-91d6-f7d616d31a45"
PARK_DATASET_ID = "5fe3a136-29cc-4695-a17e-6636a32c3342"

# 樹林區的分區資料集範例。其他行政區請用 search_district_datasets() 查對應 ID。
SHULIN_DATASET_EXAMPLES = {
    "sales_current": "ef459e3b-202c-4886-87a2-bf6fc54bb569",
    "rentals_current": "5588f4c3-b929-4fe9-b420-0d7960b20b6f",
    "presales_current": "ccf7e380-0030-492f-8186-e1839b8b3bd6",
    "sales_111": "16bb81d0-13c1-43b0-866f-9824766845cc",
    "land_sections": "1fcc8dd3-d295-4102-b52c-f809794e4cd9",
    "announced_expropriations": "6872742e-b379-4840-81b8-e4298cc50dcf",
}


# --------------------------------------------------------------------------
# 行政區比對
# --------------------------------------------------------------------------
def normalize_district(district: str) -> str:
    """把「金山」「金山區」「新北市金山區」正規化為「金山區」。"""
    if not isinstance(district, str):
        raise ValueError("district 必須是字串，例如 '金山區'。")
    text = district.strip().replace(" ", "")
    for prefix in (CITY_NAME, "臺北縣", "台北縣"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text in NTPC_DISTRICTS:
        return text
    for suffix in ("區", "市", "鎮", "鄉"):
        if text.endswith(suffix) and f"{text[:-1]}區" in NTPC_DISTRICTS:
            return f"{text[:-1]}區"
    if f"{text}區" in NTPC_DISTRICTS:
        return f"{text}區"
    raise ValueError(
        f"'{district}' 不是新北市行政區。可用值：{'、'.join(NTPC_DISTRICTS)}")


def _field_forms(district: str) -> set[str]:
    """行政區欄位可能出現的寫法。改制前的市／鎮／鄉舊名一併認可。"""
    bare = district[:-1]
    return {district, bare, f"{bare}市", f"{bare}鎮", f"{bare}鄉"}


# 全部 29 區的欄位寫法，用來判斷「這欄位已宣告為某個行政區」。
_ANY_DISTRICT_FIELD_VALUES = frozenset(
    form for d in NTPC_DISTRICTS for form in _field_forms(d))
# 帶「區／市／鎮／鄉」的完整寫法，可用於前綴比對；不含只有二字的簡稱。
_ANY_DISTRICT_PREFIXES = tuple(sorted(
    form for form in _ANY_DISTRICT_FIELD_VALUES if len(form) > 2))
# 行政區欄位可能並列多區，例如區域排水的「泰山區、五股區」。
# 只用標點與空白切分：不可加入「和」「與」「及」，否則會把中和區、永和區切壞。
_DISTRICT_SEPARATORS = re.compile(r"[、,，/／|｜;；\s]+")


class DistrictMatcher:
    """依行政區產生比對規則。

    三層比對，優先度由高而低：
      district_field 資料集自帶的行政區欄位相符（最可靠，支援多區並列）
      address        地址含「○○區」「○○市」等完整行政區名
      name_keyword   僅名稱含行政區字樣（寬鬆，須人工覆核）

    行政區欄位優先：欄位已明確宣告為其他行政區時不再退回地址比對。
    否則跨區設施會被兩邊重複認領，例如路外停車場「板樹停車場」
    AREA=樹林區、地址寫「樹林區水源街及板橋區溪城路」。

    寬鬆比對容易誤收：淡水「紅樹林」含「樹林」、林口舊稱「樹林口」、
    新店「大坪林」含「坪林」、台北「金山南路」含「金山」。本類別不維護
    排除字典，而是由嚴格比對結果的座標推出參考範圍再回頭驗證，
    見 fetch_valuation_factors() 的 reference_bbox。
    """

    __slots__ = ("district", "bare", "full_name", "field_values",
                 "field_prefixes", "address_re", "loose_re", "school_address_re")

    def __init__(self, district: str):
        self.district = normalize_district(district)
        self.bare = self.district[:-1]
        self.full_name = f"{CITY_NAME}{self.district}"
        bare = re.escape(self.bare)
        self.field_values = frozenset(_field_forms(self.district))
        # 欄位值常帶後綴，例如路邊停車的「板橋區機車收費」；只有完整寫法
        # 才做前綴比對，簡稱「樹林」不可，否則「樹林口公園」會被誤收。
        self.field_prefixes = tuple(sorted(
            form for form in self.field_values if len(form) > 2))
        self.address_re = re.compile(rf"{bare}(?:區|市|鎮|鄉)")
        self.loose_re = re.compile(bare)
        self.school_address_re = re.compile(
            rf"^(?:\[\d+\])?\s*{re.escape(CITY_NAME)}{re.escape(self.district)}")

    def _claimed_by_self(self, token: str) -> bool:
        return token in self.field_values or token.startswith(self.field_prefixes)

    def match(self, row: dict, source: dict) -> str | None:
        declared_elsewhere = False
        for key in source["district_keys"]:
            value = row.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            tokens = [t for t in _DISTRICT_SEPARATORS.split(text) if t]
            if any(self._claimed_by_self(token) for token in tokens):
                return "district_field"
            if any(token in _ANY_DISTRICT_FIELD_VALUES
                   or token.startswith(_ANY_DISTRICT_PREFIXES)
                   for token in tokens):
                declared_elsewhere = True
        if declared_elsewhere:
            # 欄位已表明屬於他區，地址提到本區多半是「○○區與××區交界」之類敘述。
            return None
        for key in source["address_keys"]:
            value = row.get(key)
            if value is not None and self.address_re.search(str(value)):
                return "address"
        if source["loose_name_match"]:
            for key in source["name_keys"]:
                value = row.get(key)
                if value is not None and self.loose_re.search(str(value)):
                    return "name_keyword"
        return None


# --------------------------------------------------------------------------
# 低階存取
# --------------------------------------------------------------------------
def _read_url(url: str, timeout: float) -> str:
    if timeout <= 0:
        raise ValueError("timeout 必須大於 0。")
    request = Request(url, headers={"User-Agent": "NtpcOpenData/3.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            # 避免錯誤端點或異常回應無限制占用記憶體。
            limit = 64 * 1024 * 1024
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError(f"回應超過 64 MiB：{url}")
        return body.decode("utf-8-sig")
    except (URLError, OSError, UnicodeError) as exc:
        raise RuntimeError(f"無法讀取公開資料 {url}：{exc}") from exc


def _get_json(url: str, timeout: float):
    try:
        return json.loads(_read_url(url, timeout))
    except json.JSONDecodeError as exc:
        raise ValueError(f"來源沒有回傳有效 JSON（可能是維護頁面）：{url}") from exc


def _validate_rows(rows, source: str, required: tuple[str, ...] = ()) -> list[dict]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"來源格式已改變，預期為 JSON 物件陣列：{source}")
    if any(any(key not in row for key in required) for row in rows):
        raise ValueError(f"來源缺少必要欄位 {required}：{source}")
    return rows


def _swagger_datasets(unit_id: str, timeout: float) -> list[dict]:
    if not isinstance(unit_id, str) or not re.fullmatch(r"\d{7}", unit_id):
        raise ValueError("unit_id 應為七位數字字串，例如 '1110000'。")
    spec_url = f"{NTPC_BASE}/api/v1/openapi/units/{unit_id}"
    spec = _get_json(spec_url, timeout)
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ValueError(f"Swagger 缺少 paths：{spec_url}")
    result = []
    for path, operations in spec["paths"].items():
        match = re.fullmatch(r"/api/datasets/([0-9a-fA-F-]{36})/json", path)
        if not match:
            continue
        operation = operations.get("get", {})
        dataset_id = str(UUID(match.group(1)))
        result.append({
            "dataset_id": dataset_id,
            "unit_id": unit_id,
            "unit_name": NTPC_UNITS.get(unit_id, ""),
            "name": operation.get("summary") or "",
            "description": operation.get("description") or "",
            "json_url": f"{NTPC_BASE}{path}",
            "csv_url": f"{NTPC_BASE}/api/datasets/{dataset_id}/csv",
            "source_page": f"{NTPC_BASE}/datasets/{dataset_id}",
            "parameters": operation.get("parameters", []),
        })
    return result


def search_ntpc_datasets(
    keyword: str = "", *, unit_id: str = LAND_UNIT_ID, timeout: float = 20
) -> list[dict]:
    """搜尋單一機關 Swagger 的資料集名稱／說明；keyword='' 列出整個機關。

    unit_id 見 NTPC_UNITS，例如地政局 1110000、環保局 1220000、交通局 1130000。
    這是「目錄搜尋」，名稱含某行政區的資料集也可能涵蓋鄰區；
    不代表該資料集每一筆都在該行政區。description 保留官方欄位說明。
    """
    if not isinstance(keyword, str):
        raise ValueError("keyword 必須是字串；空字串代表整個機關目錄。")
    needle = keyword.casefold()
    result = [
        item for item in _catalog_cached(unit_id, timeout)
        if needle in f"{item['name']} {item['description']}".casefold()
    ]
    return sorted(result, key=lambda item: (item["name"], item["dataset_id"]))


def search_all_ntpc_datasets(
    keyword: str = "", *, timeout: float = 30, strict: bool = False
) -> list[dict]:
    """跨全部機關搜尋資料集目錄；keyword='' 會列出全部（約 2900 筆）。

    strict=False 時個別機關失敗只跳過；strict=True 直接拋出例外。
    """
    if not isinstance(keyword, str):
        raise ValueError("keyword 必須是字串；空字串代表全部資料集。")
    needle = keyword.casefold()
    result = []
    for unit_id in NTPC_UNITS:
        try:
            items = _catalog_cached(unit_id, timeout)
        except (RuntimeError, ValueError):
            if strict:
                raise
            continue
        result.extend(
            item for item in items
            if needle in f"{item['name']} {item['description']}".casefold()
        )
    return sorted(result, key=lambda item: (item["unit_id"], item["name"]))


def search_district_datasets(
    district: str, keyword: str = "", *, timeout: float = 30
) -> list[dict]:
    """找出以「-○○區」結尾的分區資料集，例如各年度公告土地現值、實價登錄。

    平臺上許多資料集同時有全市版與分區版；分區版筆數少、抓取快。
    keyword 可再過濾，例如 search_district_datasets("金山區", "實價登錄")。
    """
    name = normalize_district(district)
    suffixes = (f"-{name}", f"-{name[:-1]}")
    needle = keyword.casefold()
    return [
        item for item in search_all_ntpc_datasets(timeout=timeout)
        if item["name"].endswith(suffixes)
        and needle in f"{item['name']} {item['description']}".casefold()
    ]


# --------------------------------------------------------------------------
# 資料集快取
# --------------------------------------------------------------------------
# 多數資料集是全市範圍，換行政區時可完全重用；抓一個區約 40 個請求，
# 開快取後第二個區幾乎不需連線。以列數計上限，避免公車站位這種
# 三萬多筆的資料集把記憶體吃光。
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_SETTINGS = {"enabled": False, "ttl": 3600.0, "max_rows": 250_000}


def enable_dataset_cache(enabled: bool = True, *, ttl: float = 3600.0,
                         max_rows: int = 250_000) -> None:
    """開啟或關閉資料集快取。ttl 為秒數，max_rows 為快取總列數上限。"""
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必須是布林值。")
    if not isinstance(ttl, (int, float)) or ttl <= 0:
        raise ValueError("ttl 必須大於 0。")
    if type(max_rows) is not int or max_rows < 1:
        raise ValueError("max_rows 必須是正整數。")
    with _CACHE_LOCK:
        _CACHE_SETTINGS.update(enabled=enabled, ttl=float(ttl), max_rows=max_rows)
        if not enabled:
            _CACHE.clear()
            _CATALOG_CACHE.clear()


def clear_dataset_cache() -> int:
    """清空快取，回傳清掉的資料集數。"""
    with _CACHE_LOCK:
        count = len(_CACHE) + len(_CATALOG_CACHE)
        _CACHE.clear()
        _CATALOG_CACHE.clear()
    return count


def dataset_cache_info() -> dict:
    """回報快取狀態，供 API 或除錯使用。"""
    now = time.monotonic()
    with _CACHE_LOCK:
        entries = [
            {"dataset_id": key, "rows": len(rows), "age_s": round(now - stamp, 1)}
            for key, (stamp, rows) in _CACHE.items()
        ]
        settings = dict(_CACHE_SETTINGS)
        catalog_units = len(_CATALOG_CACHE)
        catalog_rows = sum(len(items) for _, items in _CATALOG_CACHE.values())
    entries.sort(key=lambda item: -item["rows"])
    return {
        "enabled": settings["enabled"], "ttl_s": settings["ttl"],
        "max_rows": settings["max_rows"], "datasets": len(entries),
        "rows": sum(item["rows"] for item in entries),
        "catalog_units": catalog_units, "catalog_datasets": catalog_rows,
        "entries": entries,
    }


# 機關 Swagger 目錄另用一份快取：全部 27 個機關約 3000 筆，體積遠小於資料集，
# 但每次重抓要下載數 MB，目錄搜尋會慢到一分鐘。
_CATALOG_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _catalog_cached(unit_id: str, timeout: float) -> list[dict]:
    with _CACHE_LOCK:
        enabled, ttl = _CACHE_SETTINGS["enabled"], _CACHE_SETTINGS["ttl"]
        hit = _CATALOG_CACHE.get(unit_id) if enabled else None
        if hit is not None and time.monotonic() - hit[0] <= ttl:
            return hit[1]
    items = _swagger_datasets(unit_id, timeout)
    with _CACHE_LOCK:
        if _CACHE_SETTINGS["enabled"]:
            _CATALOG_CACHE[unit_id] = (time.monotonic(), items)
    return items


def _cache_get(dataset_id: str) -> list[dict] | None:
    with _CACHE_LOCK:
        if not _CACHE_SETTINGS["enabled"]:
            return None
        hit = _CACHE.get(dataset_id)
        if hit is None:
            return None
        stamp, rows = hit
        if time.monotonic() - stamp > _CACHE_SETTINGS["ttl"]:
            del _CACHE[dataset_id]
            return None
        return rows


def _cache_put(dataset_id: str, rows: list[dict]) -> None:
    with _CACHE_LOCK:
        if not _CACHE_SETTINGS["enabled"]:
            return
        budget = _CACHE_SETTINGS["max_rows"]
        if len(rows) > budget:
            return
        _CACHE[dataset_id] = (time.monotonic(), rows)
        # 超出預算時先丟最舊的（快取內容相同，先進先出即可）。
        while sum(len(cached) for _, cached in _CACHE.values()) > budget:
            oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
            if oldest == dataset_id:
                del _CACHE[dataset_id]
                return
            del _CACHE[oldest]


def fetch_ntpc_dataset(
    dataset_id: str, *, page_size: int = 100, max_pages: int = 500,
    timeout: float = 20, use_cache: bool = False,
) -> list[dict]:
    """由第 0 頁抓取完整 JSON，保留原始欄位及值，不擅自推定住宅用地。

    dataset_id 可從 search_ntpc_datasets() 或 search_district_datasets() 選取。
    自動讀到空頁；不因短頁而停止，避免伺服器限制 size 導致漏資料。
    超出頁數上限、重複頁或 API 失敗均拋出例外，不交付看似完整的部分資料。
    timeout 是每次請求的秒數。大型地價資料可自行提高 max_pages。
    use_cache=True 時命中快取直接回傳同一個 list 物件（呼叫端請勿就地修改），
    須先呼叫 enable_dataset_cache()。
    """
    dataset_id = str(UUID(dataset_id))
    for name, value in (("page_size", page_size), ("max_pages", max_pages)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} 必須是正整數。")
    if use_cache:
        cached = _cache_get(dataset_id)
        if cached is not None:
            return cached
    result, seen = [], set()
    for page in range(max_pages):
        query = urlencode({"page": page, "size": page_size})
        url = f"{NTPC_BASE}/api/datasets/{dataset_id}/json?{query}"
        rows = _validate_rows(_get_json(url, timeout), url)
        if not rows:
            if use_cache:
                _cache_put(dataset_id, result)
            return result
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).digest()
        if digest in seen:
            raise RuntimeError(f"第 {page} 頁重複，API 可能未正確分頁：{dataset_id}")
        seen.add(digest)
        result.extend(rows)
    raise RuntimeError(f"已達 max_pages={max_pages}，尚未確認資料結束；請提高上限。")


# --------------------------------------------------------------------------
# 座標
# --------------------------------------------------------------------------
def twd97_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """TWD97 TM2（中央經線 121°、GRS80）轉 WGS84 經緯度，回傳 (lon, lat)。

    部分資料集（例如路外公共停車場）只提供 TWD97 平面座標，需轉換後才能
    與其他來源一起量測距離。以同時含兩種座標的消防據點驗證，中位數偏差
    約 0.06 公尺；僅供距離初篩，不取代地籍測量。
    """
    for name, value in (("x", x), ("y", y)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} 必須是數值。")
        if not math.isfinite(value):
            raise ValueError(f"{name} 必須是有限數值。")
    a = 6378137.0
    f = 1 / 298.257222101
    k0, dx = 0.9999, 250000.0
    lon0 = math.radians(121.0)
    e2 = 2 * f - f * f
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    mu = (y / k0) / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = ep2 * cos1 ** 2
    t1 = tan1 ** 2
    n1 = a / math.sqrt(1 - e2 * sin1 ** 2)
    r1 = a * (1 - e2) / (1 - e2 * sin1 ** 2) ** 1.5
    d = (x - dx) / (n1 * k0)
    lat = phi1 - (n1 * tan1 / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = lon0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / cos1
    return math.degrees(lon), math.degrees(lat)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """兩組 WGS84 經緯度的大圓距離（公尺）。

    這是「點到點直線距離」，不是勘查表要求的區段邊界距離，也不是路網距離；
    只能用來初篩候選設施，仍須以地價區段圖與現地勘查認定級距。
    """
    for name, value in (("lon1", lon1), ("lat1", lat1), ("lon2", lon2), ("lat2", lat2)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} 必須是數值。")
        if not math.isfinite(value):
            raise ValueError(f"{name} 必須是有限數值。")
    radius = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


# 台灣本島合理經緯度範圍，用來擋掉來源填錯或單位錯置的座標。
_TAIWAN_LON = (119.0, 122.5)
_TAIWAN_LAT = (21.5, 26.5)


def _plausible(lon, lat) -> bool:
    return (lon is not None and lat is not None
            and _TAIWAN_LON[0] <= lon <= _TAIWAN_LON[1]
            and _TAIWAN_LAT[0] <= lat <= _TAIWAN_LAT[1])


def _percentile(values: list[float], q: float) -> float:
    index = int(round(q * (len(values) - 1)))
    return values[min(len(values) - 1, max(0, index))]


def reference_bbox(points, *, margin_deg: float = 0.015, min_points: int = 4):
    """由可信座標推出行政區的參考範圍，供寬鬆比對結果覆核。

    取 2%~98% 分位數再外擴 margin_deg（0.015° 約 1.6 公里），
    避免單一離群點把範圍撐大。點數不足時回傳 None，代表無法驗證。
    """
    usable = [(lon, lat) for lon, lat in points if _plausible(lon, lat)]
    if len(usable) < min_points:
        return None
    lons = sorted(p[0] for p in usable)
    lats = sorted(p[1] for p in usable)
    return {
        "min_lon": _percentile(lons, 0.02) - margin_deg,
        "max_lon": _percentile(lons, 0.98) + margin_deg,
        "min_lat": _percentile(lats, 0.02) - margin_deg,
        "max_lat": _percentile(lats, 0.98) + margin_deg,
        "based_on_points": len(usable),
        "margin_deg": margin_deg,
    }


def _inside(bbox: dict, lon, lat) -> bool:
    return (bbox["min_lon"] <= lon <= bbox["max_lon"]
            and bbox["min_lat"] <= lat <= bbox["max_lat"])


# --------------------------------------------------------------------------
# 表3／表5-1 欄位對應的資料來源登錄表
# --------------------------------------------------------------------------
def _ntpc(key, factor, item, category, dataset_id, source_name, *,
          name_keys, district_keys=(), address_keys=(), phone_keys=(),
          lon_keys=(), lat_keys=(), twd97_keys=(), extra_keys=(),
          loose_name_match=False, heavy=False, notes=()):
    return {
        "key": key, "factor": factor, "item": item, "category": category,
        "dataset_id": dataset_id, "source_name": source_name,
        "name_keys": name_keys, "district_keys": district_keys,
        "address_keys": address_keys, "phone_keys": phone_keys,
        "lon_keys": lon_keys, "lat_keys": lat_keys, "twd97_keys": twd97_keys,
        "extra_keys": extra_keys, "loose_name_match": loose_name_match,
        "heavy": heavy, "notes": tuple(notes),
    }


# 每一筆的欄位名稱都以實際 API 回應驗證過（2026-09 取樣）。
NTPC_SOURCES = (
    # ---------------- 交通運輸(2) ----------------
    _ntpc("bus_stops", "交通運輸", "站牌之接近程度或密集程度", "公車站牌",
          "34b402a8-53d9-483d-9406-24a682c2d6dc", "公車站位資訊",
          name_keys=("namezh",), address_keys=("address",),
          lon_keys=("longitude",), lat_keys=("latitude",),
          extra_keys=("routeid", "goback", "stoplocationid"), heavy=True,
          notes=("約 3.3 萬筆，需 include_heavy=True 才抓取。",
                 "部分站位 address 未含行政區，僅靠地址比對會漏收，須以座標複核。")),

    # ---------------- 公共建設(5) ----------------
    _ntpc("markets_public", "公共建設", "接近市場之程度", "公有市場／超市",
          MARKET_DATASET_ID, "新北市公有市場及超市清冊",
          name_keys=("name",), district_keys=("town",), address_keys=("address",),
          phone_keys=("phone",), extra_keys=("types",),
          notes=("公有清冊不完整涵蓋民營傳統市場、超級市場及超大型購物中心。",)),
    _ntpc("market_stalls", "公共建設", "接近市場之程度", "市場攤位（樂活名攤）",
          "82f5075d-b94e-4f54-a0db-1a439a88c93a", "新北市樂活名攤",
          name_keys=("stall_name",), district_keys=("district",),
          extra_keys=("market_name", "grade"),
          notes=("此為攤位名單，可反推市場存在，但無地址與座標。",)),
    _ntpc("parks", "公共建設", "接近公園、廣場、徒步區之程度", "公園",
          PARK_DATASET_ID, "新北市公園",
          name_keys=("name",), district_keys=("area",), address_keys=("address",),
          phone_keys=("localcallservice",), extra_keys=("management",),
          notes=("清冊未統一提供鄰里／一般公園分類，亦未完整涵蓋廣場及徒步區。",
                 "公園名稱常含他區地名（如林口區「樹林口公園」），"
                 "本模組一律以行政區欄位認定。")),
    _ntpc("tourist_spots", "公共建設", "接近觀光遊憩設施之程度", "觀光旅遊景點",
          "b3a30a19-4b89-4da2-8d99-18200dc5dfde", "新北市觀光旅遊景點(中文)",
          name_keys=("Name",), district_keys=("Zone",), address_keys=("Add",),
          phone_keys=("Tel",), lon_keys=("Px",), lat_keys=("Py",),
          extra_keys=("Class1", "Class2", "Class3", "Level", "Opentime"),
          notes=("Zone 欄位常為空值，主要以 Add 地址認定行政區。",)),
    _ntpc("tourist_factories", "公共建設", "接近觀光遊憩設施之程度", "觀光工廠",
          "57eb9b00-979c-44bb-a4ee-cc55bdf1488a", "新北市觀光工廠",
          name_keys=("organization",), address_keys=("adress",),
          phone_keys=("localcallservice",), extra_keys=("introduction",)),
    _ntpc("bikeways", "公共建設", "接近觀光遊憩設施之程度", "自行車道出入口／租借站",
          "996a600d-fd74-4a49-92d3-9464d2606e3f", "新北市自行車道資料",
          name_keys=("name", "position"), lon_keys=("longitude",), lat_keys=("latitude",),
          extra_keys=("location",), loose_name_match=True,
          notes=("此資料集無行政區與地址欄位，只能用名稱寬鬆比對，"
                 "再以參考範圍覆核座標。",)),
    _ntpc("parking_offstreet", "公共建設", "停車場地之便利程度", "路外公共停車場",
          "b1464ef0-9c7c-4a6f-abf7-6bdf32847e68", "新北市路外公共停車場資訊",
          name_keys=("NAME",), district_keys=("AREA",), address_keys=("ADDRESS",),
          phone_keys=("TEL",), twd97_keys=("TW97X", "TW97Y"),
          extra_keys=("TYPE", "SUMMARY", "PAYEX", "SERVICETIME",
                      "TOTALCAR", "TOTALMOTOR", "TOTALBIKE"),
          notes=("僅提供 TWD97 平面座標，已換算 WGS84 經緯度供距離初篩。",)),
    _ntpc("parking_roadside", "公共建設", "停車場地之便利程度", "路邊收費停車路段",
          "d9f18db5-41c7-41d4-b7f0-82a335255b08", "新北市路邊收費停車場收費路段資訊",
          name_keys=("road_name",), district_keys=("area",),
          extra_keys=("rates", "weekdays_time"),
          notes=("以路段為單位，無門牌與座標。",)),
    _ntpc("health_centers", "公共建設", "接近服務性設施的程度", "衛生所",
          "2553bb1a-bcbb-4284-8b24-acfefe966f1e", "新北市各區衛生所",
          name_keys=("hosp_name",), district_keys=("district",),
          address_keys=("hosp_addr",), phone_keys=("tel",)),
    _ntpc("emergency_hospitals", "公共建設", "接近服務性設施的程度", "急救責任醫院",
          "c2f23210-03c7-4461-b9d3-9ee4df24c3e9", "新北市急救責任醫院",
          name_keys=("hosp_name",), address_keys=("hosp_addr",), phone_keys=("tel",),
          lon_keys=("wgs84ax",), lat_keys=("wgs84ay",),
          twd97_keys=("twd97x", "twd97y"), extra_keys=("yyyroc",),
          notes=("只含急救責任醫院，非全部醫院與診所；一般診所須另查中央醫事機構清冊。",)),
    _ntpc("community_centers", "公共建設", "接近服務性設施的程度", "市民活動中心",
          "08df50e4-2ab6-47b6-91b6-fa9ae08a30bd", "新北市市民活動中心資料",
          name_keys=("title",), district_keys=("district",), address_keys=("address",),
          phone_keys=("tel",),
          notes=("district 欄位不含「區」字（如「樹林」），本模組已一併認定。",)),
    _ntpc("police_stations", "公共建設", "接近服務性設施的程度", "警察服務據點",
          "385dbda9-87c4-4357-ba39-2dd43547855c", "新北市警察服務據點",
          name_keys=("unit2", "unit1"), address_keys=("address",), phone_keys=("tel",),
          lon_keys=("lon_dd",), lat_keys=("lat_dd",), twd97_keys=("twd97_x", "twd97_y"),
          notes=("少數據點的 lon_dd／lat_dd 與 twd97 欄位互相矛盾（實測最大差 5 公里），"
                 "距離計算前建議以地址複核。",)),
    _ntpc("fire_stations", "公共建設", "接近服務性設施的程度", "消防據點",
          "80dc6551-a36d-4172-968c-4f72d74db82f", "新北市政府消防據點",
          name_keys=("firestrongholds",), address_keys=("address",),
          phone_keys=("localcallservice",),
          lon_keys=("coordinatelongitude",), lat_keys=("coordinatelatitude",),
          twd97_keys=("twd97x", "twd97y")),
    _ntpc("farmers_associations", "公共建設", "接近服務性設施的程度", "農會",
          "aac5c97e-eefb-41ec-81bc-9ba148a7a54c", "新北市農會通訊資料",
          name_keys=("name",), address_keys=("address",), phone_keys=("tel",),
          notes=("農會兼具金融機構性質，亦可對應工商活動-金融機構欄位。",)),

    # ---------------- 特殊設施(6) ----------------
    _ntpc("gas_stations", "特殊設施", "電業設施及公用氣體燃料設施之有無及接近程度",
          "加油站",
          "112f981a-0f10-4791-8f10-67fbda1d3a83", "新北市加油站清冊",
          name_keys=("station",), district_keys=("town",), address_keys=("address",),
          extra_keys=("company",),
          notes=("加油站可作為儲油槽的替代指標，非台電變電所或高壓鐵塔資料。",)),
    _ntpc("cng_stations", "特殊設施", "電業設施及公用氣體燃料設施之有無及接近程度",
          "加氣站",
          "54e214d6-39bd-4486-8050-2d27a32dcfc0", "新北市加氣站清冊",
          name_keys=("station",), district_keys=("town",), address_keys=("address",),
          extra_keys=("company",)),
    _ntpc("lpg_retailers", "特殊設施", "電業設施及公用氣體燃料設施之有無及接近程度",
          "液化石油氣零售業者",
          "ba33a61c-72b9-4e80-956d-beff4b8c85cc", "新北市各區液化石油氣零售業者清冊",
          name_keys=("company",), district_keys=("town",), address_keys=("address",),
          extra_keys=("unified number",),
          notes=("零售業者登記地址不等於瓦斯槽或儲存場所位置。",)),
    _ntpc("funeral_facilities", "特殊設施", "殯葬設施之有無及接近程度", "公立公墓／納骨塔",
          "1d228eab-23d4-41a6-bd33-f4014dd44660", "新北市公立公墓納骨塔查詢",
          name_keys=("facilityname",), district_keys=("district",),
          address_keys=("facilityaddress",), phone_keys=("localcallservice1",),
          extra_keys=("facilityclassification", "recent", "remarks"),
          notes=("僅公立設施；私立墓園、殯儀館、火葬場須另行查證。",)),
    _ntpc("incinerators", "特殊設施", "廢棄物處理設施之有無及接近程度", "垃圾焚化廠",
          "39e17852-9ac9-45b7-bc60-d8d0ed7e3161", "新北市垃圾焚化廠位置",
          name_keys=("chinese_name",), address_keys=("address",),
          phone_keys=("localcallservice",),
          notes=("全市僅 3 座（新店、樹林、八里）；鄰區焚化廠也會影響本區，"
                 "查無不等於周邊無焚化廠。",)),
    _ntpc("landfills", "特殊設施", "廢棄物處理設施之有無及接近程度", "掩埋場",
          "a30d296d-e43c-43a5-97d2-aef54332d4e0", "新北市掩埋場位置",
          name_keys=("chinesename",), address_keys=("address",),
          phone_keys=("localcallservice",),
          notes=("全市僅 3 座；鄰區掩埋場也會影響本區。",)),
    _ntpc("waste_handlers", "特殊設施", "廢棄物處理設施之有無及接近程度",
          "廢棄物清除及處理機構",
          "8c2288ba-0b37-4e2e-af55-bf723ba40edf", "新北市清除及處理機構基本資料(新版)",
          name_keys=("fac_name",), address_keys=("fac_addr",), phone_keys=("tel_no",),
          extra_keys=("cate", "grad", "licid", "effedata"),
          notes=("登記地址多為公司所在地，未必是處理場址。",)),

    # ---------------- 環境污染(7) ----------------
    _ntpc("soil_water_sites", "環境污染", "水污染", "土壤及地下水列管場址",
          "9987dc63-2c8d-4c75-903d-6ebd82d1792d", "新北市土壤及地下水列管資訊(目前列管場址)",
          name_keys=("name",), extra_keys=("style", "pollute", "date"),
          loose_name_match=True,
          notes=("名稱多為地號（部分沿用舊制「臺北縣○○市」），無座標，"
                 "須另查地籍位置。",)),
    _ntpc("drainage", "環境污染", "水污染", "市管區域排水",
          "bfcaacf8-c9c1-4d9a-8561-ac232819e001", "新北市管區域排水資訊",
          name_keys=("drain_name",), district_keys=("district",),
          extra_keys=("drain_outlet", "start", "end"),
          notes=("排水路本身不等於水污染源，僅供判斷水體位置參考。",)),
    _ntpc("noise_monitors", "環境污染", "噪音污染", "環境及交通噪音監測站",
          "cad88b80-8230-48d4-a8d4-ce478954fddf", "新北市環境及交通噪音監測站地點",
          name_keys=("name",), address_keys=("address",),
          extra_keys=("no", "control_area", "road_width"),
          notes=("監測站是量測點，不是噪音源；控制區級別可佐證環境噪音程度。",)),
    _ntpc("noise_monitors_other", "環境污染", "噪音污染", "噪音監測站",
          "612f1570-6a62-47b6-8531-94774d98c422", "新北市噪音監測站位置",
          name_keys=("name",), address_keys=("address",),
          extra_keys=("no.", "control_area", "road_width")),
    _ntpc("air_fixed_sources", "環境污染", "廢氣污染", "設有空污監測設施之固定污染源",
          "0f0967bd-3c42-4fd4-80ac-786509c315f3",
          "新北市轄內設置空氣污染物監測設施之固定污染源",
          name_keys=("name",), address_keys=("address",), extra_keys=("number",)),
    _ntpc("air_monitors", "環境污染", "廢氣污染", "空氣品質人工監測站",
          "a57c5c06-5066-4452-b2f2-9cfc95d4291d", "新北市空氣品質人工監測站位置",
          name_keys=("name",), district_keys=("administrative_area",),
          address_keys=("address",), extra_keys=("no.", "item", "date")),
    _ntpc("waste_reusers", "環境污染", "廢棄物污染", "事業廢棄物再利用者",
          "473ca704-c8e6-4ae2-91b9-855fe8ddf2a2", "新北市事業廢棄物再利用者登記資料",
          name_keys=("fac_name",), address_keys=("fac_addr",), phone_keys=("tel_no",),
          extra_keys=("cate", "certdata", "effedata"),
          notes=("同一機構可能重複列於多筆許可，計數不等於場址數。",)),
    _ntpc("recycle_stations", "環境污染", "廢棄物污染", "黃金資收站",
          "a381e1f4-86d0-4575-adb4-8d9b6a75e3c4", "新北市黃金資收站資訊",
          name_keys=("name",), district_keys=("district",),
          address_keys=("recycle_address", "address"),
          phone_keys=("tel_localcallservice",),
          extra_keys=("village", "no", "open_time", "state")),
    _ntpc("factories", "環境污染", "其他污染", "工廠登記",
          "821bfb96-a1ae-43d9-bf2c-065ce8c22765", "新北市工廠登記清冊v2",
          name_keys=("fact_name",), address_keys=("fact_addr",),
          extra_keys=("prf", "prd8", "status", "regi_id"), heavy=True,
          notes=("逾 4 萬筆，需 include_heavy=True 才抓取。",
                 "status 含「歇業」者仍在清冊中，判斷污染須先過濾營業狀態。")),

    # ---------------- 工商活動 ----------------
    _ntpc("cinemas", "工商活動", "娛樂設施", "電影院",
          "61c99f42-8a90-4adc-9c40-ba9e0ea097aa", "新北市電影院名冊",
          name_keys=("name",), address_keys=("address",), phone_keys=("tel",),
          extra_keys=("number",)),
    _ntpc("amusement_venues", "工商活動", "娛樂設施", "特定行業／電子遊戲場／KTV",
          "46364866-1d11-479c-ae75-74932cf1d5f3",
          "新北市特定行業、電子遊戲場業及資訊休閒業營業場所投保公共意外險清冊",
          name_keys=("name",), address_keys=("address",),
          extra_keys=("industry", "result", "invoice number")),
    _ntpc("internet_cafes", "工商活動", "娛樂設施", "資訊休閒業",
          "9a34e36f-6ac2-4c1f-a5af-7f20d740a2e0", "新北市合法資訊休閒業者清冊",
          name_keys=("corporation",), address_keys=("address",),
          extra_keys=("owner", "businessadministrationnumber", "date")),
    _ntpc("hotels", "工商活動", "大型展示中心或觀光飯店", "合法一般旅館",
          "8565597e-a174-4907-99c7-adb5ddee1326", "新北市合法一般旅館名冊",
          name_keys=("name",), address_keys=("address",),
          phone_keys=("localcallservice",),
          lon_keys=("longitude",), lat_keys=("latitude",),
          extra_keys=("room", "button_price", "higher_price"),
          notes=("一般旅館不等於觀光飯店；星級與大型展示中心須另行認定。",)),
    _ntpc("bnb", "工商活動", "大型展示中心或觀光飯店", "合法民宿",
          "137e071b-f315-43bb-adc8-90fafa014c4a", "新北市合法民宿名冊",
          name_keys=("name",), address_keys=("address",), phone_keys=("tel",),
          lon_keys=("coordinatelongitude",), lat_keys=("coordinatelatitude",),
          extra_keys=("room",)),
    _ntpc("business_districts", "工商活動", "顧客之通行量", "商圈",
          "f54ded71-eb04-466d-bb6d-dd948c8d8502", "各商圈理事長聯絡資料",
          name_keys=("business_district",), address_keys=("addr",), phone_keys=("tel",),
          notes=("僅商圈組織聯絡資料，無人流量統計。",)),

    # ---------------- 其他周邊環境 ----------------
    _ntpc("temples", "其他影響因素", "周邊環境設施", "寺廟",
          "f0e1879f-3c5b-429f-a12b-9540acac26e8", "新北市寺廟資料",
          name_keys=("tep_name",), district_keys=("tep_area",),
          address_keys=("tep_address",), phone_keys=("tep_phone",),
          extra_keys=("tep_god", "tep_class", "tep_village")),
    _ntpc("water_company", "其他影響因素", "產業用水及設施", "自來水營運所",
          "7be52182-61d9-41fd-838f-8726dc302d53", "新北市台灣自來水公司通訊資料",
          name_keys=("name",), address_keys=("address",), phone_keys=("tel_1",),
          extra_keys=("area",),
          notes=("全市僅 6 個營運所，且為聯絡資訊；供水轄區須看 area 欄位敘述，"
                 "非設施位置。",)),
    _ntpc("pump_stations", "其他影響因素", "產業用水及設施", "抽水站",
          "3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296", "新北市各抽水站資訊",
          name_keys=("title",), address_keys=("address",),
          extra_keys=("river", "pump_type", "year")),
)

# 表3／表5-1 有欄位、但新北市開放資料平臺查無對應清冊者。
# 一律回報 no_open_data_source + survey_required，禁止當成「無」。
SURVEY_ONLY_ITEMS = (
    {"factor": "交通運輸", "item": "接近大型車站之程度", "category": "火車站／捷運站",
     "reason": "平臺無車站點位清冊；公車站位資訊雖含「○○火車站」等站名，"
               "屬公車站牌非車站本體。"},
    {"factor": "交通運輸", "item": "交流道之有無及接近交流道之程度", "category": "高速公路交流道",
     "reason": "平臺查無交流道或匝道位置資料集。"},
    {"factor": "特殊設施", "item": "電業設施及公用氣體燃料設施之有無及接近程度",
     "category": "變電所或高壓鐵塔",
     "reason": "屬台灣電力公司資料，新北市平臺查無變電所、輸電鐵塔位置清冊。"},
    {"factor": "特殊設施", "item": "廢棄物處理設施之有無及接近程度", "category": "污水處理場",
     "reason": "平臺僅有污水處理率與接管普及率統計，查無水資源回收中心點位。"},
    {"factor": "環境污染", "item": "水污染", "category": "河川水質測站／放流水",
     "reason": "平臺查無河川水質監測或列管放流水的分區資料。"},
    {"factor": "工商活動", "item": "百貨公司", "category": "百貨公司／購物中心",
     "reason": "平臺查無百貨公司、購物中心、量販店清冊；"
               "需由公司登記清冊人工篩選或現地勘查。"},
    {"factor": "工商活動", "item": "金融機構", "category": "銀行／郵局分支機構",
     "reason": "平臺僅有農會通訊資料與信用合作社家數統計，"
               "查無銀行分行、郵局據點位置清冊。"},
    {"factor": "工商活動", "item": "顧客之通行量", "category": "人流量",
     "reason": "無開放資料，屬現地勘查項目。"},
    {"factor": "工商活動", "item": "店舖之叫座狀態", "category": "店舖經營狀況",
     "reason": "無開放資料，屬現地勘查項目。"},
    {"factor": "其他影響因素", "item": "電力資源", "category": "電力供應設施",
     "reason": "平臺僅有用電設備檢驗維護業清冊，查無供電設施位置。"},
)

GLOBAL_WARNINGS = (
    "學校為指定學年度；其餘 NTPC 資料集為 API 現行清冊，不可當作同年度歷史證據。",
    "行政區不是地價區段；區段內外、距離須補設施座標、區段邊界及量測定義。",
    "僅篩選指定行政區，未納入鄰接行政區設施，不能據此判斷區段外最近設施。",
    "查無資料、來源失敗或 survey_required 均不等於設施不存在；"
    "不可自動勾選『無』或填零距離。",
    "match_basis='name_keyword' 之記錄屬寬鬆比對，已用參考範圍過濾座標，"
    "無座標者仍須人工覆核行政區。",
    "TWD97 換算之經緯度為公尺級精度，僅供距離初篩，不取代地籍測量。",
    "行政區以資料集的行政區欄位優先認定；欄位宣告為他區者即排除，"
    "故跨越兩區的設施（如區界上的停車場）只會出現在欄位所載的行政區。",
)


# --------------------------------------------------------------------------
# 篩選與正規化
# --------------------------------------------------------------------------
def _text(row: dict, keys) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in {"-", "NIL", "無"}:
            return text
    return None


def _number(row: dict, keys) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _build_record(row: dict, source: dict, url: str, basis: str,
                  matcher: DistrictMatcher) -> dict:
    longitude = _number(row, source["lon_keys"])
    latitude = _number(row, source["lat_keys"])
    if not _plausible(longitude, latitude):
        longitude = latitude = None
    twd97_x = twd97_y = None
    coordinate_source = "dataset_wgs84" if longitude is not None else None
    if source["twd97_keys"]:
        twd97_x = _number(row, (source["twd97_keys"][0],))
        twd97_y = _number(row, (source["twd97_keys"][1],))
        if longitude is None and twd97_x is not None and twd97_y is not None:
            converted = twd97_to_wgs84(twd97_x, twd97_y)
            if _plausible(*converted):
                longitude, latitude = converted
                coordinate_source = "twd97_converted"
    return {
        "factor": source["factor"],
        "item": source["item"],
        "category": source["category"],
        "name": _text(row, source["name_keys"]),
        "administrative_district": matcher.full_name,
        "address": _text(row, source["address_keys"]),
        "phone": _text(row, source["phone_keys"]),
        "longitude": longitude,
        "latitude": latitude,
        "twd97_x": twd97_x,
        "twd97_y": twd97_y,
        "coordinate_source": coordinate_source,
        "match_basis": basis,
        "needs_manual_check": basis == "name_keyword",
        "school_year": None,
        "in_value_section": None,
        "distance_m": None,
        "extra": {k: row.get(k) for k in source["extra_keys"] if k in row},
        "source_key": source["key"],
        "source_name": source["source_name"],
        "source_url": url,
        "raw": row,
    }


# --------------------------------------------------------------------------
# 學校
# --------------------------------------------------------------------------
def _school_sources(year: int) -> list[dict]:
    base = "https://stats.moe.gov.tw/files"
    return [
        {"key": "elementary", "name": "國民小學名錄", "category": "國小",
         "url": f"{base}/school/{year}/e1_new.json", "format": "json"},
        {"key": "junior", "name": "國民中學名錄", "category": "國中",
         "url": f"{base}/opendata/j1_new.json", "format": "json"},
        {"key": "attached_junior", "name": "附設國中部名錄", "category": "國中",
         "url": f"{base}/opendata/aj_new.json", "format": "json"},
        {"key": "senior", "name": "一般高級中等學校名錄", "category": "高中／高職",
         "url": f"{base}/school/{year}/high.csv", "format": "csv"},
        {"key": "university", "name": "大專校院名錄", "category": "大專院校",
         "url": f"{base}/opendata/u1_new.json", "format": "json"},
    ]


def _read_school_rows(source: dict, timeout: float) -> list[dict]:
    """只負責連線取回原始列，方便與其他來源並行下載。"""
    if source["format"] == "csv":
        return list(csv.DictReader(io.StringIO(_read_url(source["url"], timeout))))
    return _get_json(source["url"], timeout)


def _match_schools(rows, source: dict, school_year: int,
                   matcher: DistrictMatcher) -> list[dict]:
    url = source["url"]
    _validate_rows(rows, url, ("學年度", "學校名稱", "地址", "縣市名稱"))
    if any(not isinstance(row[key], str) for row in rows
           for key in ("學校名稱", "地址", "縣市名稱")):
        raise ValueError("學校名稱、地址或縣市名稱不是文字，請確認來源格式。")
    rows = [row for row in rows if str(row["學年度"]).strip() == str(school_year)]
    if not rows:
        raise ValueError(f"此來源沒有 {school_year} 學年度資料，未替用其他年度。")
    # 不用校名判斷，避免誤收他區學校或漏收校名無地名的學校。
    matches = [row for row in rows if CITY_NAME in row["縣市名稱"]
               and matcher.school_address_re.match(row["地址"].strip())]
    records = []
    for row in matches:
        records.append({
            "factor": "公共建設",
            "item": "接近學校之程度",
            "category": source["category"],
            "name": row["學校名稱"],
            "administrative_district": matcher.full_name,
            "address": row["地址"].strip(),
            "phone": row.get("電話"),
            "longitude": None, "latitude": None,
            "twd97_x": None, "twd97_y": None, "coordinate_source": None,
            "match_basis": "address",
            "needs_manual_check": False,
            "school_year": school_year,
            "in_value_section": None, "distance_m": None,
            "extra": {},
            "source_key": source["key"],
            "source_name": source["name"],
            "source_url": url,
            "raw": row,
        })
    return records


# --------------------------------------------------------------------------
# 主要查詢
# --------------------------------------------------------------------------
def fetch_valuation_factors(
    district: str = "樹林區", *, school_year: int = 114, timeout: float = 30,
    strict: bool = False, include_heavy: bool = False,
    only_factors: tuple[str, ...] | None = None,
    only_source_keys: tuple[str, ...] | None = None,
    max_workers: int = 4, use_cache: bool = False, include_raw: bool = True,
    progress=None,
) -> dict:
    """彙整表3／表5-1 各欄位可用的候選設施資料。

    district 可填「金山區」「金山」或「新北市金山區」，見 NTPC_DISTRICTS。
    回傳 factors（依「主要項目 / 修正細項」分組）、sources、errors、warnings、
    reference_bbox，另附 schools／markets／parks 三個扁平清單。

    include_heavy=True 才會抓取公車站位資訊（約 3.3 萬筆）與工廠登記清冊
    （逾 4 萬筆），時間與流量明顯增加。
    only_factors 可限定主要項目，例如 ("特殊設施", "環境污染")。
    only_source_keys 可限定個別來源，鍵值見 NTPC_SOURCES 與 _school_sources()。
    max_workers 為同時下載的來源數；請勿設過高，對方是公開服務。
    use_cache=True 需先呼叫 enable_dataset_cache()，換區時可省下大部分連線。
    include_raw=False 會移除每筆的 raw 原始欄位，回應體積小很多。
    progress 為 callable(done, total, label)，抓取每個來源後呼叫一次。
    strict=False 時個別來源失敗列入 errors；strict=True 直接拋出例外。
    """
    matcher = DistrictMatcher(district)
    if type(school_year) is not int or not 103 <= school_year <= 200:
        raise ValueError("school_year 請填民國學年度整數，例如 111 或 114。")
    if timeout <= 0:
        raise ValueError("timeout 必須大於 0。")
    if type(max_workers) is not int or not 1 <= max_workers <= 16:
        raise ValueError("max_workers 必須是 1~16 的整數。")
    if progress is not None and not callable(progress):
        raise ValueError("progress 必須是可呼叫物件。")
    for label, value in (("only_factors", only_factors),
                         ("only_source_keys", only_source_keys)):
        if value is not None and (
            not isinstance(value, (tuple, list, set, frozenset))
            or any(not isinstance(item, str) for item in value)
        ):
            raise ValueError(f"{label} 必須是字串序列。")
    wanted = set(only_factors) if only_factors else None
    wanted_keys = set(only_source_keys) if only_source_keys else None
    if wanted:
        unknown = wanted - {source["factor"] for source in NTPC_SOURCES} \
            - {item["factor"] for item in SURVEY_ONLY_ITEMS}
        if unknown:
            raise ValueError(f"未知的主要項目：{'、'.join(sorted(unknown))}")

    report = {
        "city": CITY_NAME,
        "district": matcher.district,
        "administrative_district": matcher.full_name,
        "requested_land_type": "普通住宅用地（查估情境，非 API 篩選或分區認定）",
        "school_year": school_year,
        "include_heavy": bool(include_heavy),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "reference_bbox": None,
        "factors": [],
        "sources": [],
        "errors": [],
        "loose_match_rejected": [],
        "warnings": list(GLOBAL_WARNINGS),
        "schools": [], "markets": [], "parks": [],
    }
    buckets: dict[tuple[str, str], dict] = {}

    def bucket(factor: str, item: str) -> dict:
        key = (factor, item)
        if key not in buckets:
            buckets[key] = {
                "factor": factor, "item": item, "status": "no_open_data_source",
                "survey_required": True, "record_count": 0,
                "records": [], "sources": [], "notes": [],
            }
            report["factors"].append(buckets[key])
        return buckets[key]

    # --- 階段一：規劃要抓哪些來源 ---
    plan: list[dict] = []
    if wanted is None or "公共建設" in wanted:
        for source in _school_sources(school_year):
            if wanted_keys is not None and source["key"] not in wanted_keys:
                continue
            plan.append({
                "kind": "school", "source": source,
                "metadata": {
                    "key": source["key"], "name": source["name"],
                    "url": source["url"], "factor": "公共建設",
                    "item": "接近學校之程度", "period": f"{school_year} 學年度",
                    "status": "ok", "matched_count": None,
                },
            })
    for source in NTPC_SOURCES:
        if wanted is not None and source["factor"] not in wanted:
            continue
        if wanted_keys is not None and source["key"] not in wanted_keys:
            continue
        url = f"{NTPC_BASE}/api/datasets/{source['dataset_id']}/json"
        plan.append({
            "kind": "ntpc", "source": source,
            "metadata": {
                "key": source["key"], "name": source["source_name"], "url": url,
                "factor": source["factor"], "item": source["item"],
                "category": source["category"], "dataset_id": source["dataset_id"],
                "period": "API 現行清冊", "status": "ok", "matched_count": None,
                "heavy": source["heavy"],
            },
        })
    total_sources = len(plan)

    # --- 階段二：並行下載。只做網路，不做比對，例外留待階段三處理 ---
    def download(task):
        source = task["source"]
        if task["kind"] == "school":
            return _read_school_rows(source, timeout)
        if source["heavy"] and not include_heavy:
            return None
        return fetch_ntpc_dataset(
            source["dataset_id"], page_size=1000, max_pages=200,
            timeout=timeout, use_cache=use_cache)

    done = 0

    def report_progress(task):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total_sources, task["metadata"]["name"])

    if max_workers > 1 and total_sources > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [(task, pool.submit(download, task)) for task in plan]
            for task, future in futures:
                try:
                    task["rows"] = future.result()
                except Exception as exc:  # noqa: BLE001 - 逐來源記錄，稍後統一處理
                    task["error"] = exc
                report_progress(task)
    else:
        for task in plan:
            try:
                task["rows"] = download(task)
            except Exception as exc:  # noqa: BLE001
                task["error"] = exc
            report_progress(task)

    # --- 階段三：序列比對。先收集嚴格比對結果，座標齊全後才裁決寬鬆比對 ---
    strict_points: list[tuple[float, float]] = []
    pending: list[tuple[dict, dict, list[dict], list[dict]]] = []
    for task in plan:
        source, metadata = task["source"], task["metadata"]
        slot = bucket(metadata["factor"], metadata["item"])
        if task["kind"] == "ntpc":
            slot["notes"].extend(source["notes"])
        slot["sources"].append(metadata)
        report["sources"].append(metadata)
        error = task.get("error")
        if error is None and task["kind"] == "ntpc" and task["rows"] is None:
            metadata["status"] = "skipped_heavy"
            metadata["note"] = "資料量龐大，請以 include_heavy=True 抓取。"
            continue
        if error is None:
            try:
                if task["kind"] == "school":
                    records = _match_schools(task["rows"], source, school_year, matcher)
                    slot["records"].extend(records)
                    report["schools"].extend(records)
                    metadata["matched_count"] = len(records)
                    metadata["status"] = "ok" if records else "no_district_matches"
                    continue
                _validate_rows(task["rows"], metadata["url"], (source["name_keys"][0],))
                firm, loose = [], []
                for row in task["rows"]:
                    basis = matcher.match(row, source)
                    if not basis:
                        continue
                    record = _build_record(row, source, metadata["url"], basis, matcher)
                    if basis == "name_keyword":
                        loose.append(record)
                    else:
                        firm.append(record)
                        if record["longitude"] is not None:
                            strict_points.append(
                                (record["longitude"], record["latitude"]))
                pending.append((source, metadata, firm, loose))
                continue
            except (RuntimeError, ValueError, csv.Error) as exc:
                error = exc
        if strict:
            raise error
        metadata["status"] = "error"
        metadata["error"] = str(error)
        report["errors"].append({"source": metadata["key"], "message": str(error)})

    # --- 用嚴格比對的座標範圍裁決寬鬆比對結果 ---
    bbox = reference_bbox(strict_points)
    report["reference_bbox"] = bbox
    for source, metadata, firm, loose in pending:
        slot = bucket(source["factor"], source["item"])
        kept = list(firm)
        for record in loose:
            if record["longitude"] is None:
                record["bbox_check"] = "no_coordinates"
                kept.append(record)
            elif bbox is None:
                record["bbox_check"] = "no_reference"
                kept.append(record)
            elif _inside(bbox, record["longitude"], record["latitude"]):
                record["bbox_check"] = "inside"
                kept.append(record)
            else:
                report["loose_match_rejected"].append({
                    "source": source["key"], "name": record["name"],
                    "longitude": record["longitude"], "latitude": record["latitude"],
                    "reason": "座標落在參考範圍外，判定為同名他區設施。",
                })
        slot["records"].extend(kept)
        metadata["matched_count"] = len(kept)
        metadata["status"] = "ok" if kept else "no_district_matches"
        if source["key"] in {"markets_public", "market_stalls"}:
            report["markets"].extend(kept)
        elif source["key"] == "parks":
            report["parks"].extend(kept)

    # --- 無開放資料來源的欄位 ---
    for item in SURVEY_ONLY_ITEMS:
        if wanted is not None and item["factor"] not in wanted:
            continue
        slot = bucket(item["factor"], item["item"])
        slot["notes"].append(f"{item['category']}：{item['reason']}")
        slot.setdefault("survey_only_categories", []).append(item["category"])

    # --- 收尾統計 ---
    for slot in report["factors"]:
        slot["record_count"] = len(slot["records"])
        statuses = {meta["status"] for meta in slot["sources"]}
        if slot["record_count"]:
            slot["status"] = "ok"
            slot["survey_required"] = bool(
                slot.get("survey_only_categories")
                or statuses & {"error", "skipped_heavy"})
        elif not slot["sources"]:
            slot["status"] = "no_open_data_source"
            slot["survey_required"] = True
        elif statuses == {"skipped_heavy"}:
            slot["status"] = "skipped_heavy"
            slot["survey_required"] = True
        elif "error" in statuses and not statuses & {"ok", "no_district_matches"}:
            slot["status"] = "error"
            slot["survey_required"] = True
        else:
            slot["status"] = "no_district_matches"
            slot["survey_required"] = True
        slot["notes"] = list(dict.fromkeys(slot["notes"]))

    report["factors"].sort(key=lambda slot: (slot["factor"], slot["item"]))
    report["record_count"] = sum(slot["record_count"] for slot in report["factors"])
    if not include_raw:
        for slot in report["factors"]:
            for record in slot["records"]:
                record.pop("raw", None)
    if report["errors"]:
        report["status"] = "error" if len(report["errors"]) == total_sources else "partial"
    return report


def fetch_public_facilities(
    district: str = "樹林區", *, school_year: int = 114, timeout: float = 20,
    strict: bool = False, **kwargs,
) -> dict:
    """只取學校、公有市場、公園三類（原 fetch_shulin_public_facilities 的行為）。"""
    keep = ("elementary", "junior", "attached_junior", "senior", "university",
            "markets_public", "market_stalls", "parks")
    return fetch_valuation_factors(
        district, school_year=school_year, timeout=timeout, strict=strict,
        only_factors=("公共建設",), only_source_keys=keep, **kwargs)


# 舊名稱保留，等同 district="樹林區"。
def fetch_shulin_valuation_factors(**kwargs) -> dict:
    """已棄用；請改用 fetch_valuation_factors("樹林區", ...)。"""
    return fetch_valuation_factors("樹林區", **kwargs)


def fetch_shulin_public_facilities(**kwargs) -> dict:
    """已棄用；請改用 fetch_public_facilities("樹林區", ...)。"""
    return fetch_public_facilities("樹林區", **kwargs)


def save_json(data, path: str | Path, *, overwrite: bool = False) -> Path:
    """儲存為 UTF-8 中文 JSON；預設拒絕覆寫既有檔案，父目錄須已存在。"""
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    target = Path(path)
    with target.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")
    return target


def summarize(report: dict) -> str:
    """把 factors 整理成可讀的文字摘要，方便貼進勘查紀錄或人工覆核。"""
    lines = [
        f"{report['administrative_district']}｜學年度 {report['school_year']}"
        f"｜狀態 {report['status']}｜共 {report.get('record_count', 0)} 筆",
    ]
    bbox = report.get("reference_bbox")
    if bbox:
        lines.append(
            f"參考範圍（由 {bbox['based_on_points']} 個可信座標推出，"
            f"外擴 {bbox['margin_deg']}°）："
            f"經度 {bbox['min_lon']:.4f}~{bbox['max_lon']:.4f}、"
            f"緯度 {bbox['min_lat']:.4f}~{bbox['max_lat']:.4f}")
    else:
        lines.append("參考範圍：可信座標不足，寬鬆比對結果未經座標驗證。")
    current = None
    for slot in report["factors"]:
        if slot["factor"] != current:
            current = slot["factor"]
            lines.append(f"\n[{current}]")
        flag = " ★需現地勘查" if slot["survey_required"] else ""
        lines.append(f"  {slot['item']}：{slot['record_count']} 筆"
                     f"（{slot['status']}）{flag}")
        counts: dict[str, int] = {}
        for record in slot["records"]:
            counts[record["category"]] = counts.get(record["category"], 0) + 1
        for category, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"      - {category}：{count}")
    if report.get("loose_match_rejected"):
        lines.append("\n[寬鬆比對已排除（同名他區）]")
        for item in report["loose_match_rejected"]:
            lines.append(f"  {item['name']}（{item['source']}）"
                         f" {item['longitude']},{item['latitude']}")
    if report["errors"]:
        lines.append("\n[來源失敗]")
        for error in report["errors"]:
            lines.append(f"  {error['source']}：{error['message'][:120]}")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="抓取新北市指定行政區的查估用開放資料（表3／表5-1 欄位）。")
    parser.add_argument("--area", "--district", dest="area", default="樹林區",
                        help="行政區，例如 樹林區、金山區、板橋區。預設 樹林區。")
    parser.add_argument("--school-year", type=int, default=114,
                        help="學校名錄的民國學年度，預設 114。")
    parser.add_argument("--out-dir", default="opendata", help="輸出目錄，預設 opendata。")
    parser.add_argument("--timeout", type=float, default=30, help="每次請求秒數。")
    parser.add_argument("--include-heavy", action="store_true",
                        help="併抓公車站位資訊與工廠登記清冊（資料量大）。")
    parser.add_argument("--workers", type=int, default=4,
                        help="同時下載的來源數，1~16，預設 4。")
    parser.add_argument("--no-raw", action="store_true",
                        help="輸出不含每筆的 raw 原始欄位，檔案小很多。")
    parser.add_argument("--catalog", action="store_true",
                        help="同時輸出該行政區的分區資料集目錄。")
    parser.add_argument("--overwrite", action="store_true", help="允許覆寫既有輸出檔。")
    parser.add_argument("--list-areas", action="store_true",
                        help="列出新北市 29 個行政區後結束。")
    args = parser.parse_args(argv)

    if args.list_areas:
        print("、".join(NTPC_DISTRICTS))
        return 0

    try:
        area = normalize_district(args.area)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.catalog:
        catalog = search_district_datasets(area, timeout=args.timeout)
        path = save_json(catalog, out_dir / f"{area}分區資料集目錄.json",
                         overwrite=args.overwrite)
        print(f"{area} 分區資料集 {len(catalog)} 筆 -> {path}")

    def show(done, total, label):
        print(f"  [{done}/{total}] {label}", flush=True)

    report = fetch_valuation_factors(
        area, school_year=args.school_year, timeout=args.timeout,
        include_heavy=args.include_heavy, max_workers=args.workers,
        include_raw=not args.no_raw, progress=show)
    path = save_json(report, out_dir / f"{area}查估因素.json", overwrite=args.overwrite)
    summary = summarize(report)
    (out_dir / f"{area}查估因素摘要.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\n-> {path}")
    return 0 if report["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(_main())
