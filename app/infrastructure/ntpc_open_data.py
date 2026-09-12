"""NTPC official OAS discovery and bounded JSON pages. No case data is uploaded."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import ssl
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

import httpx

from app.application.open_data import DatasetSearch, DatasetRead, OpenDataUnavailable

BASE = 'https://data.ntpc.gov.tw'
DATASET_PATH = re.compile(r'^/api/datasets/([0-9a-fA-F-]{36})/json$')


class NtpcOpenData:
    def __init__(self, transport=None):
        self.transport = transport
        self._cache = OrderedDict()
        self._lock = Lock()
        # NTPC's certificate chain lacks SKI required by Python 3.13's strict
        # X.509 profile. Retain trusted-CA, expiry and hostname verification,
        # using the compatibility profile that Python 3.12 used by default.
        self._tls = ssl.create_default_context()
        self._tls.verify_flags &= ~ssl.VERIFY_X509_STRICT

    def _get(self, path, ttl):
        # Paths are built exclusively from validated inputs or matched OAS paths.
        with self._lock:
            cached = self._cache.get(path)
            if cached and monotonic() - cached[0] < ttl:
                return deepcopy(cached[1]), cached[2]
        try:
            with httpx.Client(transport=self.transport, verify=self._tls, timeout=10, follow_redirects=False) as client:
                with client.stream('GET', BASE + path, headers={'Accept': 'application/json'}) as response:
                    response.raise_for_status()
                    chunks, length = [], 0
                    for chunk in response.iter_bytes():
                        length += len(chunk)
                        if length > 8 * 1024 * 1024:
                            raise OpenDataUnavailable('官方回應過大，請縮小查詢。')
                        chunks.append(chunk)
                    value = json.loads(b''.join(chunks))
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise OpenDataUnavailable('新北市資料 API 暫時無法讀取，請稍後再試；此狀態不代表沒有資料。') from None
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._cache[path] = (monotonic(), deepcopy(value), timestamp)
            self._cache.move_to_end(path)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
        return value, timestamp

    def search(self, query: DatasetSearch):
        query = DatasetSearch.model_validate(query)
        terms = query.keyword.strip().casefold().split()
        if not terms:
            raise ValueError('請提供資料集關鍵字。')
        path = '/api/v1/openapi/units/' + query.unit
        spec, fetched_at = self._get(path, 3600)
        if not isinstance(spec, dict) or not isinstance(spec.get('paths'), dict):
            raise OpenDataUnavailable('官方 OpenAPI 目錄格式異常。')
        matches = []
        for route, operation in spec['paths'].items():
            match = DATASET_PATH.fullmatch(route)
            if not match or not isinstance(operation, dict):
                continue
            definition = operation.get('get', {})
            if not isinstance(definition, dict):
                continue
            title = str(definition.get('summary', ''))
            description = str(definition.get('description', ''))
            if all(term in (title + ' ' + description).casefold() for term in terms):
                matches.append(dict(dataset_id=match[1].lower(), title=title[:200],
                                    description=description[:300], url=BASE + route))
        return dict(datasets=matches[:10], matched_count=len(matches), truncated=len(matches) > 10,
                    source_url=BASE + path, fetched_at=fetched_at,
                    message='僅搜尋所選機關的資料集名稱與描述；多個關鍵字請用空格分開。超過十筆時請縮小關鍵字。')

    def read(self, query: DatasetRead):
        query = DatasetRead.model_validate(query)
        path = '/api/datasets/' + query.dataset_id.lower() + '/json?' + urlencode(dict(page=query.page, size=query.size))
        rows, fetched_at = self._get(path, 300)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise OpenDataUnavailable('官方資料格式異常，預期為 JSON 物件陣列。')
        if len(rows) > query.size:
            raise OpenDataUnavailable('官方 API 未遵守分頁上限，請改用其他資料集。')
        try:
            quote = json.dumps(rows, ensure_ascii=False, allow_nan=False)
        except ValueError:
            raise OpenDataUnavailable('官方資料包含無效數值。') from None
        if len(quote) > 8000:
            raise OpenDataUnavailable('這頁資料過長，請減少 size 後重試。')
        url = BASE + path
        identity = hashlib.sha256((url + fetched_at + quote).encode()).hexdigest()
        return dict(id=identity, dataset_id=query.dataset_id.lower(), source_url=url,
                    fetched_at=fetched_at, records=rows, quote=quote, page=query.page, size=query.size,
                    next_page=query.page + 1 if len(rows) == query.size and query.page < 10000 else None,
                    message='僅為此頁公開資料；取得時間不是資料生效日。未匹配或缺少欄位不代表數值為零或設施不存在；案件日期與適用性待人工確認。')
