import os
from pathlib import Path
import subprocess
import pytest
from app.application.ports import ExtractionUnavailable
from app.infrastructure.ocr_worker import layout_text
from app.infrastructure.paddle_pdf import PaddlePdfReader
from app.infrastructure.settings import Settings


def test_layout_groups_rows_and_keeps_columns_in_order():
    lines = [{'text': '7', 'bbox': [200, 11, 220, 30]}, {'text': '寬度', 'bbox': [0, 10, 40, 30]},
             {'text': '5', 'bbox': [100, 10, 120, 30]}, {'text': '下一列', 'bbox': [0, 60, 60, 80]}]
    text = layout_text(lines, 300)
    assert text.splitlines()[0].split() == ['寬度', '5', '7']
    assert text.splitlines()[1] == '下一列'


def test_invalid_pdf_rejected_before_spawning_worker(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs): pytest.fail('Worker must not run')
    monkeypatch.setattr(subprocess, 'run', unexpected)
    with pytest.raises(ValueError): PaddlePdfReader(Settings(data_dir=tmp_path)).read(b'not pdf')


def test_timeout_is_explicit_and_cloud_credentials_are_not_forwarded(tmp_path, monkeypatch):
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'test-only-not-a-real-key')
    def timeout(command, **kwargs):
        assert 'AWS_SECRET_ACCESS_KEY' not in kwargs['env']
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(ExtractionUnavailable, match='逾時'):
        PaddlePdfReader(Settings(data_dir=tmp_path)).read(b'%PDF-test')


@pytest.mark.integration
@pytest.mark.skipif(os.getenv('RUN_OCR_TESTS') != '1', reason='Set RUN_OCR_TESTS=1 to run real CPU OCR')
@pytest.mark.parametrize('engine', ['paddleocr', 'rapidocr'])
def test_real_ocr_reads_scanned_pdf(tmp_path, engine):
    from pypdf import PdfReader
    path = Path(__file__).parent / 'fixtures' / 'synthetic-scanned.pdf'
    assert not PdfReader(path).pages[0].extract_text().strip()
    pages = PaddlePdfReader(Settings(data_dir=tmp_path, ocr_engine=engine)).read(path.read_bytes())
    assert len(pages) == 1 and pages[0]['method'] == engine
    assert '寬度' in pages[0]['text']
    assert '18' in pages[0]['text'] and '6' in pages[0]['text']
    assert all(len(line['bbox']) == 4 for line in pages[0]['lines'])
