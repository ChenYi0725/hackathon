"""Validation of the valuation rule language."""
from app.domain.engine import number

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
