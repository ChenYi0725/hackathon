"""Opt-in real PDF test for PaddleOCR-to-ruleset compilation."""

import os
from pathlib import Path

import pytest

from app.application.ruleset_extraction import RulesetExtractionService
from app.infrastructure.paddle_pdf import PaddlePdfReader
from app.infrastructure.ruleset_table import PaddleLayoutRulesetExtractor
from app.infrastructure.settings import Settings


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv('RUN_RULESET_OCR_TESTS') != '1',
    reason='Set RUN_RULESET_OCR_TESTS=1 to run real ruleset OCR',
)
def test_real_ruleset_pdf_compiles_to_confirmation_required_drafts(tmp_path):
    source_value = os.getenv('RULESET_PDF_PATH')
    locality = os.getenv('RULESET_LOCALITY')
    if not source_value or not locality:
        pytest.fail('RULESET_PDF_PATH and RULESET_LOCALITY are required')

    source = Path(source_value)
    if not source.is_file():
        pytest.fail(f'RULESET_PDF_PATH does not exist: {source}')

    service = RulesetExtractionService(
        PaddlePdfReader(Settings(data_dir=tmp_path)),
        PaddleLayoutRulesetExtractor(),
    )
    result = service.extract(
        source.read_bytes(),
        source_name=source.name,
        expected_locality=locality,
    )

    assert result.requires_confirmation is True
    assert result.rulesets
    assert all(ruleset.locality == locality for ruleset in result.rulesets)
    assert all(ruleset.factors for ruleset in result.rulesets)
    assert all(
        factor.rule.matrix is not None
        for ruleset in result.rulesets
        for factor in ruleset.factors
    )
    payload = result.to_dict()
    assert payload['requires_confirmation'] is True
    assert payload['rulesets']
