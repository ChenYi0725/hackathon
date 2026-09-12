"""PaddleOCR PDF adapter. The OCR runtime runs in a bounded child process."""
import hashlib
import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
from app.application.ports import ExtractionUnavailable
from app.infrastructure.settings import ROOT


class PaddlePdfReader:
    def __init__(self, settings, repository=None):
        self.settings, self.repository = settings, repository

    def read(self, data):
        if not data.startswith(b'%PDF-'):
            raise ValueError('檔案不是有效的 PDF。')
        if len(data) > 20 * 1024 * 1024:
            raise ValueError('PDF 上限 20 MB。')
        options = {
            'device': self.settings.ocr_device,
            'dpi': self.settings.ocr_dpi, 'cpu_threads': self.settings.ocr_threads,
            'detection_model': self.settings.detection_model, 'recognition_model': self.settings.recognition_model,
        }
        key = 'ocr:' + hashlib.sha256(data + json.dumps(options, sort_keys=True).encode() + b'paddle-pdf-v1').hexdigest()
        if self.repository:
            cached = self.repository.cache_get(key)
            if cached is not None:
                return cached
        with TemporaryDirectory(prefix='landwise-ocr-') as tmp:
            source, output = Path(tmp) / 'source.pdf', Path(tmp) / 'result.json'
            source.write_bytes(data)
            # OCR only needs model downloads; do not forward cloud credentials to the worker.
            env = {k: v for k, v in os.environ.items() if not k.startswith(('AWS_', 'GH_', 'GITHUB_'))}
            try:
                completed = subprocess.run(
                    [sys.executable, '-m', 'app.infrastructure.ocr_worker', str(source), str(output), json.dumps(options)],
                    cwd=ROOT, env=env, capture_output=True, timeout=self.settings.ocr_timeout,
                )
            except subprocess.TimeoutExpired:
                raise ExtractionUnavailable('PaddleOCR 處理逾時，請拆分 PDF 或調整 OCR_TIMEOUT_SECONDS。') from None
            if not output.exists():
                raise ExtractionUnavailable('PaddleOCR 無法啟動。請確認所選 CPU／GPU 的 PaddlePaddle 套件及模型可下載。')
            result = json.loads(output.read_text())
            if completed.returncode or 'error' in result:
                code = result.get('error', '')
                if code == 'invalid_pdf':
                    raise ValueError('PDF 無法開啟、受到密碼保護，或頁面超出處理限制。')
                if code == 'gpu_unavailable':
                    raise ExtractionUnavailable('OCR 指定的 GPU 無法使用。請確認 NVIDIA GPU、驅動程式、paddlepaddle-gpu 與 OCR_DEVICE；未改用 CPU。')
                raise ExtractionUnavailable('PaddleOCR 辨識失敗。請確認所選 CPU／GPU 套件及模型檔案，或縮小文件範圍。')
        pages = result['pages']
        if self.repository:
            self.repository.cache_put(key, pages)
        return pages
