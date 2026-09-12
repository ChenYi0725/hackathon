import csv
import html
import io
import json
import math
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from app import store
from app.engine import review, number
from app.extraction import read_pdf, parse_case, ai_extract
from app.models import Case, Factor
from app.sample import sample_case


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    with store.db() as db:
        empty=db.execute('SELECT COUNT(*) FROM cases').fetchone()[0]==0
    if empty:
        docid=register_sample()
        for demo in [False,True]:
            case=sample_case(demo);case.document_id=docid
            store.save_case(case,'建立內建範例',new=True)
    yield


app=FastAPI(title='地衡 · 估價審查工作台',version='1.0.0',lifespan=lifespan)


@app.middleware('http')
async def local_mutations(request,call_next):
    # No CORS. Prevent an unrelated website from writing to a running local instance.
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
            return Response('Cross-origin mutation is not permitted',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    return response


@app.exception_handler(KeyError)
async def missing(request,exc):return Response('找不到案件、文件或基準。',status_code=404)


@app.exception_handler(ValueError)
async def invalid(request,exc):return Response(str(exc),status_code=400)


def register_sample():
    path=store.ROOT/'查估書表範本.pdf'
    if not path.exists():return None
    with store.db() as db:
        db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?)',('sample',path.name,str(path),json.dumps(read_pdf(path.read_bytes()),ensure_ascii=False)))
    return 'sample'


def payload(case):
    return dict(case=case.model_dump(),review=review(case,store.get_rules(case.ruleset_id)))


def validate_case(case):
    rules=store.get_rules(case.ruleset_id)
    ids=[f.id for f in case.factors]
    if len(ids)!=len(set(ids)):raise ValueError('因素 ID 不可重複。')
    if case.document_id:store.document(case.document_id)
    return rules


@app.get('/api/health')
def health():return dict(status='ok',ai_configured=bool(os.getenv('OLLAMA_MODEL')),ai_model=os.getenv('OLLAMA_MODEL',''),version='1.0.0')


@app.get('/api/cases')
def list_cases():
    with store.db() as db:rows=db.execute('SELECT body,updated FROM cases ORDER BY updated DESC').fetchall()
    result=[]
    for row in rows:
        case=Case.model_validate_json(row['body']);p=payload(case)
        result.append(dict(id=case.id,title=case.title,case_number=case.case_number,demo=case.demo,updated=row['updated'],counts=p['review']['counts'],source_kind=case.source_kind))
    return result


@app.post('/api/cases')
def create_case(case: Case):
    validate_case(case);return payload(store.save_case(case,'建立或匯入案件',new=True))


@app.post('/api/samples/{kind}')
def create_sample(kind: str):
    if kind not in ['original','errors']:raise ValueError('未知的範例類型。')
    case=sample_case(kind=='errors');case.document_id=register_sample()
    return payload(store.save_case(case,'建立範例副本',new=True))


@app.get('/api/cases/{cid}')
def get_case(cid: str):return payload(store.get_case(cid))


@app.put('/api/cases/{cid}')
def update_case(cid: str,case: Case):
    if case.id!=cid:raise ValueError('案件 ID 不符。')
    validate_case(case)
    return payload(store.save_case(case,'儲存欄位與重新審查'))


@app.post('/api/cases/{cid}/fix/{check_id}')
def fix_check(cid: str,check_id: str,body: dict):
    case=store.get_case(cid)
    if body.get('revision')!=case.revision:raise ValueError('案件已更新，請重新載入。')
    result=review(case,store.get_rules(case.ruleset_id))
    item=next((r for r in result['checks'] if r['id']==check_id),None)
    if not item or item['status']!='error' or item['expected'] is None:raise ValueError('此項目前沒有可直接採用的修正建議。')
    if item.get('factor_id'):
        factor=next(f for f in case.factors if f.id==item['factor_id'])
        factor.entered_rate=item['expected']
        if factor.subject_grade is not None:factor.subject_grade=item['subject_grade']
        if factor.comparable_grade is not None:factor.comparable_grade=item['comparable_grade']
    elif item.get('total_field'):setattr(case.totals,item['total_field'],item['expected'])
    else:raise ValueError('請手動處理此項。')
    return payload(store.save_case(case,'採用建議：'+item['title']))


@app.get('/api/cases/{cid}/audit')
def audit(cid: str):
    store.get_case(cid)
    with store.db() as db:
        return [dict(r) for r in db.execute('SELECT id,action,at FROM audit WHERE case_id=? ORDER BY id DESC',(cid,)).fetchall()]


@app.get('/api/cases/{cid}/audit/{aid}')
def audit_snapshot(cid: str,aid: int):
    with store.db() as db:row=db.execute('SELECT snapshot FROM audit WHERE case_id=? AND id=?',(cid,aid)).fetchone()
    if not row:raise KeyError(aid)
    return json.loads(row['snapshot'])


@app.post('/api/documents')
async def upload(request: Request):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>20*1024*1024:raise HTTPException(413,'PDF 上限 20 MB。')
    try:pages=await run_in_threadpool(read_pdf,bytes(data))
    except Exception as e:
        raise HTTPException(422,'PDF 無法解析：'+str(e)[:200]) from e
    docid=uuid.uuid4().hex
    name=request.query_params.get('name','案件.pdf')[:200]
    path=store.DATA/'uploads'/f'{docid}.pdf';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    with store.db() as db:db.execute('INSERT INTO documents VALUES (?,?,?,?)',(docid,name,str(path),json.dumps(pages,ensure_ascii=False)))
    case=parse_case(pages,Path(name).stem[:140] or '匯入案件');case.document_id=docid
    return payload(store.save_case(case,'上傳 PDF 與版面抽取',new=True))


@app.get('/api/documents/{docid}')
def get_document(docid: str):
    doc=store.document(docid)
    return dict(id=docid,name=doc['name'],pages=json.loads(doc['pages']))


@app.get('/api/documents/{docid}/file')
def get_file(docid: str):
    doc=store.document(docid)
    return FileResponse(doc['path'],media_type='application/pdf',headers={'Content-Disposition':"inline; filename*=UTF-8''"+quote(doc['name'])})


@app.get('/api/reference/{kind}')
def reference(kind: str):
    names={'rules':'評價基準明細表範例.pdf','manual':'土地徵收補償市價查估作業手冊.pdf','brief':'【命題文件】地政局-新北市政府AI黑客松競賽.pdf'}
    if kind not in names:raise KeyError(kind)
    path=store.ROOT/names[kind]
    if not path.exists():raise KeyError(kind)
    return FileResponse(path,media_type='application/pdf')


@app.post('/api/cases/{cid}/ai')
def extract_ai(cid: str,body: dict):
    case=store.get_case(cid)
    if body.get('revision')!=case.revision:raise ValueError('案件已更新，請重新載入。')
    if not case.document_id:raise ValueError('請先匯入 PDF。')
    pages=json.loads(store.document(case.document_id)['pages'])
    try:extracted=ai_extract(pages)
    except Exception as exc:raise HTTPException(502,'本機 AI 抽取失敗：'+str(exc)[:250]) from exc
    # Return a preview. User explicitly accepts selected draft values in the editor.
    return dict(factors=[f.model_dump() for f in extracted],revision=case.revision,
                message='AI 草稿尚未套用。所有欄位皆須人工確認，原文引用已做文字存在性檢查。')


@app.get('/api/rulesets')
def rulesets():
    with store.db() as db:return [json.loads(r['body']) for r in db.execute('SELECT body FROM rulesets').fetchall()]


def validate_ruleset(r):
    for key in ['name','version','locality','land_use','source','direction']:
        if not isinstance(r.get(key),str) or not r[key].strip() or len(r[key])>500:raise ValueError('基準缺少有效欄位：'+key)
    rules=r.get('rules')
    if not isinstance(rules,list) or not 1<=len(rules)<=100:raise ValueError('基準需包含 1–100 項因素。')
    ids=set()
    for rule in rules:
        for key in ['id','name','group','unit','scope']:
            if not isinstance(rule.get(key),str):raise ValueError('規則欄位格式錯誤：'+key)
        if not rule['id'] or rule['id'] in ids:raise ValueError('規則 ID 不可空白或重複。')
        ids.add(rule['id'])
        if rule['scope'] not in ['individual','regional']:raise ValueError('scope 必須為 individual 或 regional。')
        if not isinstance(rule.get('source_page'),int) or not 1<=rule['source_page']<=200:raise ValueError('來源頁碼必須為 1–200。')
        bands=rule.get('bands');matrix=rule.get('matrix')
        if not isinstance(bands,list) or not 2<=len(bands)<=20:raise ValueError('等級數應為 2–20。')
        n=len(bands)
        if not isinstance(matrix,list) or len(matrix)!=n or any(not isinstance(row,list) or len(row)!=n for row in matrix):raise ValueError('矩陣尺寸必須符合等級數。')
        if any(number(v) is None or abs(number(v))>1000 for row in matrix for v in row):raise ValueError('矩陣必須為有限數值，範圍 ±1000。')
        if any(number(matrix[i][i])!=0 for i in range(n)):raise ValueError('矩陣同級修正率必須為 0。')
        values=set();labels=set();intervals=[]
        for b in bands:
            if not isinstance(b,dict) or not isinstance(b.get('label'),str) or not b['label'] or b['label'] in labels:raise ValueError('等級標籤不可空白或重複。')
            labels.add(b['label'])
            aliases=b.get('values') or []
            if not isinstance(aliases,list) or any(not isinstance(v,str) or not v for v in aliases):raise ValueError('分類值應為非空白字串陣列。')
            if values.intersection(aliases) or len(aliases)!=len(set(aliases)):raise ValueError('分類值不能同時出現在多個等級。')
            values.update(aliases)
            if not rule['unit']:
                if not aliases:raise ValueError('文字規則每個等級須有分類值。')
                continue
            if aliases and b.get('low',0)==0 and b.get('high') is None and not b.get('ranges'):continue
            ranges=b.get('ranges') or [[b.get('low',0),b.get('high')]]
            if not isinstance(ranges,list):raise ValueError('ranges 格式錯誤。')
            for pair in ranges:
                if not isinstance(pair,list) or len(pair)!=2:raise ValueError('級距須為 [下限, 上限]。')
                lo,hi=pair
                if number(lo) is None or number(lo)<0 or (hi is not None and (number(hi) is None or number(hi)<=number(lo))):raise ValueError('級距上下限錯誤。')
                intervals.append((number(lo),number(hi)))
        intervals.sort(key=lambda p:p[0])
        for a,b in zip(intervals,intervals[1:]):
            if a[1] is None or a[1]>b[0]:raise ValueError('數值級距不可重疊。')
    return r


@app.post('/api/rulesets')
def create_ruleset(body: dict):
    r=validate_ruleset(body)
    r['id']='custom-'+uuid.uuid4().hex
    with store.db() as db:db.execute('INSERT INTO rulesets VALUES (?,?)',(r['id'],json.dumps(r,ensure_ascii=False)))
    return r


def csv_safe(value):
    s='' if value is None else str(value)
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s


@app.get('/api/cases/{cid}/export/{kind}')
def export(cid: str,kind: str):
    case=store.get_case(cid);result=review(case,store.get_rules(case.ruleset_id))
    filename=f'review-{case.case_number or case.id}'
    headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename)}
    if kind=='json':
        headers['Content-Disposition']+='.json'
        return Response(case.model_dump_json(indent=2),media_type='application/json',headers=headers)
    if kind=='csv':
        stream=io.StringIO(newline='');writer=csv.writer(stream)
        writer.writerow(['檢核項目','狀態','原填值','預期值','說明','原文頁碼','基準頁碼'])
        for r in result['checks']:writer.writerow([csv_safe(r.get(k)) for k in ['title','status','actual','expected','message','page','rule_page']])
        headers['Content-Disposition']+='.csv'
        return Response('\ufeff'+stream.getvalue(),media_type='text/csv; charset=utf-8',headers=headers)
    if kind not in ['report','forms']:raise KeyError(kind)
    esc=lambda value:html.escape('—' if value is None else str(value))
    statuses={'pass':'通過','error':'疑似錯誤','pending':'待確認','missing':'資料不足'}
    if kind=='report':
        head='<tr><th>檢核項目</th><th>狀態</th><th>原填</th><th>預期</th><th>依據與說明</th></tr>'
        rows=''.join(f'<tr><td>{esc(r["title"])}</td><td>{statuses[r["status"]]}</td><td>{esc(r["actual"])}</td><td>{esc(r["expected"])}</td><td>{esc(r["message"])}<br>原文 p.{esc(r.get("page"))} / 基準 p.{esc(r.get("rule_page"))}</td></tr>' for r in result['checks'])
        content='<h2>逐項審查結果</h2><table>'+head+rows+'</table>'
    else:
        content=''
        rules=store.get_rules(case.ruleset_id)
        for scope,title in [('regional','表 1 / 表 5-2 · 區域條件與修正率整理'),('individual','表 4 · 比較法調查估價整理')]:
            rows=''
            for r in rules['rules']:
                if r['scope']!=scope:continue
                f=next((f for f in case.factors if f.id==r['id']),None)
                if f:rows+=f'<tr><td>{esc(r["name"])}</td><td>{esc(f.subject)} {esc(r["unit"])}</td><td>{esc(f.comparable)} {esc(r["unit"])}</td><td>{esc(f.entered_rate)}%</td><td>{"已核對" if f.confirmed else "待確認"}</td></tr>'
            content+=f'<h2>{title}</h2><table><tr><th>因素</th><th>比準地</th><th>比較標的</th><th>修正率</th><th>資料狀態</th></tr>{rows}</table>'
        content+='<h2>表 4 · 計算欄位</h2><table>'+''.join(f'<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>' for k,v in case.totals.model_dump().items())+'</table><p>此為整理書表，未覆寫原始 PDF 或套印官方格式。</p>'
    doc=f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>{esc(case.title)}</title>
    <style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;color:#183b38;padding:0 20px}}h1{{font-size:26px}}h2{{font-size:18px;margin-top:32px}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{border:1px solid #ccc;padding:9px;text-align:left}}th{{background:#eef4f1}}.notice{{background:#fff4db;padding:16px}}button{{padding:12px}}@media print{{button{{display:none}}tr{{break-inside:avoid}}thead{{display:table-header-group}}}}</style>
    <button onclick="window.print()">列印 / 另存 PDF</button><h1>地衡 · {esc(case.title)}</h1>
    <p>案號 {esc(case.case_number)} · 基準日 {esc(case.valuation_date)} · 案件版本 {case.revision}</p>
    <p>比準地：{esc(case.subject_name)} ／ 比較標的：{esc(case.comparable_name)}</p>
    <p>基準：{esc(result['ruleset_id'])} / {esc(result['ruleset_version'])}</p>
    <div class="notice">{'人工植入錯誤之示範案件。' if case.demo else ''} 審查狀態：{'全部檢核通過' if result['complete'] else '尚有疑點或待確認項目'}。本文件為輔助審查草稿。</div>
    <p>{esc(case.notes)}</p>{content}<p>產出時間：{store.now()}</p></html>'''
    return HTMLResponse(doc)


app.mount('/static',StaticFiles(directory=store.ROOT/'static'),name='static')


@app.get('/')
def index():return FileResponse(store.ROOT/'static'/'index.html')
