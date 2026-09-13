"""Agent adapter reuses the same government clients as /api/opendata."""
import hashlib
import json
import threading
from urllib.parse import urlparse
import ntpc_shulin_api as source
from app.application.ports import ExtractionUnavailable

LOOKUP_LOCK = threading.Semaphore(1)


class GovernmentDataLookup:
    def catalog(self):
        sources = [dict(key=s['key'], factor=s['factor'], item=s['item'], name=s['source_name'],
                        survey_required=True, heavy=s['heavy'], school_year_required=False)
                   for s in source.NTPC_SOURCES]
        sources += [dict(key=s['key'], factor='公共建設', item='學校', name=s['name'],
                         survey_required=True, heavy=False, school_year_required=True)
                    for s in source._school_sources(114)]
        return dict(sources=sources, gaps=[dict(i) for i in source.SURVEY_ONLY_ITEMS],
                    warning='候選設施不等於區段內設施；查無資料不等於不存在。未登錄 API 的欄位須補來源或勘查。')

    def lookup(self, locality, source_key, school_year):
        district = source.normalize_district(locality)
        registered = {s['key']: s for s in self.catalog()['sources']}
        item = registered.get(source_key)
        if item is None:
            raise ValueError('請選擇已登錄的資料來源。')
        if item['school_year_required'] and school_year is None:
            return dict(status='missing', missing_fields=['school_year'], sources=[], candidates=[])
        if item['heavy']:
            return dict(status='pending', sources=[], candidates=[],
                        warning='大型資料集請先使用既有開放資料報表查詢，Agent 不在單輪下載全市大型清冊。')
        if not LOOKUP_LOCK.acquire(timeout=0.1):
            raise ExtractionUnavailable('另一個政府資料查詢進行中，請稍後重試。')
        try:
            report = source.fetch_valuation_factors(
                district, school_year=school_year or 114, only_source_keys=(source_key,),
                include_heavy=False, include_raw=False, max_workers=1, timeout=15, use_cache=True,
            )
        except (OSError, ValueError):
            raise ExtractionUnavailable('政府資料來源暫時無法查詢，請稍後重試。') from None
        finally:
            LOOKUP_LOCK.release()
        records = [r for f in report['factors'] for r in f['records']]
        citations, candidates = {}, []
        for record in records[:10]:
            url = record.get('source_url', '')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in {'data.ntpc.gov.tw', 'stats.moe.gov.tw'}:
                continue
            citation = dict(title=str(record.get('source_name', item['name']))[:200], url=url,
                            fetched_at=report['fetched_at'], locality=locality,
                            kind='government-api', historical_applicability='unverified')
            identity = hashlib.sha256(json.dumps(citation, sort_keys=True).encode()).hexdigest()
            citations[identity] = dict(id=identity, **citation)
            allowed = ('name', 'address', 'category', 'longitude', 'latitude', 'twd97_x', 'twd97_y',
                       'coordinate_source', 'match_basis', 'school_year', 'factor', 'item')
            candidate = {k: (v[:300] if isinstance(v, str) else v)
                         for k in allowed if (v := record.get(k)) is not None}
            candidates.append(dict(candidate, citation_id=identity, confirmed=False,
                                   in_value_section=None, distance_m=None))
        return dict(status=report['status'], source_key=source_key, locality=locality,
                    sources=list(citations.values()), candidates=candidates, record_count=len(records),
                    truncated=len(records)>10, upstream_error_count=len(report.get('errors', [])),
                    warning='此為查詢時點的候選資料，須核對估價日期、標的位置、區段歸屬與量測方式；缺值不可填零。')
