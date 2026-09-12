"""Device selection and failure checks do not require a CUDA runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.application.ports import ExtractionUnavailable
from app.infrastructure.ocr_worker import create_ocr, GpuUnavailable
from app.infrastructure.paddle_pdf import PaddlePdfReader
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.settings import Settings


@pytest.mark.parametrize('value', ['auto', 'gpu', 'gpu:-1', 'gpu:0,1', 'gpu:01', 'cuda:0', ''])
def test_device_configuration_rejects_implicit_or_multiple_devices(value):
    with pytest.raises(ValueError, match='OCR_DEVICE'):
        Settings(ocr_device=value)


def runtime(monkeypatch, *, compiled=True, count=1):
    selected, constructed = [], []
    paddle = SimpleNamespace(
        is_compiled_with_cuda=lambda: compiled,
        device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: count)),
        set_device=selected.append,
    )
    monkeypatch.setitem(sys.modules, 'paddle', paddle)
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=lambda **kw: constructed.append(kw)))
    return selected, constructed


def options(device):
    return dict(device=device, detection_model='det', recognition_model='rec', cpu_threads=2)


@pytest.mark.parametrize('device,compiled,count', [('gpu:0', False, 1), ('gpu:0', True, 0), ('gpu:1', True, 1)])
def test_gpu_requirement_fails_before_model_loading(monkeypatch, device, compiled, count):
    selected, constructed = runtime(monkeypatch, compiled=compiled, count=count)
    with pytest.raises(GpuUnavailable):
        create_ocr(options(device))
    assert not selected and not constructed


def test_gpu_selection_reaches_paddle_and_ocr(monkeypatch):
    selected, constructed = runtime(monkeypatch, count=2)
    create_ocr(options('gpu:1'))
    assert selected == ['gpu:1']
    assert constructed[0]['device'] == 'gpu:1'


def test_cpu_does_not_require_cuda(monkeypatch):
    selected, constructed = runtime(monkeypatch, compiled=False, count=0)
    create_ocr(options('cpu'))
    assert not selected and constructed[0]['device'] == 'cpu'


def test_health_reports_configured_device_without_initializing_cuda(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.interfaces.http import create_app
    monkeypatch.setenv('SEED_EXAMPLES', 'false')
    selected, constructed = runtime(monkeypatch, compiled=False, count=0)
    with TestClient(create_app(Settings(data_dir=tmp_path, ocr_device='gpu:0'))) as client:
        assert client.get('/api/health').json()['ocr_device'] == 'gpu:0'
    assert not selected and not constructed


def test_device_changes_do_not_reuse_cpu_cache_and_gpu_failure_is_not_cached(tmp_path, monkeypatch):
    repo = SQLiteReviewRepository(tmp_path)
    repo.initialize()
    calls = []

    def worker(command, **kwargs):
        device = json.loads(command[-1])['device']
        calls.append(device)
        result = {'pages': [{'page': 1, 'text': 'synthetic', 'device': 'cpu'}]} if device == 'cpu' else {'error': 'gpu_unavailable'}
        Path(command[-2]).write_text(json.dumps(result))
        return SimpleNamespace(returncode=0 if device == 'cpu' else 1)

    monkeypatch.setattr(subprocess, 'run', worker)
    cpu = PaddlePdfReader(Settings(data_dir=tmp_path, ocr_device='cpu'), repo)
    gpu = PaddlePdfReader(Settings(data_dir=tmp_path, ocr_device='gpu:0'), repo)
    assert cpu.read(b'%PDF-synthetic') == cpu.read(b'%PDF-synthetic')
    for _ in range(2):
        with pytest.raises(ExtractionUnavailable, match='未改用 CPU'):
            gpu.read(b'%PDF-synthetic')
    assert calls == ['cpu', 'gpu:0', 'gpu:0']


@pytest.mark.integration
@pytest.mark.skipif(os.getenv('RUN_GPU_OCR_TESTS') != '1', reason='Set RUN_GPU_OCR_TESTS=1 on an NVIDIA GPU host')
def test_real_gpu_reads_synthetic_scanned_pdf(tmp_path):
    device = os.getenv('OCR_DEVICE', 'gpu:0')
    assert device.startswith('gpu:'), 'GPU acceptance cannot run on CPU'
    data = (Path(__file__).parent / 'fixtures' / 'synthetic-scanned.pdf').read_bytes()
    pages = PaddlePdfReader(Settings(data_dir=tmp_path, ocr_device=device, ocr_timeout=900)).read(data)
    assert len(pages) == 1 and pages[0]['device'] == device
    assert '寬度' in pages[0]['text'] and '18' in pages[0]['text'] and '6' in pages[0]['text']
    assert pages[0]['lines'] and all(len(line['bbox']) == 4 for line in pages[0]['lines'])
