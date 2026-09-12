"""Transcription of the supplied Jinshan commercial-land example, not legislation."""
from decimal import Decimal

LABELS = ['優', '稍優', '普通', '稍劣', '劣']


def band(label, low=0, high=None, values=None, ranges=None):
    return dict(label=label, low=low, high=high, values=values, ranges=ranges)


def numeric(bounds, descending=True):
    edges = [0, *sorted(bounds), None]
    result = [band('', edges[i], edges[i + 1]) for i in range(len(edges)-1)]
    if descending:
        result.reverse()
    for b, label in zip(result, LABELS):
        b['label'] = label
    return result


def categorical(values, labels=None):
    return [band(label, values=v if isinstance(v, list) else [v])
            for label, v in zip(labels or LABELS, values)]


def rule(key, name, group, unit, bands, step, page, scope='individual', **kw):
    n = len(bands)
    return dict(id=key, name=name, group=group, scope=scope, unit=unit, bands=bands,
                matrix=[[float(Decimal(str(step)) * (j-i)) for j in range(n)] for i in range(n)],
                source_page=page, **kw)


def default_rules():
    r = []
    def add(*args, **kwargs):
        r.append(rule(*args, **kwargs))
    add('area', '面積', '宗地條件', '㎡', numeric([63,73,83,93]), 2, 6)
    add('width', '寬度', '宗地條件', 'm', numeric([5,10,20,40]), 1, 6)
    depth = [band('優',40,100),band('稍優',30,40),band('普通',20,30),band('稍劣',10,20),
             band('劣',ranges=[[0,10],[100,None]])]
    add('depth','深度','宗地條件','m',depth,1,6)
    add('shape','形狀','宗地條件','',categorical(['方形','不規則形'],['優','劣']),5,6)
    add('frontage','臨街情形','宗地條件','',categorical(['3面以上臨街','路角地','雙面臨街','單面臨街','非臨街地']),2,6)
    add('terrain','地勢','宗地條件','',categorical(['平坦','緩坡','低窪'],['優','普通','劣']),1.5,6)
    add('road_type','道路種類','道路條件','',categorical(['主要道路','次要道路','巷道','既成巷道','私設巷道']),2,7)
    add('road_width','面前道路寬度','道路條件','m',numeric([4,8,15,20]),2.5,7)
    for key,name,bounds,step,page in [
        ('school','接近學校之程度',[200,600,1200,2000],1,7),
        ('market','接近市場之程度',[500,1000,1500,2000],2.5,7),
        ('park','接近公園、廣場之程度',[300,500,1000,1500],1,7),
        ('station','接近車站之程度',[300,400,600,800],1,7),
        ('business','接近商圈之程度',[500,1000,1800,2800],2,8)]:
        bands=numeric(bounds,False); bands[-1]['values']=['無']
        add(key,name,'接近條件','m',bands,step,page)
    bands=numeric([100,200,300,500]); bands[0]['values']=['無']
    add('nuisance','嫌惡設施','周邊環境條件','m',bands,1.5,8)
    add('parking','停車方便性','周邊環境條件','',categorical(['可路邊停車','不可路邊停車'],['優','劣']),2,8)
    add('zoning','使用分區或編定用地','行政條件','',categorical([
        ['商業區','第二種商業區'],['住宅區','第一種住宅區','第二種住宅區'],['甲建','乙建'],
        ['農業區建地目','保護區建地目'],['農業區已建築用地','保護區已建築用地']]),3.75,8)
    add('coverage','建蔽率','行政條件','%',numeric([50,60,70,80]),2.5,8)
    add('far','容積率','行政條件','%',numeric([120,200,240,300]),10,9)
    add('restriction','有無禁限建','行政條件','',categorical([['無','無禁止或限制建築'],['有','有禁止或限制建築']],['優','劣']),40,9)
    def region(key,name,group,unit,bands,step,page,**kw):
        add('r_'+key,name,group,unit,bands,step,page,scope='regional',**kw)
    region('plan','都市計畫內外','土地使用管制','',categorical(['都市計畫內','都市計畫外'],['優','劣']),20,1)
    region('zoning','使用分區','土地使用管制','',categorical(['第二種商業區','市場用地','第二種住宅區','第一種住宅區','其他分區']),5,1)
    region('coverage','建蔽率','土地使用管制','%',numeric([40,45,50,60]),2.5,1)
    region('far','容積率','土地使用管制','%',numeric([120,160,200,240]),10,1)
    for key,name in [('ban','有無禁止建築'),('restriction','有無限制建築')]:
        region(key,name,'土地使用管制','',categorical(['無','有'],['無','有']),40,1)
    region('road_width','主要道路寬度','交通運輸','m',numeric([10,15,20,30]),3.75,2)
    region('avg_width','區段內道路平均寬度','交通運輸','m',numeric([6,10,15,20]),2.5,2)
    region('station','接近大型車站之程度','交通運輸','m',numeric([500,1000,2000,3000],False),2.5,2)
    def inside_bands(bounds):
        # "Inside the section" is a distinct category, never inferred from zero distance.
        result=[band('優',values=['區段內有'])]
        edges=[0,*bounds,None]
        for i in range(4):
            result.append(band(LABELS[i+1],edges[i],edges[i+1]))
        return result
    region('bus','站牌之接近程度','交通運輸','m',inside_bands([200,400,700]),2,2,
           warning='原基準普通級距印為「200km以上未滿400m」，請確認單位後建立新版本。',blocked=True)
    region('interchange','接近交流道之程度','交通運輸','m',numeric([500,1500,3000,4500],False),2,2)
    region('development','道路規劃及闢建程度','交通運輸','',categorical(['已完全開發','大部分已完成','已規劃及闢建中','已進行規劃','尚未規劃']),2.5,2)
    region('drainage','排水之良否','自然條件','',categorical(['排水系統完善不曾淹水','有排水系統不易淹水','有排水系統偶有淹水但排水速度快','有排水系統偶有淹水','無排水系統易淹水']),2.5,3)
    region('terrain','地勢','自然條件','',categorical(['該區地勢平坦','該區大部分地勢平坦','該區一半地勢平坦','該區大部分地勢高亢或低窪','該區全部地勢高亢或低窪']),2.5,3)
    for key,name,bounds,step in [('market','接近市場之程度',[500,1000,1800],1.5),('park','接近公園廣場之程度',[500,1000,1800],1.5),('tourism','接近觀光遊憩設施之程度',[500,1000,1500],.75),('parking','停車場地之便利程度',[200,400,700],1)]:
        b=inside_bands(bounds); b[-1]['values']=['無']
        kw=dict(warning='原基準稍劣級距印為「1,000km以上未滿1,500m」，請確認單位後建立新版本。',blocked=True) if key=='tourism' else {}
        region(key,name,'公共建設','m',b,step,3,**kw)
    for key,name,group,step in [('utility','電業及氣體燃料設施','特殊設施',2),('funeral','殯葬設施','特殊設施',2),('waste','廢棄物處理設施','特殊設施',2),('pollution','環境污染','環境污染',1.5)]:
        region(key,name,group,'m',numeric([500,1000,2000,3000]),step,4,
               warning='本範例未明訂設施「無」的級距；無設施時交人工確認。')
    for key,name,step in [('department','百貨公司',2),('bank','金融機構',1),('entertainment','娛樂設施',1),('hotel','大型展示中心或觀光飯店',2)]:
        b=inside_bands([500,1000,1500]); b[-1]['values']=['無']
        region(key,name,'工商活動','m',b,step,5)
    region('customers','顧客通行量','工商活動','',categorical(['顧客通行量多','顧客通行量稍多','顧客通行量普通','顧客通行量較少','顧客通行量少']),3,5)
    region('shops','店舖毗連比例','工商活動','%',numeric([50,60,70,80]),3,5)
    return dict(id='jinshan-commercial-v1',name='金山區商業用地 · 範例基準',version='1.0',
                locality='新北市金山區',land_use='商業用地',source='評價基準明細表範例.pdf',
                direction='列：比準地；欄：比較標的；矩陣值為百分點',rules=r)
