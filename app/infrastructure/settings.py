"""Deployment configuration. Credentials stay in the AWS SDK credential chain."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    form_template_dir: Path = field(default_factory=lambda: Path(os.getenv('FORM_TEMPLATE_DIR', ROOT / 'problem_files')))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('APP_DATA_DIR', ROOT / 'data')))
    reference_dir: Path = field(default_factory=lambda: Path(os.getenv('REFERENCE_DATA_DIR', ROOT.parent / 'aws')))
    region: str = field(default_factory=lambda: os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or 'us-west-2')
    model_id: str = field(default_factory=lambda: os.getenv('BEDROCK_MODEL_ID', 'qwen.qwen3-32b-v1:0'))
    # Empty means the ordinary SDK chain (environment, default profile or instance role).
    aws_profile: str | None = field(default_factory=lambda: os.getenv('AWS_PROFILE') or None)
    ai_enabled: bool = field(default_factory=lambda: os.getenv('BEDROCK_ENABLED', 'true').lower() == 'true')
    min_interval: float = field(default_factory=lambda: float(os.getenv('BEDROCK_MIN_INTERVAL', '1.1')))
    ocr_timeout: int = field(default_factory=lambda: int(os.getenv('OCR_TIMEOUT_SECONDS', '300')))
    ocr_dpi: int = field(default_factory=lambda: int(os.getenv('OCR_DPI', '180')))
    ocr_threads: int = field(default_factory=lambda: int(os.getenv('OCR_CPU_THREADS', '2')))
    detection_model: str = field(default_factory=lambda: os.getenv('OCR_DETECTION_MODEL', 'PP-OCRv5_mobile_det'))
    recognition_model: str = field(default_factory=lambda: os.getenv('OCR_RECOGNITION_MODEL', 'PP-OCRv5_server_rec'))

    def __post_init__(self):
        if self.region not in {'us-west-2', 'us-east-1'}:
            raise ValueError('競賽部署區域須為 us-west-2 或 us-east-1。')
        # Cross-region destinations need a separate policy review; this deployment is regional.
        if self.model_id.startswith(('us.', 'eu.', 'apac.', 'global.', 'arn:')):
            raise ValueError('本版使用區域內模型 ID；跨區推論 profile 尚未啟用。')
        if not 1.1 <= self.min_interval <= 60:
            raise ValueError('BEDROCK_MIN_INTERVAL 須介於 1.1 與 60 秒。')
        if not 72 <= self.ocr_dpi <= 300 or not 1 <= self.ocr_threads <= 8:
            raise ValueError('OCR_DPI 須為 72–300，OCR_CPU_THREADS 須為 1–8。')
        if not 10 <= self.ocr_timeout <= 1800:
            raise ValueError('OCR_TIMEOUT_SECONDS 須為 10–1800 秒。')

    def reference(self, kind: str) -> Path | None:
        paths = {
            'sample': ('範例/查估書表範本.pdf', '查估書表範本.pdf'),
            'rules': ('範例/評價基準明細表範例.pdf', '評價基準明細表範例.pdf'),
            'manual': ('其他參考資料/土地徵收補償市價查估作業手冊.pdf', '土地徵收補償市價查估作業手冊.pdf'),
            'brief': ('【命題文件】地政局-新北市政府AI黑客松競賽.pdf',),
        }
        if kind not in paths:
            raise KeyError(kind)
        for root in (self.reference_dir, ROOT):
            for name in paths[kind]:
                path = root / name
                if path.is_file():
                    return path
        return None
