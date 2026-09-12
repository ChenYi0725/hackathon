from app.models import Case, Factor, Evidence, Totals
from app.rules import default_rules
from app.engine import classify


def sample_case(demo=False):
    values=[('113.21','111.85',0),('5','7',0),('23','16',1),('方形','方形',0),
            ('單面臨街','單面臨街',0),('平坦','平坦',0),('主要道路','次要道路',2),('18','6',5),
            ('150','100',0),('30','92',0),('190','200',0),('80','190',0),('0','0',0),
            ('260','80',3),('可路邊停車','不可路邊停車',2),('第二種商業區','第二種商業區',0),
            ('70','70',0),('240','240',0),('無','無',0)]
    region=['都市計畫內','第二種商業區','70','240','無','無','18','12','300','區段內有','無',
            '已完全開發','有排水系統不易淹水','該區地勢平坦','區段內有','區段內有','區段內有','120',
            '440','80','無','無','無','210','無','850','顧客通行量多','90']
    factors=[]
    rules=default_rules()['rules']
    for r,(a,b,rate) in zip(rules[:19],values):
        factors.append(Factor(id=r['id'],subject=a,comparable=b,entered_rate=rate,confirmed=True,
            evidence=Evidence(page=3,quote=f'{r["name"]}：比準地 {a}；比較標的 {b}；差異率 {rate}%',method='curated')))
    for r,v in zip(rules[19:],region):
        idx=classify(v,r)
        grade=r['bands'][idx]['label'] if idx is not None else ('劣' if r['id']=='r_interchange' else '優')
        factors.append(Factor(id=r['id'],subject=v,comparable=v,entered_rate=0,confirmed=True,
            subject_grade=grade,comparable_grade=grade,
            evidence=Evidence(page=1,quote=f'{r["name"]}：{v}；表 5-2 比較雙方同為 P002-00 區段。',method='curated')))
    c=Case(title='金山區商業用地｜原始範例',case_number='1140901-99-001',valuation_date='1140901',
           subject_name='金美段 489 地號',comparable_name='溫泉段 218 地號',subject_section='P002-00',comparable_section='P002-00',
           source_kind='curated',factors=factors,totals_confirmed=True,
           totals=Totals(regional_detail=0,regional_carried=0,individual=13,absolute=15,time_rate=2,
                         normal_price=184763,adjusted_price=188459,trial_price=212958,weight=100),
           notes='依提供範本人工整理。僅選一筆比較標的之理由見原表 4 全案備註。區域設施採相關設施最近距離；原始 PDF 為證據來源。')
    if demo:
        c.title='金山區商業用地｜錯誤示範';c.demo=True
        c.factors[7].entered_rate=2
        c.factors[8].subject=None
        c.totals.individual=12;c.totals.regional_carried=2
        c.notes='人工植入測試：道路修正率 5→2%、學校距離清空、個別合計 13→12%、跨表區域修正率 0→2%。原始 PDF 未修改。'
    return c
