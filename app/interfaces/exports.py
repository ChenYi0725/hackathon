"""HTTP export presentation; domain calculations are supplied by the use case."""
import csv
import html
import io
from urllib.parse import quote
from fastapi.responses import Response, HTMLResponse

def csv_safe(value):
    s='' if value is None else str(value)
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s


def export_case(case, result, rules, kind: str, generated_at: str):
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
    esc=lambda value:html.escape('待補' if value is None or value == '' else str(value))
    statuses={'pass':'通過','error':'疑似錯誤','pending':'待確認','missing':'資料不足'}
    source_label=lambda row: ('原文 p.'+str(row['page']) if row.get('page') else '未記錄來源頁碼') + (' / 基準 p.'+str(row['rule_page']) if row.get('rule_page') else '')
    if kind=='report':
        head='<tr><th>檢核項目</th><th>狀態</th><th>原填</th><th>預期</th><th>依據與說明</th></tr>'
        rows=''.join(f'<tr><td>{esc(r["title"])}</td><td>{statuses[r["status"]]}</td><td>{esc(r["actual"])}</td><td>{esc(r["expected"])}</td><td>{esc(r["message"])}<br>{esc(source_label(r))}</td></tr>' for r in result['checks'])
        content='<h2>逐項審查結果</h2><table>'+head+rows+'</table>'
    else:
        content='<p>原填資料與程式重算分欄呈現；重算值供核對，不會自動覆寫案件。</p>'
        factor_checks={row.get('factor_id'):row for row in result['checks'] if row.get('factor_id')}
        def condition(value, grade, unit, options):
            raw=esc(value) + (' '+esc(unit) if value is not None and unit else '')
            if not unit and 1 < len(options) <= 6 and value in options:
                raw=' '.join(('☑' if value==option else '☐')+esc(option) for option in options)
            return raw + ('<br>等級：'+esc(grade) if grade is not None else '')
        for scope,title in [('regional','表 1 / 表 5-2 · 區域條件與修正率整理'),('individual','表 4 · 比較法調查估價整理')]:
            rows=''
            for r in rules['rules']:
                if r['scope']!=scope:continue
                f=next((f for f in case.factors if f.id==r['id']),None)
                if f:
                    expected=factor_checks.get(f.id, {}).get('expected')
                    options=list(dict.fromkeys(v for band in r['bands'] for v in (band.get('values') or [])))
                    rows+=f'<tr><td>{esc(r["name"])}</td><td>{condition(f.subject,f.subject_grade,r["unit"],options)}</td><td>{condition(f.comparable,f.comparable_grade,r["unit"],options)}</td><td>{esc(f.entered_rate)}{"%" if f.entered_rate is not None else ""}</td><td>{esc(expected) if expected is not None else "待確認／資料不足"}{"%" if expected is not None else ""}</td><td>{"已核對" if f.confirmed else "待確認"}</td></tr>'
            content+=f'<h2>{title}</h2><table><tr><th>因素</th><th>比準地</th><th>比較標的</th><th>原填修正率</th><th>基準重算</th><th>資料狀態</th></tr>{rows}</table>'
        labels={'normal_price':'土地正常單價','time_rate':'日期調整率','adjusted_price':'估價基準日單價',
                'regional_detail':'區域因素總修正數','regional_carried':'跨表區域調整率','individual':'個別因素合計',
                'absolute':'調整率絕對值加總','trial_price':'試算價格','weight':'權重'}
        content+='<h2>表 4 · 計算欄位</h2><table><tr><th>欄位</th><th>原填值</th><th>程式重算（供核對）</th></tr>'
        for key,value in case.totals.model_dump().items():
            calculations=[row for row in result['checks'] if row.get('total_field')==key and row.get('expected') is not None]
            calculated='<br>'.join(esc(row['title'])+'：'+esc(row['expected']) for row in calculations) or '待確認／資料不足或屬輸入值'
            content+=f'<tr><td>{esc(labels.get(key,key))}</td><td>{esc(value)}</td><td>{calculated}</td></tr>'
        content+='</table><p>此為整理書表，未覆寫原始 PDF 或套印官方格式。</p>'
    if case.field_sources:
        factor_names={rule['id']:rule['name'] for rule in rules['rules']}
        content+='<h2>自動選填來源</h2><table><tr><th>項目／欄位</th><th>填入值</th><th>來源與方法</th></tr>'
        for source in case.field_sources:
            content+=f'<tr><td>{esc(factor_names.get(source.factor_id,"計算欄位"))} / {esc(source.field)}</td><td>{esc(source.value)}</td><td>{esc(source.reference)}<br>{esc(source.detail)}</td></tr>'
        content+='</table>'
    warnings=''.join('<li>'+esc(warning)+'</li>' for warning in case.extraction_warnings)
    if warnings: content='<div class="notice"><strong>匯入限制與待確認事項</strong><ul>'+warnings+'</ul></div>'+content
    doc=f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>{esc(case.title)}</title>
    <style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;color:#183b38;padding:0 20px}}h1{{font-size:26px}}h2{{font-size:18px;margin-top:32px}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{border:1px solid #ccc;padding:9px;text-align:left}}th{{background:#eef4f1}}.notice{{background:#fff4db;padding:16px}}button{{padding:12px}}@media print{{button{{display:none}}tr{{break-inside:avoid}}thead{{display:table-header-group}}}}</style>
    <h1>沒有錯的地方 · {esc(case.title)}</h1>
    <p>案號 {esc(case.case_number)} · 基準日 {esc(case.valuation_date)} · 案件版本 {case.revision}</p>
    <p>比準地：{esc(case.subject_name)}（{esc(case.subject_address)}） ／ 比較標的：{esc(case.comparable_name)}（{esc(case.comparable_address)}）</p>
    <p>基準：{esc(result['ruleset_id'])} / {esc(result['ruleset_version'])}</p>
    <div class="notice">{'人工植入錯誤之示範案件。' if case.demo else ''} 審查狀態：{'全部檢核通過' if result['complete'] else '尚有疑點或待確認項目'}。本文件為輔助審查草稿。</div>
    <p>{esc(case.notes)}</p>{content}<p>產出時間：{generated_at}</p></html>'''
    return HTMLResponse(doc)
