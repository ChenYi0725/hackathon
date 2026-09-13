"""Real digital PDFs exercise native extraction without downloading OCR models."""
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

pytest.importorskip('pypdfium2')

from app.infrastructure import ocr_backends
from app.infrastructure.ocr_worker import recognize
from app.infrastructure.pdf_text_layout import read_text_lines

OPTIONS = dict(engine='paddleocr', dpi=144, cpu_threads=2,
               detection_model='PP-OCRv5_mobile_det', recognition_model='PP-OCRv5_server_rec')


def digital_pdf(path, *, hidden=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data((f'BT /F1 12 Tf {3 if hidden else 0} Tr 50 700 Td '
                     '(Synthetic appraisal document with numbers 18 6 -2.50) Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)
    return path


def test_digital_page_uses_native_geometry_without_initializing_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_backends, 'create_predictor', lambda _: pytest.fail('Digital PDF must not initialize OCR'))
    pages = recognize(digital_pdf(tmp_path / 'text.pdf'), OPTIONS)
    assert len(pages) == 1 and pages[0]['method'] == 'pdf-text'
    assert '18 6 -2.50' in pages[0]['text']
    assert (pages[0]['width'], pages[0]['height']) == (1200, 1600)
    box = pages[0]['lines'][0]['bbox']
    assert 95 <= box[0] <= 105 and 170 <= box[1] <= 205
    assert box[2] > box[0] and box[3] > box[1]


def test_mixed_pdf_only_initializes_ocr_for_image_page(tmp_path, monkeypatch):
    pytest.importorskip('numpy')
    pytest.importorskip('PIL')
    path = digital_pdf(tmp_path / 'text.pdf')
    writer = PdfWriter()
    writer.append(path)
    writer.append(Path(__file__).parent / 'fixtures/synthetic-scanned.pdf')
    writer.append(path)
    mixed = tmp_path / 'mixed.pdf'
    writer.write(mixed)
    calls = []

    def predictor(options):
        calls.append('initialized')
        def predict(image):
            calls.append('page')
            yield 'Scanned evidence 18 6', .98, [10, 10, 200, 40]
        return predict

    monkeypatch.setattr(ocr_backends, 'create_predictor', predictor)
    pages = recognize(mixed, OPTIONS)
    assert [p['method'] for p in pages] == ['pdf-text', 'paddleocr', 'pdf-text']
    assert [p['page'] for p in pages] == [1, 2, 3]
    assert calls == ['initialized', 'page']


@pytest.mark.parametrize('kind', ['hidden', 'rotated', 'scanned', 'disabled'])
def test_unusable_text_or_disabled_fast_path_requires_ocr(tmp_path, monkeypatch, kind):
    path = digital_pdf(tmp_path / 'text.pdf', hidden=kind == 'hidden')
    if kind == 'rotated':
        writer = PdfWriter()
        writer.add_page(PdfReader(path).pages[0].rotate(90))
        path = tmp_path / 'rotated.pdf'
        writer.write(path)
    elif kind == 'scanned':
        path = Path(__file__).parent / 'fixtures/synthetic-scanned.pdf'
    class NeedsOCR(Exception):
        pass
    def predictor(_):
        raise NeedsOCR
    monkeypatch.setattr(ocr_backends, 'create_predictor', predictor)
    with pytest.raises(NeedsOCR):
        recognize(path, dict(OPTIONS, text_layer=kind != 'disabled'))


def test_translated_form_text_coordinates_include_parent_transform(tmp_path):
    import pypdfium2 as pdfium
    from pypdf.generic import ArrayObject, NumberObject
    path = digital_pdf(tmp_path / 'base.pdf')
    writer = PdfWriter(clone_from=path)
    page = writer.pages[0]
    form = DecodedStreamObject()
    form.set_data(b'BT /F1 12 Tf 0 0 Td (Synthetic translated form text with value -50) Tj ET')
    form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                 NameObject('/BBox'): ArrayObject([NumberObject(v) for v in [-10, -10, 500, 20]]),
                 NameObject('/Matrix'): ArrayObject([NumberObject(v) for v in [1, 0, 0, 1, 50, 700]]),
                 NameObject('/Resources'): page['/Resources']})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({
        NameObject('/Fm'): writer._add_object(form)})})
    content = DecodedStreamObject()
    content.set_data(b'/Fm Do')
    page[NameObject('/Contents')] = writer._add_object(content)
    path = tmp_path / 'form.pdf'
    writer.write(path)
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        lines = read_text_lines(page, 144)
        page.close()
    assert lines is not None and '-50' in lines[0]['text']
    assert 95 <= lines[0]['bbox'][0] <= 105
    assert 170 <= lines[0]['bbox'][1] <= 205
