"""開放資料查估因素 API。

包裝 ntpc_shulin_api，提供表3／表5-1 各欄位的候選設施查詢。

端點分三類：
  即時（不連網）  /areas /coverage /gaps  —— 純本地登錄表，毫秒回應
  同步（會連網）  /factors                —— 建議搭配 factor 篩選或快取
  非同步          /jobs                   —— 整區完整抓取，輪詢取結果

整區未命中快取約需數十秒到數分鐘（約 40 個上游請求），所以預設開快取，
並以 semaphore 限制同時只有一份報表在建，避免對公開服務造成壓力。
"""

import threading
import time
import uuid
from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

import ntpc_shulin_api as source

router=APIRouter(prefix='/api/opendata',tags=['opendata'])

# 上游是公開服務，同時只建一份報表；下載並行度由 max_workers 控制。
BUILD_LOCK=threading.Semaphore(1)
WORKERS=6
JOB_LIMIT=20
JOB_POOL_SIZE=2

source.enable_dataset_cache(True,ttl=3600,max_rows=250_000)

_jobs={}
_jobs_lock=threading.Lock()
_job_pool=None
_job_pool_lock=threading.Lock()


def pool():
    global _job_pool
    with _job_pool_lock:
        if _job_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _job_pool=ThreadPoolExecutor(max_workers=JOB_POOL_SIZE,thread_name_prefix='opendata-job')
        return _job_pool


def shutdown():
    global _job_pool
    with _job_pool_lock:
        if _job_pool is not None:_job_pool.shutdown(wait=False,cancel_futures=True);_job_pool=None


def area_or_400(area):
    # normalize_district 對未知行政區拋 ValueError，交由全域處理器轉 400。
    return source.normalize_district(area)


def factors_or_400(factor):
    if not factor:return None
    known={s['factor'] for s in source.NTPC_SOURCES}|{i['factor'] for i in source.SURVEY_ONLY_ITEMS}
    unknown=[f for f in factor if f not in known]
    if unknown:raise ValueError('未知的主要項目：'+'、'.join(unknown)+'。可用值見 /api/opendata/coverage。')
    return tuple(factor)


def build(area,school_year,factors,include_heavy,include_raw,progress=None):
    if not BUILD_LOCK.acquire(timeout=0.1):
        raise HTTPException(429,'已有另一份報表正在建立，請稍後重試或改用 /api/opendata/jobs。')
    try:
        return source.fetch_valuation_factors(area,school_year=school_year,only_factors=factors,
            include_heavy=include_heavy,include_raw=include_raw,max_workers=WORKERS,
            use_cache=True,progress=progress)
    finally:BUILD_LOCK.release()


@router.get('/areas')
def areas():
    """列出可查詢的行政區。城市固定為新北市。"""
    return dict(city=source.CITY_NAME,count=len(source.NTPC_DISTRICTS),areas=list(source.NTPC_DISTRICTS))


@router.get('/coverage')
def coverage():
    """表3／表5-1 欄位對應到哪些開放資料集，以及哪些欄位沒有資料來源。

    純本地登錄表，不連網。前端可用它先畫出欄位涵蓋狀況。
    """
    items={}
    for s in source.NTPC_SOURCES:
        key=(s['factor'],s['item'])
        items.setdefault(key,dict(factor=s['factor'],item=s['item'],sources=[],survey_only=[]))
        items[key]['sources'].append(dict(key=s['key'],name=s['source_name'],category=s['category'],
            dataset_id=s['dataset_id'],dataset_url=f"{source.NTPC_BASE}/datasets/{s['dataset_id']}",
            heavy=s['heavy'],loose_name_match=s['loose_name_match'],
            has_coordinates=bool(s['lon_keys'] or s['twd97_keys']),notes=list(s['notes'])))
    for i in source.SURVEY_ONLY_ITEMS:
        key=(i['factor'],i['item'])
        items.setdefault(key,dict(factor=i['factor'],item=i['item'],sources=[],survey_only=[]))
        items[key]['survey_only'].append(dict(category=i['category'],reason=i['reason']))
    result=sorted(items.values(),key=lambda x:(x['factor'],x['item']))
    for x in result:x['source_count']=len(x['sources']);x['survey_required']=not x['sources'] or bool(x['survey_only'])
    return dict(city=source.CITY_NAME,factors=sorted({x['factor'] for x in result}),
        items=result,warnings=list(source.GLOBAL_WARNINGS))


@router.get('/gaps')
def gaps():
    """只列出沒有開放資料來源的欄位，提醒必須現地勘查、不可勾「無」。"""
    return dict(count=len(source.SURVEY_ONLY_ITEMS),
        items=[dict(i) for i in source.SURVEY_ONLY_ITEMS],
        notice='查無資料不等於設施不存在。這些欄位不可自動勾選「無」或填零距離。')


@router.get('/factors')
async def factors(area: str=Query(...,description='行政區，例如 金山區'),
                  school_year: int=Query(114,ge=103,le=200),
                  factor: list[str]|None=Query(None,description='限定主要項目，可重複給值'),
                  include_heavy: bool=Query(False,description='併抓公車站位與工廠登記，很慢'),
                  include_raw: bool=Query(False,description='是否附上每筆的 raw 原始欄位')):
    """同步取得查估因素報表。

    未命中快取時整區約需數十秒到數分鐘。建議先用 factor 縮小範圍，
    或改用 POST /api/opendata/jobs 非同步執行。
    """
    name=area_or_400(area)
    wanted=factors_or_400(factor)
    started=time.monotonic()
    report=await run_in_threadpool(build,name,school_year,wanted,include_heavy,include_raw)
    report['elapsed_s']=round(time.monotonic()-started,2)
    return report


@router.get('/summary')
async def summary(area: str=Query(...),school_year: int=Query(114,ge=103,le=200),
                  factor: list[str]|None=Query(None),include_heavy: bool=Query(False)):
    """同 /factors 但只回統計與文字摘要，不含逐筆記錄。"""
    name=area_or_400(area)
    wanted=factors_or_400(factor)
    report=await run_in_threadpool(build,name,school_year,wanted,include_heavy,False)
    return dict(city=report['city'],district=report['district'],school_year=report['school_year'],
        status=report['status'],record_count=report['record_count'],
        reference_bbox=report['reference_bbox'],fetched_at=report['fetched_at'],
        items=[dict(factor=f['factor'],item=f['item'],status=f['status'],
            survey_required=f['survey_required'],record_count=f['record_count'],
            categories=_categories(f['records'])) for f in report['factors']],
        loose_match_rejected=report['loose_match_rejected'],errors=report['errors'],
        text=source.summarize(report),warnings=report['warnings'])


def _categories(records):
    counts={}
    for r in records:counts[r['category']]=counts.get(r['category'],0)+1
    return dict(sorted(counts.items(),key=lambda kv:-kv[1]))


@router.get('/catalog')
async def catalog(keyword: str=Query('',max_length=100),
                  unit: str|None=Query(None,description='機關代碼，例如 1110000；省略則搜全部')):
    """搜尋新北市資料開放平臺的資料集目錄（約 2900 筆）。"""
    if unit is not None:
        if unit not in source.NTPC_UNITS:
            raise ValueError('未知的機關代碼。可用值見 /api/opendata/units。')
        items=await run_in_threadpool(source.search_ntpc_datasets,keyword,unit_id=unit)
    else:
        items=await run_in_threadpool(source.search_all_ntpc_datasets,keyword)
    return dict(keyword=keyword,unit=unit,count=len(items),datasets=items)


@router.get('/units')
def units():
    """列出資料開放平臺的機關代碼。"""
    return [dict(unit_id=k,name=v) for k,v in source.NTPC_UNITS.items()]


@router.get('/areas/{area}/datasets')
async def area_datasets(area: str,keyword: str=Query('',max_length=100)):
    """找出以「-○○區」結尾的分區資料集，例如公告土地現值、實價登錄。"""
    name=area_or_400(area)
    items=await run_in_threadpool(source.search_district_datasets,name,keyword)
    return dict(area=name,keyword=keyword,count=len(items),datasets=items)


def run_job(jid,area,school_year,factors,include_heavy,include_raw):
    def progress(done,total,label):
        with _jobs_lock:
            job=_jobs.get(jid)
            if job is not None:job['progress']=dict(done=done,total=total,current=label)
    with _jobs_lock:
        if _jobs.get(jid,{}).get('status')!='queued':return
        _jobs[jid]['status']='running';_jobs[jid]['started_at']=time.time()
    try:
        report=build(area,school_year,factors,include_heavy,include_raw,progress)
    except Exception as exc:
        with _jobs_lock:
            job=_jobs.get(jid)
            if job is not None:
                job.update(status='error',error=str(exc)[:500],finished_at=time.time())
        return
    with _jobs_lock:
        job=_jobs.get(jid)
        if job is not None:
            job.update(status='done',result=report,finished_at=time.time(),
                record_count=report['record_count'])


@router.post('/jobs',status_code=202)
def create_job(body: dict|None=None):
    """非同步建立整區報表。回傳 job_id，之後輪詢 GET /jobs/{job_id}。

    body 欄位：area（必填）、school_year、factors、include_heavy、include_raw。
    """
    body=body or {}
    if not isinstance(body,dict):raise ValueError('請傳送 JSON 物件。')
    name=area_or_400(body.get('area',''))
    school_year=body.get('school_year',114)
    if type(school_year) is not int or not 103<=school_year<=200:
        raise ValueError('school_year 請填 103~200 的民國學年度整數。')
    raw_factors=body.get('factors')
    if raw_factors is not None and (not isinstance(raw_factors,list) or any(not isinstance(f,str) for f in raw_factors)):
        raise ValueError('factors 必須是字串陣列。')
    wanted=factors_or_400(raw_factors)
    for key in ('include_heavy','include_raw'):
        if key in body and not isinstance(body[key],bool):raise ValueError(f'{key} 必須是布林值。')
    jid=uuid.uuid4().hex
    with _jobs_lock:
        for old in sorted(_jobs,key=lambda k:_jobs[k]['created_at'])[:max(0,len(_jobs)+1-JOB_LIMIT)]:
            if _jobs[old]['status'] in ('done','error'):del _jobs[old]
        _jobs[jid]=dict(id=jid,status='queued',area=name,school_year=school_year,
            factors=list(wanted) if wanted else None,include_heavy=bool(body.get('include_heavy',False)),
            include_raw=bool(body.get('include_raw',False)),created_at=time.time(),
            progress=dict(done=0,total=None,current=None),result=None,error=None)
    pool().submit(run_job,jid,name,school_year,wanted,
        bool(body.get('include_heavy',False)),bool(body.get('include_raw',False)))
    return dict(job_id=jid,status='queued',poll='/api/opendata/jobs/'+jid)


@router.get('/jobs')
def list_jobs():
    with _jobs_lock:
        return [{k:v for k,v in job.items() if k!='result'} for job in
                sorted(_jobs.values(),key=lambda j:-j['created_at'])]


@router.get('/jobs/{jid}')
def get_job(jid: str,include_result: bool=Query(True)):
    """查詢工作狀態。result 一律存在，未完成或未索取時為 null，回應形狀固定。"""
    with _jobs_lock:
        job=_jobs.get(jid)
        if job is None:raise KeyError(jid)
        out=dict(job)
        out['result']=job['result'] if include_result and job['status']=='done' else None
    return out


@router.delete('/jobs/{jid}')
def delete_job(jid: str):
    with _jobs_lock:
        if jid not in _jobs:raise KeyError(jid)
        status=_jobs[jid]['status']
        if status=='queued':_jobs[jid]['status']='cancelled'
        elif status in ('done','error','cancelled'):del _jobs[jid]
        else:raise ValueError('工作正在執行中，無法取消。')
    return dict(id=jid,status='cancelled' if status=='queued' else 'deleted')


@router.get('/cache')
def cache_info():
    """回報資料集快取狀態。全市資料集在各行政區之間共用。"""
    return source.dataset_cache_info()


@router.post('/cache/clear')
def cache_clear():
    return dict(cleared_datasets=source.clear_dataset_cache())
