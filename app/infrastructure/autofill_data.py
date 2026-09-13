"""Reuse registered NTPC/MOE clients; never treat district candidates as parcel facts."""
from urllib.parse import urlparse
import ntpc_shulin_api as source


class GovernmentFieldData:
    def catalog(self):
        return [dict(key=s['key'], item=s['item'], name=s['source_name'], heavy=s['heavy'], school_year_required=False)
                for s in source.NTPC_SOURCES] + [
                    dict(key=s['key'], item='接近學校之程度', name=s['name'], heavy=False, school_year_required=True)
                    for s in source._school_sources(114)]

    def lookup(self, locality, source_keys, school_year):
        registered = {item['key']: item for item in self.catalog()}
        if any(key not in registered for key in source_keys):
            raise ValueError('未登錄的政府資料來源。')
        allowed, gaps = [], []
        for key in dict.fromkeys(source_keys):
            item = registered[key]
            if item['heavy']:
                gaps.append(dict(source_key=key, reason='大型資料集需另行查詢，未當成無資料。'))
            elif item['school_year_required'] and school_year is None:
                gaps.append(dict(source_key=key, reason='缺少明示學年度。'))
            else:
                allowed.append(key)
        # An empty only_source_keys means ALL datasets to the legacy client.
        if not allowed:
            return dict(sources=[], candidates=[], gaps=gaps)
        try:
            report = source.fetch_valuation_factors(locality, school_year=school_year or 114,
                only_source_keys=tuple(allowed), include_heavy=False, include_raw=False,
                max_workers=6, timeout=15, use_cache=True)
        except (ValueError, RuntimeError, OSError):
            return dict(sources=[], candidates=[], gaps=gaps + [dict(reason='政府資料查詢失敗或地區不支援；未填零或無。')])
        references = []
        for item in report.get('sources', []):
            url = str(item.get('url', ''))
            if urlparse(url).scheme != 'https' or urlparse(url).hostname not in {'data.ntpc.gov.tw', 'stats.moe.gov.tw'}:
                continue
            references.append(dict(key=item['key'], title=item['name'], url=url, status=item['status'],
                fetched_at=report['fetched_at'], period=item.get('period', ''), historical_applicability='unverified'))
        records = [row for group in report['factors'] for row in group['records']]
        candidates = [{key: row.get(key) for key in ('source_key', 'name', 'address', 'category',
            'twd97_x', 'twd97_y', 'longitude', 'latitude', 'source_url', 'school_year')} for row in records[:200]
            if row.get('source_key') in allowed and urlparse(str(row.get('source_url', ''))).scheme == 'https'
            and urlparse(str(row.get('source_url', ''))).hostname in {'data.ntpc.gov.tw', 'stats.moe.gov.tw'}]
        return dict(sources=references, candidates=candidates, gaps=gaps,
            record_count=len(records), truncated=len(records)>200,
            warning='清冊候選不代表地價區段內存在；地址／地號定位、歷史適用性及量測方式尚須確認。')


class RepositoryAutofillDrafts:
    def __init__(self, repository):
        self.repository = repository

    def put(self, token, data):
        self.repository.cache_put('autofill-v1:' + token, data)
        with self.repository.db() as db:
            db.execute("DELETE FROM extraction_cache WHERE key IN (SELECT key FROM extraction_cache WHERE key LIKE 'autofill-v1:%' ORDER BY rowid DESC LIMIT -1 OFFSET 100)")

    def get(self, token):
        return self.repository.cache_get('autofill-v1:' + token)
