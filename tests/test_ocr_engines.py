"""Engine selection, cache isolation and persisted source compatibility."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.application.ports import ExtractionUnavailable
from app.infrastructure.ocr_backends import create_predictor
from app.infrastructure.paddle_pdf import LocalPdfReader
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.settings import Settings
from app.interfaces.http import create_app


def page(engine):
    return {"page": 1, "text": "表 4 比較法調查估價表\n8 寬度 5 7 -2%", "method": engine, "width": 300, "height": 200,
            "lines": [{"text": "寬度 5 7", "confidence": .97, "bbox": [10, 20, 150, 40]}]}


@pytest.mark.parametrize("engine", ["paddleocr", "rapidocr"])
def test_engine_loaded_from_environment(monkeypatch, engine):
    monkeypatch.setenv("OCR_ENGINE", engine)
    assert Settings().ocr_engine == engine


@pytest.mark.parametrize("options", [
    {"ocr_engine": "unknown"},
    {"ocr_engine": "rapidocr", "detection_model": "PP-OCRv4_mobile_det"},
    {"ocr_engine": "rapidocr", "recognition_model": "unknown"},
])
def test_invalid_engine_configuration_fails_at_startup(options):
    with pytest.raises(ValueError):
        Settings(**options)


def test_cache_isolates_engine_models_and_dpi_and_reuses_rollback(tmp_path, monkeypatch):
    repository = SQLiteReviewRepository(tmp_path)
    repository.initialize()
    calls = []

    def worker(command, **kwargs):
        options = json.loads(command[-1])
        calls.append(options)
        Path(command[-2]).write_text(json.dumps({"pages": [page(options["engine"])]}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", worker)
    for engine in ["paddleocr", "rapidocr", "paddleocr", "rapidocr"]:
        reader = LocalPdfReader(Settings(data_dir=tmp_path, ocr_engine=engine), repository)
        assert reader.read(b"%PDF-same-file") == [page(engine)]
    assert len(calls) == 2
    for override in [{"recognition_model": "PP-OCRv5_mobile_rec"}, {"ocr_dpi": 200}]:
        LocalPdfReader(Settings(data_dir=tmp_path, ocr_engine="rapidocr", **override), repository).read(b"%PDF-same-file")
    assert len(calls) == 4


@pytest.mark.parametrize("engine", ["paddleocr", "rapidocr"])
def test_engine_failure_is_not_cached_or_silently_retried(tmp_path, monkeypatch, engine):
    repository = SQLiteReviewRepository(tmp_path)
    repository.initialize()
    calls = []

    def worker(command, **kwargs):
        calls.append(json.loads(command[-1])["engine"])
        Path(command[-2]).write_text(json.dumps({"error": "ocr_failed"}))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", worker)
    reader = LocalPdfReader(Settings(data_dir=tmp_path, ocr_engine=engine), repository)
    for _ in range(2):
        with pytest.raises(ExtractionUnavailable, match="辨識失敗"):
            reader.read(b"%PDF-test")
    assert calls == [engine, engine]


def test_rapid_polygon_conversion_and_explicit_v5_cpu_settings(monkeypatch):
    from enum import Enum
    np = pytest.importorskip("numpy")

    class ModelType(Enum):
        MOBILE = "mobile"
        SERVER = "server"

    class OCRVersion(Enum):
        PPOCRV5 = "PP-OCRv5"

    captured = {}

    def factory(*, params):
        captured.update(params)
        return lambda image: SimpleNamespace(
            txts=["-12.50%"], scores=[.98],
            boxes=np.array([[[15, 22], [92, 20], [94, 40], [12, 42]]]),
        )

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(
        RapidOCR=factory, ModelType=ModelType, OCRVersion=OCRVersion))
    predict = create_predictor({"engine": "rapidocr", "cpu_threads": 2,
                               "detection_model": "PP-OCRv5_mobile_det",
                               "recognition_model": "PP-OCRv5_server_rec"})
    assert list(predict(None)) == [("-12.50%", .98, [12, 20, 94, 42])]
    assert captured["Det.ocr_version"] == captured["Rec.ocr_version"] == OCRVersion.PPOCRV5
    assert captured["Det.model_type"] == ModelType.MOBILE
    assert captured["Rec.model_type"] == ModelType.SERVER
    assert captured["EngineConfig.onnxruntime.use_cuda"] is False
    assert captured["Global.use_cls"] is False


def test_switch_engine_preserves_existing_cases_documents_and_audit(tmp_path):
    class Pdf:
        def __init__(self, engine): self.engine = engine
        def read(self, data): return [page(self.engine)]

    old_app = create_app(Settings(data_dir=tmp_path, ocr_engine="paddleocr"), pdf=Pdf("paddleocr"))
    with TestClient(old_app) as client:
        original = client.post("/api/documents?name=original.pdf", content=b"%PDF-test").json()["case"]
        document = client.get("/api/documents/" + original["document_id"]).json()
        history = old_app.state.service.repository.audit(original["id"])

    for engine in ["rapidocr", "paddleocr"]:
        app = create_app(Settings(data_dir=tmp_path, ocr_engine=engine), pdf=Pdf(engine))
        with TestClient(app) as client:
            assert client.get("/api/health").json()["ocr_provider"] == engine
            assert client.get("/api/cases/" + original["id"]).json()["case"] == original
            assert client.get("/api/documents/" + original["document_id"]).json() == document
            assert app.state.service.repository.audit(original["id"]) == history
            new = client.post("/api/documents?name=new.pdf", content=b"%PDF-test").json()["case"]
            pages = client.get("/api/documents/" + new["document_id"]).json()["pages"]
            assert pages == [page(engine)]
            width = next(factor for factor in new["factors"] if factor["id"] == "width")
            assert width["evidence"]["method"] == engine + "-layout"
            assert not any(factor["confirmed"] for factor in new["factors"])
            assert client.get("/api/documents/" + new["document_id"] + "/file").content == b"%PDF-test"


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_OCR_TESTS") != "1", reason="Set RUN_OCR_TESTS=1 for real OCR")
@pytest.mark.parametrize("engine", ["paddleocr", "rapidocr"])
def test_synthetic_ruleset_keeps_matrix_signs_thresholds_and_confirmation(tmp_path, engine):
    from decimal import Decimal
    from app.bootstrap import build_ruleset_extraction_service
    from app.domain.factor_evaluation import evaluate_factor

    source = Path(__file__).parent / "fixtures/ocr_benchmark/ruleset.pdf"
    result = build_ruleset_extraction_service(Settings(data_dir=tmp_path, ocr_engine=engine)).extract(
        source.read_bytes(), source_name=source.name, expected_locality="測試市甲區")
    assert result.requires_confirmation is True
    assert len(result.rulesets) == 1
    factors = result.rulesets[0].factors
    assert len(factors) == 1
    rule = factors[0].rule
    assert rule.matrix == ((0, 5, 10), (-5, 0, 5), (-10, -5, 0))
    for value, grade in [("80", 1), ("79.999", 2), ("60", 2), ("59.999", 3)]:
        assert evaluate_factor(Decimal(value), rule).index == grade
