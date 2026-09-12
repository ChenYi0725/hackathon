from decimal import Decimal

import pytest

from app.application.ruleset_contracts import RulesetExtractionResult
from app.application.ruleset_imports import (
    SOURCE_BENCHMARK_ROW,
    SOURCE_TARGET_ROW,
    RulesetImportService,
    build_review_candidates,
    normalize_candidate,
)
from app.domain.factor_rules import (
    FactorRule,
    GradeDefinition,
    NumericRangeRule,
)
from app.domain.engine import review
from app.domain.models import Case, Factor
from app.domain.rule_validation import validate_ruleset
from app.domain.ruleset_models import (
    RulesetScope,
    StructuredFactorRule,
    StructuredRuleset,
)


def extraction_result(locality='測試市甲區'):
    grades = (
        GradeDefinition(1, '第一級'),
        GradeDefinition(2, '第二級'),
        GradeDefinition(3, '第三級'),
    )
    factor = StructuredFactorRule(
        name='測試數值',
        group='測試群組',
        source_page=2,
        criteria=(
            ('第一級', '80%以上'),
            ('第二級', '60%以上未滿80%'),
            ('第三級', '未滿60%'),
        ),
        rule=FactorRule(
            id='opaque-factor',
            input_type='numeric',
            grading_method='numeric_range',
            grades=grades,
            ranges=(
                NumericRangeRule(1, min_value=Decimal('80')),
                NumericRangeRule(2, min_value=Decimal('60'), max_value=Decimal('80')),
                NumericRangeRule(3, max_value=Decimal('60')),
            ),
            matrix=(
                (Decimal('0'), Decimal('1.25'), Decimal('2.5')),
                (Decimal('-1.25'), Decimal('0'), Decimal('1.25')),
                (Decimal('-2.5'), Decimal('-1.25'), Decimal('0')),
            ),
        ),
    )
    ruleset = StructuredRuleset(
        id='source-regional',
        version='ocr-source',
        title=f'{locality}測試用地影響地價區域因素評價基準明細表',
        locality=locality,
        land_use='測試用地',
        scope=RulesetScope.REGIONAL,
        factors=(factor,),
        source_name='測試基準.pdf',
    )
    return RulesetExtractionResult((ruleset,), ())


def test_candidate_keeps_source_data_and_validates_for_review_engine():
    candidate = build_review_candidates(extraction_result())[0]
    with pytest.raises(ValueError, match='百分點矩陣'):
        validate_ruleset(candidate)
    validated = validate_ruleset(normalize_candidate(candidate, SOURCE_BENCHMARK_ROW))
    rule = validated['rules'][0]
    assert candidate['locality'] == '測試市甲區'
    assert rule['id'] == 'regional-opaque-factor'
    assert rule['bands'][0]['ranges'] == [['80', None]]
    assert rule['matrix'][0] == ['0', '1.25', '2.5']
    assert candidate['requires_confirmation'] is True
    assert candidate['structured_rulesets'][0]['factors'][0]['grading_method'] == 'numeric_range'


def test_confirmation_direction_transposes_only_when_source_rows_are_targets():
    candidate = build_review_candidates(extraction_result())[0]
    unchanged = normalize_candidate(candidate, SOURCE_BENCHMARK_ROW)
    transposed = normalize_candidate(candidate, SOURCE_TARGET_ROW)
    assert unchanged['rules'][0]['matrix'][0][1] == '1.25'
    assert transposed['rules'][0]['matrix'][0][1] == '-1.25'
    assert candidate['rules'][0]['matrix'][0][1] == '1.25'
    assert transposed['direction'].startswith('列：比準地')


def test_confirmed_source_grades_can_drive_matrix_when_raw_values_are_absent():
    ruleset = normalize_candidate(
        build_review_candidates(extraction_result())[0], SOURCE_BENCHMARK_ROW
    )
    ruleset['id'] = 'confirmed-rule'
    factor = Factor(
        id='regional-opaque-factor',
        subject_grade='第一級',
        comparable_grade='第三級',
        entered_rate=Decimal('2.5'),
        confirmed=True,
    )
    case = Case(
        title='等級輸入案件',
        subject_name='比準地',
        comparable_name='比較標的',
        locality='測試市甲區',
        land_use='測試用地',
        ruleset_id='confirmed-rule',
        factors=[factor],
    )
    result = review(case, ruleset)
    check = next(item for item in result['checks'] if item['id'] == factor.id)
    assert check['expected'] == 2.5
    assert check['status'] == 'pass'


class Pdf:
    def read(self, data):
        return [{'page': 1, 'text': '測試 OCR', 'lines': [], 'width': 1, 'height': 1}]


class Extractor:
    def extract(self, pages, *, source_name, expected_locality):
        assert expected_locality == '測試市甲區'
        return extraction_result(expected_locality)


class Repository:
    def __init__(self):
        self.documents = {}
        self.confirmed = None

    def save_document(self, data, name, pages):
        self.documents['doc-1'] = {'name': name, 'pages': pages}
        return 'doc-1'

    def get_document(self, document_id):
        return self.documents[document_id]

    def save_confirmed_ruleset(self, ruleset, document_id, valid_from, valid_to):
        self.confirmed = (ruleset, document_id, valid_from, valid_to)
        return dict(ruleset, id='saved-rule')


def test_import_service_saves_ocr_document_then_requires_explicit_confirmation():
    repository = Repository()
    service = RulesetImportService(repository, Pdf(), Extractor())
    draft = service.extract(b'%PDF-test', '測試基準.pdf', '測試市甲區')
    assert draft['document_id'] == 'doc-1'
    assert draft['requires_confirmation'] is True
    with pytest.raises(ValueError, match='人工確認'):
        service.confirm(
            document_id='doc-1',
            candidate=draft['candidates'][0],
            valid_from='2026-01-01',
            valid_to='2026-12-31',
            matrix_direction=SOURCE_BENCHMARK_ROW,
            confirmed=False,
        )
    result = service.confirm(
        document_id='doc-1',
        candidate=draft['candidates'][0],
        valid_from='2026-01-01',
        valid_to='2026-12-31',
        matrix_direction=SOURCE_BENCHMARK_ROW,
        confirmed=True,
    )
    assert result['ruleset']['id'] == 'saved-rule'
    assert result['evidence_document']['document_id'] == 'doc-1'
    assert repository.confirmed[0]['requires_confirmation'] is False
