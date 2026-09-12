from pathlib import Path
import pytest
from app.extraction import read_pdf,parse_case
from app.infrastructure.settings import Settings

ROOT=Path(__file__).resolve().parent.parent


def test_real_pdf_preserves_width_depth_and_all_individual_values():
    path=Settings().reference('sample')
    if path is None: pytest.skip('External reference PDF is not installed')
    c=parse_case(read_pdf(path.read_bytes()),'測試')
    f={f.id:f for f in c.factors}
    assert (f['width'].subject,f['width'].comparable)==('5','7')
    assert (f['depth'].subject,f['depth'].comparable)==('23','16')
    assert (f['restriction'].subject,f['restriction'].comparable)==('無','無')
    assert all(x.subject is not None and x.comparable is not None for x in c.factors[:19])
    assert all(x.entered_rate is not None for x in c.factors)
    assert not any(x.confirmed for x in c.factors)
    assert c.totals.individual==13 and c.totals.regional_detail==0
    assert c.totals.trial_price==212958
    assert c.subject_section==c.comparable_section=='P002-00'
    assert f['r_road_width'].subject=='18'


def test_unrecognized_or_scanned_document_stays_empty():
    c=parse_case([{'page':1,'text':''}],'掃描案件')
    assert all(f.subject is None and f.entered_rate is None for f in c.factors)
    assert c.extraction_warnings


def test_not_a_pdf_rejected():
    with pytest.raises(ValueError):read_pdf(b'not pdf')


def test_multiple_comparables_never_get_silently_merged():
    c=parse_case([{'page':1,'text':'表4  比較法調查估價表\n8寬度(M)  5  7  0.00%  9  1.00%'}],'多標的')
    assert all(f.entered_rate is None for f in c.factors)
    assert any('多筆' in w for w in c.extraction_warnings)


def test_ocr_spacing_and_reordered_rules_preserve_factor_identity():
    from app.domain.rules import default_rules
    rules = default_rules()
    rules['rules'].reverse()
    c = parse_case([{'page': 1, 'text': '表4比較法調查估價表\n8宽度(M)  5  7  0.00%'}], 'OCR', rules)
    width = next(f for f in c.factors if f.id == 'width')
    assert (width.subject, width.comparable, width.entered_rate) == ('5', '7', 0)
    assert not width.confirmed


def test_multiple_named_comparables_are_detected_even_when_rates_are_blank():
    c = parse_case([{'page': 1, 'text': '表4比較法調查估價表\n0基本資料  比準地甲  比較標的一  比較標的二  比較標的三'}], '多標的')
    assert any('多筆' in warning for warning in c.extraction_warnings)
    assert all(f.subject is None for f in c.factors)


def test_regional_values_and_rates_keep_their_respective_pdf_pages():
    from app.domain.rules import default_rules
    from app.application.drafts import parse_case as parse
    detail='影響地價區域因素分析明細表\n'+'\n'.join(f'因素{i} 1 優 1 優 0' for i in range(28))
    pages=[dict(page=1,text='表1 地價區段勘查表\n主要道路 寬度：18'),dict(page=2,text=detail),
           dict(page=3,text='表4 比較法調查估價表\n地價區段 P002-00 P002-00')]
    case=parse(pages,'跨頁合成案件',default_rules())
    sources=case.field_sources
    assert sources['factors.r_road_width.subject'].page==1
    assert sources['factors.r_road_width.comparable'].page==1
    assert sources['factors.r_road_width.subject_grade'].page==2
    assert sources['factors.r_road_width.entered_rate'].page==2
    assert sources['factors.r_road_width.entered_rate'].quote in detail
