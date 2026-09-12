"""Use case for OCR then deterministic ruleset-table compilation."""

from app.application.ports import PdfReader, RulesetExtractor
from app.application.ruleset_contracts import RulesetExtractionResult


class RulesetExtractionService:
    def __init__(self, pdf: PdfReader, extractor: RulesetExtractor):
        self.pdf = pdf
        self.extractor = extractor

    def extract(
        self,
        data: bytes,
        source_name: str,
        expected_locality: str,
    ) -> RulesetExtractionResult:
        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError('評價基準明細表檔名不可為空白。')
        if not isinstance(expected_locality, str) or not expected_locality.strip():
            raise ValueError('必須提供要核對的地區。')
        pages = self.pdf.read(data)
        return self.extractor.extract(
            pages,
            source_name=source_name,
            expected_locality=expected_locality,
        )
