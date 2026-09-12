from pathlib import Path
import pytest
from app.extraction import read_pdf,parse_case,ai_extract

ROOT=Path(__file__).resolve().parent.parent


def test_real_pdf_preserves_width_depth_and_all_individual_values():
    c=parse_case(read_pdf((ROOT/'查估書表範本.pdf').read_bytes()),'測試')
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


def test_ai_disabled_explicitly(monkeypatch):
    monkeypatch.delenv('OLLAMA_MODEL',raising=False)
    with pytest.raises(ValueError,match='OLLAMA_MODEL'):ai_extract([])


def test_multiple_comparables_never_get_silently_merged():
    c=parse_case([{'page':1,'text':'表4  比較法調查估價表\n8寬度(M)  5  7  0.00%  9  1.00%'}],'多標的')
    assert all(f.entered_rate is None for f in c.factors)
    assert any('多筆' in w for w in c.extraction_warnings)


def test_ai_accepts_only_known_fields_with_existing_quotes(monkeypatch):
    import io,json
    import app.extraction as extraction
    monkeypatch.setenv('OLLAMA_MODEL','test-model')
    factors=[
        {'id':'width','subject':'5','comparable':'7','entered_rate':0,'page':1,'quote':'寬度 5 7'},
        {'id':'depth','subject':'23','comparable':'16','entered_rate':1,'page':1,'quote':'不存在的引用'},
        {'id':'invented','subject':'0','comparable':'0','entered_rate':0,'page':1,'quote':'寬度 5 7'}]
    def response(request,timeout):
        body=json.loads(request.data)
        assert request.full_url=='http://127.0.0.1:11434/api/chat'
        assert body['stream'] is False and isinstance(body['format'],dict)
        return io.BytesIO(json.dumps({'message':{'content':json.dumps({'factors':factors})}}).encode())
    monkeypatch.setattr(extraction,'urlopen',response)
    result=ai_extract([{'page':1,'text':'寬度 5 7'}])
    assert len(result)==1 and result[0].id=='width'
    assert not result[0].confirmed
