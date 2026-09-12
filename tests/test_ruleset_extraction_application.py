"""Application use case composes OCR and deterministic ruleset extraction."""

import pytest

from app.application.ruleset_contracts import RulesetExtractionResult
from app.application.ruleset_extraction import RulesetExtractionService


class Pdf:
    def __init__(self):
        self.calls = []

    def read(self, data):
        self.calls.append(data)
        return [{'page': 1, 'lines': [], 'width': 1, 'height': 1}]


class Extractor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def extract(self, pages, *, source_name, expected_locality):
        self.calls.append((pages, source_name, expected_locality))
        return self.result


def test_service_passes_paddle_pages_and_scope_to_extractor():
    sentinel = object()
    pdf = Pdf()
    extractor = Extractor(sentinel)
    service = RulesetExtractionService(pdf, extractor)
    result = service.extract(b'%PDF-synthetic', '基準.pdf', '某市某區')
    assert result is sentinel
    assert pdf.calls == [b'%PDF-synthetic']
    assert extractor.calls == [
        ([{'page': 1, 'lines': [], 'width': 1, 'height': 1}], '基準.pdf', '某市某區')
    ]


@pytest.mark.parametrize(
    ('source_name', 'locality'),
    [('', '某市某區'), ('基準.pdf', ''), (None, '某市某區'), ('基準.pdf', None)],
)
def test_service_requires_source_name_and_expected_locality(source_name, locality):
    with pytest.raises(ValueError):
        RulesetExtractionService(Pdf(), Extractor(None)).extract(
            b'%PDF-synthetic', source_name, locality
        )
