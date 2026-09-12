"""Build an offline teaching pack without modifying any saved user cases."""
import html
import json
from pathlib import Path

from app.engine import review
from app.extraction import parse_case, read_pdf
from app.rules import default_rules
from app.sample import sample_case


def main():
    root = Path(__file__).resolve().parent.parent
    output = root / 'examples' / 'walkthrough'
    output.mkdir(parents=True, exist_ok=True)
    rules = default_rules()
    draft = parse_case(read_pdf((root / '查估書表範本.pdf').read_bytes()), '教學練習｜PDF 抽取草稿')
    reference = sample_case()
    reference.title = '教學對照｜原始範例審查答案'
    reference.notes += ' 本檔為教學對照資料，非主辦方官方標準答案；保留基準疑點與價格精度待確認項目。'
    result = review(reference, rules)
    individual = draft.model_copy(deep=True)
    for factor in individual.factors[:19]:
        factor.confirmed = True
    individual.totals_confirmed = True
    for name, value in [('01-pdf-draft.json', draft.model_dump()),
                        ('02-reference-case.json', reference.model_dump()),
                        ('03-reference-review.json', result)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    statuses = {'pass': '通過', 'error': '疑似錯誤', 'pending': '待確認', 'missing': '資料不足'}
    checks = {c['id']: c for c in result['checks']}
    text = [
        '# 原始 PDF 操作練習與參考答案', '',
        '這是依提供文件與目前程式產生的教學對照，並非主辦方官方答案。沒有修改工作台中的既有案件。', '',
        '## 操作順序', '',
        '1. 開啟 http://127.0.0.1:8000 ，選「匯入估價書表」，上傳專案根目錄的 `查估書表範本.pdf`。',
        '2. 在「資料核對 → 個別因素」依下表逐列核對原始 PDF 第 3 頁，確認後勾選「已核對原文」。',
        '3. 在「案件與計算」核對標的、區段、預設基準及計算欄位，勾選「已核對計算欄位及日期調整率」。',
        '4. 儲存並重新審查。19 項個別因素應通過，個別合計 13%。區域因素尚未確認是正常情況。',
        '5. 在「資料核對 → 區域因素」逐列對照 PDF 第 1 頁條件及第 2 頁等級，補齊空白並確認。',
        '6. 儲存後應得到 48 通過、0 疑似錯誤、5 待確認、3 資料不足。保留待處理事項，不要為了變綠而任意改值。',
        '7. 點「匯出成果 → 審查報告」，瀏覽器列印另存 PDF；另可匯出 CSV 與 JSON。', '',
        'JSON 可透過工作台「匯入案件 JSON」建立練習副本；此操作不附帶原始 PDF 連結。要練習原文對照，請從 PDF 上傳開始。', '',
        '## 每階段目前版本的預期計數', '',
        f'- 剛抽取、尚未確認：{review(draft, rules)["counts"]}',
        f'- 19 項個別因素與總計已確認：{review(individual, rules)["counts"]}',
        f'- 全部資料依範例補齊及核對：{result["counts"]}', '',
        '計數包含因素及額外的加總、跨表、價格檢核，故總數超過 47。', '',
    ]
    for scope, title in [('individual', '個別因素：原始 PDF 第 3 頁'), ('regional', '區域因素：條件見第 1 頁，原填等級見第 2 頁')]:
        text += ['## ' + title, '', '| 因素 | 比準地 | 比較標的 | 原填等級（比準地／比較標的） | 原填修正率 | 審查狀態 |',
                 '|---|---|---|---|---:|---|']
        for rule in rules['rules']:
            if rule['scope'] != scope:
                continue
            factor = next(f for f in reference.factors if f.id == rule['id'])
            unit = rule['unit']
            grades = f'{factor.subject_grade}／{factor.comparable_grade}' if scope == 'regional' else '原表未填等級，系統由條件判定'
            text.append(f'| {rule["name"]} | {factor.subject} {unit} | {factor.comparable} {unit} | {grades} | {factor.entered_rate:g}% | {statuses[checks[rule["id"]]["status"]]} |')
        text.append('')
    text += [
        '區域值「區段內有」與「無」是文字分類，勿輸入為 0。數字輸入框中不附單位。', '',
        '區域設施採本教學案例相關設施的最近距離：電業及氣體燃料為 440 m（加油站），殯葬為 80 m（公墓）。這是人工整理的案例處理方式，不表示程式已完成所有設施選擇的專業判斷。', '',
        '## 計算欄位：依原表抄錄', '',
        '| 欄位 | 原表值 |', '|---|---:|',
        '| 土地正常單價 | 184763 |', '| 日期調整率 | 2% |',
        '| 估價基準日單價 | 188459 |', '| 表 5-2 區域總修正數 | 0% |',
        '| 表 4 區域調整率 | 0% |', '| 個別因素合計 | 13% |',
        '| 調整率絕對值加總 | 15% |', '| 試算價格 | 212958 |', '| 比較標的權重 | 100% |', '',
        '13% = 深度 1% + 道路種類 2% + 道路寬度 5% + 嫌惡設施 3% + 停車 2%。',
        '15% = 日期調整 2% + 區域細項絕對值合計 0% + 個別細項絕對值合計 13%。', '',
        '## 最後仍保留的 8 個項目', '',
    ]
    for check in result['checks']:
        if check['status'] != 'pass':
            text.append(f'- **{check["title"]}／{statuses[check["status"]]}**：{check["message"]}')
    text += ['',
        '價格精度示例：184763 × 1.02 = 188458.26；188459 × 1.13 = 212958.67。原表分別為 188459 與 212958，請保留原值並核對原始計算式，不將 1 元落差直接當成錯誤。', '',
        '## 選做：測試能否抓到自己植入的錯誤', '',
        '從工作台點「建立錯誤示範」產生全新副本，不要覆寫原始案例。依序補回學校距離 150、道路修正率 5%、個別合計 13%、跨表區域率 0%。修正前後比較檢核結果，再檢視修訂紀錄。', '',
    ]
    (output / 'README.md').write_text('\n'.join(text), encoding='utf-8')
    escape = lambda x: html.escape('—' if x is None else str(x))
    rows = ''.join(f'<tr><td>{escape(c["title"])}</td><td>{statuses[c["status"]]}</td><td>{escape(c["actual"])}</td><td>{escape(c["expected"])}</td><td>{escape(c["message"])}</td></tr>' for c in result['checks'])
    page = f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>原始範例審查參考答案</title>
    <style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:20px;color:#23483e}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #ccd8cf;padding:10px;text-align:left}}th{{background:#edf3ed}}p{{line-height:1.8}}@media print{{button{{display:none}}tr{{break-inside:avoid}}}}</style>
    <button onclick="window.print()">列印／另存 PDF</button><h1>原始範例審查參考答案</h1>
    <p>案號 1140901-99-001。教學對照，非主辦方官方標準答案。比準地金美段 489 地號，比較標的溫泉段 218 地號。</p>
    <p>48 項通過、0 項疑似錯誤、5 項待確認、3 項資料不足。原表比較價格為 212,958 元／㎡，不代表已完成全部專業審查。</p>
    <table><thead><tr><th>項目</th><th>狀態</th><th>原填值</th><th>計算預期值</th><th>理由</th></tr></thead><tbody>{rows}</tbody></table></html>'''
    (output / '04-reference-answer.html').write_text(page, encoding='utf-8')
    print(json.dumps({'output': str(output), 'draft': review(draft, rules)['counts'],
                      'individual_confirmed': review(individual, rules)['counts'],
                      'reference': result['counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
