"""Import OCR ruleset drafts and explicitly confirm them for case review.

The OCR compiler produces locality-neutral ``StructuredRuleset`` objects.  The
current review aggregate still consumes its legacy JSON rule language, so this
module owns the compatibility projection.  It never invents thresholds,
labels, factors, or matrix values: every such value comes from the structured
draft.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
import re

from app.application.ports import PdfReader, ReviewRepository, RulesetExtractor
from app.application.ruleset_contracts import RulesetExtractionResult
from app.domain.factor_rules import GradingMethod, NumericRangeRule
from app.domain.rule_validation import validate_ruleset


SOURCE_TARGET_ROW = 'target_row_benchmark_column'
SOURCE_BENCHMARK_ROW = 'benchmark_row_target_column'
MATRIX_DIRECTIONS = {SOURCE_TARGET_ROW, SOURCE_BENCHMARK_ROW}


class RulesetImportService:
    """Orchestrate OCR draft creation, confirmation, and source indexing."""

    def __init__(
        self,
        repository: ReviewRepository,
        pdf: PdfReader,
        extractor: RulesetExtractor,
    ) -> None:
        self.repository = repository
        self.pdf = pdf
        self.extractor = extractor

    def extract(
        self,
        data: bytes,
        source_name: str,
        expected_locality: str,
    ) -> dict:
        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError('評價基準明細表檔名不可為空白。')
        if not isinstance(expected_locality, str) or not expected_locality.strip():
            raise ValueError('必須提供要核對的地區。')
        pages = self.pdf.read(data)
        result = self.extractor.extract(
            pages,
            source_name=source_name,
            expected_locality=expected_locality,
        )
        document_id = self.repository.save_document(data, source_name[:200], pages)
        payload = result.to_dict()
        payload.update(
            document_id=document_id,
            source_name=source_name[:200],
            candidates=build_review_candidates(result),
            message=(
                '已完成 OCR 與 structured ruleset 草稿；請核對原文、適用期間及矩陣方向後再建立基準。'
            ),
        )
        return payload

    def confirm(
        self,
        *,
        document_id: str,
        candidate: dict,
        valid_from: str,
        valid_to: str,
        matrix_direction: str,
        confirmed: bool,
    ) -> dict:
        if confirmed is not True:
            raise ValueError('OCR ruleset 必須經人工確認後才能套用。')
        try:
            start = date.fromisoformat(valid_from)
            end = date.fromisoformat(valid_to)
        except (TypeError, ValueError):
            raise ValueError('適用期間必須使用 YYYY-MM-DD。') from None
        if start > end:
            raise ValueError('適用起日不可晚於迄日。')
        if matrix_direction not in MATRIX_DIRECTIONS:
            raise ValueError('請明確確認來源矩陣的列與欄方向。')
        if not isinstance(candidate, dict) or candidate.get('import_kind') != 'ocr-structured':
            raise ValueError('只能確認由 OCR structured ruleset 產生的候選基準。')

        document = self.repository.get_document(document_id)
        normalized = normalize_candidate(candidate, matrix_direction)
        normalized['source'] = document['name']
        normalized['source_document_id'] = document_id
        normalized['requires_confirmation'] = False
        normalized = validate_ruleset(normalized)
        saved = self.repository.save_confirmed_ruleset(
            normalized,
            document_id,
            start,
            end,
        )
        return {
            'ruleset': saved,
            'evidence_document': {
                'document_id': document_id,
                'name': document['name'],
                'ruleset_id': saved['id'],
                'ruleset_version': saved['version'],
                'valid_from': start.isoformat(),
                'valid_to': end.isoformat(),
            },
            'message': '基準已建立，原始 PDF 已加入此版本的本機檢索來源。',
        }


def build_review_candidates(result: RulesetExtractionResult) -> list[dict]:
    """Project structured drafts into the review engine's data-only format."""

    grouped: dict[tuple[str, str, str], list] = {}
    for ruleset in result.rulesets:
        key = (ruleset.locality, ruleset.land_use, ruleset.source_name)
        grouped.setdefault(key, []).append(ruleset)

    candidates = []
    for (locality, land_use, source_name), rulesets in grouped.items():
        structured = [ruleset.to_dict() for ruleset in rulesets]
        content = json.dumps(structured, ensure_ascii=False, sort_keys=True)
        version = 'ocr-' + hashlib.sha256(content.encode()).hexdigest()[:16]
        rules = []
        for ruleset in rulesets:
            for factor in ruleset.factors:
                rules.append(_legacy_factor(factor, ruleset.scope.value))
        candidates.append(
            {
                'name': f'{locality}{land_use} · OCR 評價基準',
                'version': version,
                'locality': locality,
                'land_use': land_use,
                'source': source_name,
                'direction': '待確認來源矩陣方向',
                'rules': rules,
                'import_kind': 'ocr-structured',
                'requires_confirmation': True,
                'structured_rulesets': structured,
                'extraction_warnings': list(result.warnings),
            }
        )
    return candidates


def normalize_candidate(candidate: dict, matrix_direction: str) -> dict:
    """Normalize a confirmed source matrix to subject-row/comparable-column."""

    normalized = deepcopy(candidate)
    normalized.pop('id', None)
    if matrix_direction == SOURCE_TARGET_ROW:
        for rule in normalized.get('rules', []):
            matrix = rule.get('matrix')
            if isinstance(matrix, list):
                rule['matrix'] = [list(column) for column in zip(*matrix)]
    normalized['source_matrix_direction'] = matrix_direction
    normalized['direction'] = '列：比準地；欄：比較標的；矩陣值為百分點'
    return normalized


def _legacy_factor(factor, scope: str) -> dict:
    rule = factor.rule
    criteria = {label: text for label, text in factor.criteria}
    bands = [
        {
            'label': grade.label,
            'values': [],
            'low': 0,
            'high': None,
        }
        for grade in rule.grades
    ]
    blocked = False
    warnings: list[str] = []

    if rule.grading_method in {GradingMethod.NUMERIC_RANGE, GradingMethod.COUNT}:
        assert rule.ranges is not None
        blocked = _put_ranges(bands, rule.ranges)
        if blocked:
            warnings.append('此級距含目前相容層無法表示的開閉邊界，須人工核對。')
    elif rule.grading_method is GradingMethod.CATEGORICAL:
        assert rule.category_mapping is not None
        for value, grade_index in rule.category_mapping.items():
            bands[grade_index - 1]['values'].append(value)
    elif rule.grading_method is GradingMethod.BOOLEAN:
        for grade_index in (rule.true_grade_index, rule.false_grade_index):
            if grade_index is not None:
                text = criteria.get(rule.grades[grade_index - 1].label)
                if text:
                    bands[grade_index - 1]['values'].append(text)
    elif rule.grading_method is GradingMethod.FACILITY_DISTANCE:
        assert rule.facility_rule is not None
        blocked = _put_ranges(bands, rule.facility_rule.ranges)
        _put_facility_values(bands, factor.criteria)
        if blocked:
            warnings.append('設施距離級距含目前相容層無法表示的開閉邊界，須人工核對。')
    else:
        blocked = True
        warnings.append('來源規則需要人工決定等級，不會自動推測。')
        for grade in rule.grades:
            text = criteria.get(grade.label)
            bands[grade.index - 1]['values'] = list(
                dict.fromkeys(value for value in (grade.label, text) if value)
            )

    unit = _unit_for(factor.criteria, rule.grading_method)
    if unit:
        for band in bands:
            ranges = band.pop('ranges', None)
            if ranges:
                band['ranges'] = ranges
                band['low'], band['high'] = ranges[0]
    else:
        for grade, band in zip(rule.grades, bands):
            if not band['values']:
                text = criteria.get(grade.label)
                band['values'] = [text or grade.label]

    return {
        'id': f'{scope}-{rule.id}',
        'source_factor_id': rule.id,
        'name': factor.name,
        'group': factor.group,
        'unit': unit,
        'scope': scope,
        'source_page': factor.source_page,
        'bands': bands,
        'matrix': [[format(value, 'f') for value in row] for row in rule.matrix or ()],
        'blocked': blocked,
        'warning': ' '.join(warnings),
        'allow_grade_only': scope == 'regional',
        'input_type': rule.input_type.value,
        'grading_method': rule.grading_method.value,
        'criteria': [
            {'label': label, 'text': text} for label, text in factor.criteria
        ],
    }


def _put_ranges(bands: list[dict], ranges: tuple[NumericRangeRule, ...]) -> bool:
    blocked = False
    for item in ranges:
        if (item.min_value is not None and not item.min_inclusive) or item.max_inclusive:
            blocked = True
        low = Decimal('0') if item.min_value is None else item.min_value
        high = item.max_value
        bands[item.grade_index - 1].setdefault('ranges', []).append(
            [format(low, 'f'), None if high is None else format(high, 'f')]
        )
    return blocked


def _put_facility_values(bands: list[dict], criteria) -> None:
    for grade_index, (_, text) in enumerate(criteria, start=1):
        values = [text]
        if '區段內' in text:
            values.append('區段內')
        if '不存在' in text or '或無' in text or text == '無':
            values.extend(('無', '不存在'))
        bands[grade_index - 1]['values'].extend(
            value for value in dict.fromkeys(values) if value
        )


def _unit_for(criteria, method: GradingMethod) -> str:
    if method is GradingMethod.COUNT:
        return '項'
    if method not in {GradingMethod.NUMERIC_RANGE, GradingMethod.FACILITY_DISTANCE}:
        return ''
    text = ''.join(body for _, body in criteria)
    if re.search(r'(?:m2|m²|㎡|平方公尺)', text, re.IGNORECASE):
        return '㎡'
    if '%' in text or '％' in text:
        return '%'
    if re.search(r'\d\s*(?:m|公尺)', text, re.IGNORECASE):
        return 'm'
    if '度' in text:
        return '度'
    return '數值'
