"""Compile PaddleOCR table-layout output into locality-neutral ruleset drafts.

This adapter understands the repeated appraisal-table structure (factor name,
grade matrix, and criterion notes).  It does not contain any district, factor,
threshold, label-count, or adjustment-rate constants.  Unsupported or
ambiguous criterion wording is preserved as a manual factor instead of being
guessed.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Iterable

from app.application.ruleset_contracts import RulesetExtractionResult
from app.domain.factor_rules import (
    DistancePreference,
    FactorRule,
    FacilityDistanceRule,
    GradeDefinition,
    NumericRangeRule,
    validate_adjustment_matrix,
)
from app.domain.ruleset_models import (
    RulesetScope,
    StructuredFactorRule,
    StructuredRuleset,
)

_TITLE_MARKER = '影響地價'
_TITLE_END = '因素評價基準明細表'
_NUMBER = re.compile(r'(?<![\d.])[-+]?\d+(?:\.\d+)?(?![\d.])')
_GRADE_PREFIX = re.compile(r'^([^:：]{1,12})[:：](.*)$')
_PAGE_NUMBER = re.compile(r'^\d+[-－]\d+$')
_UNIT = r'(?:m2|m²|㎡|平方公尺|m|公尺|%|％|度)?'
_BETWEEN = re.compile(
    rf'(\d+(?:\.\d+)?)\s*{_UNIT}\s*以上\s*未滿\s*'
    rf'(\d+(?:\.\d+)?)\s*{_UNIT}'
)
_AT_LEAST = re.compile(rf'(\d+(?:\.\d+)?)\s*{_UNIT}\s*以上')
_BELOW = re.compile(rf'未滿\s*(\d+(?:\.\d+)?)\s*{_UNIT}')
_AT_MOST = re.compile(rf'(\d+(?:\.\d+)?)\s*{_UNIT}\s*以下')
_COUNT_WORDS = {
    '零': 0,
    '無': 0,
    '一': 1,
    '二': 2,
    '兩': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
    '十': 10,
}
_OCR_CHARACTER_NORMALIZATION = str.maketrans({
    '满': '滿',
    '内': '內',
    '项': '項',
    '积': '積',
    '宽': '寬',
    '势': '勢',
    '划': '劃',
    '区': '區',
    '业': '業',
    '气': '氣',
    '设': '設',
    '细': '細',
    '计': '計',
    '来': '來',
    '统': '統',
    '学': '學',
    '场': '場',
    '广': '廣',
    '调': '調',
    '当': '當',
    '别': '別',
    '规': '規',
    '缓': '緩',
    '视': '視',
})


class RulesetTableExtractionError(ValueError):
    """The OCR layout cannot be converted without inventing source rules."""


@dataclass(frozen=True)
class _Line:
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def height(self) -> float:
        return self.y2 - self.y1


@dataclass(frozen=True)
class _MatrixRow:
    center_y: float
    numbers: tuple[Decimal, ...]
    source_lines: tuple[_Line, ...]


@dataclass(frozen=True)
class _MatrixBlock:
    rows: tuple[_MatrixRow, ...]

    @property
    def first_y(self) -> float:
        return self.rows[0].center_y

    @property
    def last_y(self) -> float:
        return self.rows[-1].center_y

    @property
    def center_y(self) -> float:
        return (self.first_y + self.last_y) / 2

    @property
    def matrix(self) -> tuple[tuple[Decimal, ...], ...]:
        return tuple(row.numbers for row in self.rows)


class PaddleLayoutRulesetExtractor:
    """Parse shared OCR page/line dictionaries; retain the legacy class name."""

    def extract(
        self,
        pages: list[dict],
        *,
        source_name: str,
        expected_locality: str,
    ) -> RulesetExtractionResult:
        if not isinstance(pages, list) or not pages:
            raise RulesetTableExtractionError('OCR 頁面不可為空。')
        if not isinstance(source_name, str) or not source_name.strip():
            raise RulesetTableExtractionError('來源名稱不可為空白。')
        locality = _compact(expected_locality)
        if not locality:
            raise RulesetTableExtractionError('必須提供要核對的地區。')

        grouped: dict[tuple[str, str, RulesetScope], list[tuple[int, dict, list[_Line]]]] = {}
        warnings: list[str] = []
        for fallback_page, page in enumerate(pages, start=1):
            page_number, width, height, lines = self._read_page(page, fallback_page)
            title = self._find_title(lines)
            if title is None:
                warnings.append(f'第 {page_number} 頁沒有評價基準明細表標題，已略過。')
                continue
            parsed_locality, land_use, scope = self._parse_title(title, locality)
            key = (title, land_use, scope)
            grouped.setdefault(key, []).append(
                (page_number, {'width': width, 'height': height}, lines)
            )
            if parsed_locality != locality:
                raise RulesetTableExtractionError(
                    f'第 {page_number} 頁標題地區與輸入地區不一致。'
                )
        if not grouped:
            raise RulesetTableExtractionError('文件中找不到指定地區的評價基準明細表。')

        rulesets: list[StructuredRuleset] = []
        for (title, land_use, scope), source_pages in grouped.items():
            factors: list[StructuredFactorRule] = []
            used_ids: set[str] = set()
            for page_number, geometry, lines in source_pages:
                page_factors, page_warnings = self._extract_page_factors(
                    page_number,
                    geometry['width'],
                    geometry['height'],
                    lines,
                    scope,
                    used_ids,
                )
                factors.extend(page_factors)
                warnings.extend(page_warnings)
            if not factors:
                raise RulesetTableExtractionError(
                    f'「{title}」沒有辨識出完整的修正率矩陣。'
                )
            rulesets.append(
                self._build_ruleset(
                    title=title,
                    locality=locality,
                    land_use=land_use,
                    scope=scope,
                    factors=tuple(factors),
                    source_name=source_name,
                )
            )
        return RulesetExtractionResult(
            rulesets=tuple(rulesets),
            warnings=tuple(warnings),
            requires_confirmation=True,
        )

    def _read_page(
        self, page: dict, fallback_page: int
    ) -> tuple[int, float, float, list[_Line]]:
        if not isinstance(page, dict):
            raise RulesetTableExtractionError('OCR 頁面格式錯誤。')
        page_number = page.get('page', fallback_page)
        width, height = page.get('width'), page.get('height')
        raw_lines = page.get('lines')
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number < 1
        ):
            raise RulesetTableExtractionError('OCR 頁碼格式錯誤。')
        if not _positive_number(width) or not _positive_number(height):
            raise RulesetTableExtractionError(f'第 {page_number} 頁缺少有效頁面尺寸。')
        if not isinstance(raw_lines, list) or not raw_lines:
            raise RulesetTableExtractionError(
                f'第 {page_number} 頁缺少 OCR line boxes，不能只用純文字解析矩陣。'
            )
        lines = [self._read_line(item, page_number) for item in raw_lines]
        return page_number, float(width), float(height), lines

    def _read_line(self, item: dict, page_number: int) -> _Line:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise RulesetTableExtractionError(f'第 {page_number} 頁 OCR line 格式錯誤。')
        bbox = item.get('bbox')
        if (
            not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(not _finite_number(value) for value in bbox)
        ):
            raise RulesetTableExtractionError(f'第 {page_number} 頁 OCR bbox 格式錯誤。')
        x1, y1, x2, y2 = (float(value) for value in bbox)
        if x2 <= x1 or y2 <= y1:
            raise RulesetTableExtractionError(f'第 {page_number} 頁 OCR bbox 範圍錯誤。')
        confidence = item.get('confidence', 1)
        if not _finite_number(confidence) or not 0 <= float(confidence) <= 1:
            raise RulesetTableExtractionError(f'第 {page_number} 頁 OCR confidence 格式錯誤。')
        return _Line(item['text'].strip(), x1, y1, x2, y2, float(confidence))

    def _find_title(self, lines: list[_Line]) -> str | None:
        candidates = [
            _compact(line.text)
            for line in lines
            if _TITLE_MARKER in _compact(line.text) and _TITLE_END in _compact(line.text)
        ]
        return max(candidates, key=len) if candidates else None

    def _parse_title(
        self, title: str, expected_locality: str
    ) -> tuple[str, str, RulesetScope]:
        if not title.startswith(expected_locality):
            raise RulesetTableExtractionError(
                f'文件標題「{title}」不屬於輸入地區「{expected_locality}」。'
            )
        suffix = title[len(expected_locality):]
        match = re.fullmatch(
            r'(.+?用地)影響地價(區域|個別)因素評價基準明細表', suffix
        )
        if match is None:
            raise RulesetTableExtractionError(f'無法解析評價基準明細表標題：{title}')
        scope = (
            RulesetScope.REGIONAL
            if match.group(2) == '區域'
            else RulesetScope.INDIVIDUAL
        )
        return expected_locality, match.group(1), scope

    def _extract_page_factors(
        self,
        page_number: int,
        width: float,
        height: float,
        lines: list[_Line],
        scope: RulesetScope,
        used_ids: set[str],
    ) -> tuple[list[StructuredFactorRule], list[str]]:
        warnings: list[str] = []
        criterion_labels = [
            line for line in lines if _GRADE_PREFIX.match(_compact(line.text))
        ]
        if criterion_labels:
            # Grade-prefixed note rows sit immediately inside the note column;
            # unlike the centred column heading, their X position approximates
            # the actual table divider across differently scaled scans.
            note_start = min(line.x1 for line in criterion_labels)
        else:
            note_start = width * 0.64
            warnings.append(
                f'第 {page_number} 頁未辨識出備註等級標籤，使用版面比例切分並要求人工確認。'
            )
        blocks = self._matrix_blocks(lines, width, height, width * 0.68)
        if not blocks:
            return [], warnings
        intro_starts = self._intro_starts(lines, blocks, note_start, width)

        factors: list[StructuredFactorRule] = []
        for index, block in enumerate(blocks):
            fallback_top = (
                height * 0.06
                if index == 0
                else (blocks[index - 1].center_y + block.center_y) / 2
            )
            fallback_bottom = (
                height * 0.96
                if index == len(blocks) - 1
                else (block.center_y + blocks[index + 1].center_y) / 2
            )
            top = intro_starts[index] if intro_starts[index] is not None else fallback_top
            next_intro = intro_starts[index + 1] if index + 1 < len(blocks) else None
            bottom = next_intro if next_intro is not None else fallback_bottom
            name = self._factor_name(lines, width, top, bottom)
            if not name:
                raise RulesetTableExtractionError(
                    f'第 {page_number} 頁第 {index + 1} 個矩陣找不到細項名稱。'
                )
            local_labels = [
                line
                for line in lines
                if top <= line.center_y < bottom
                and _GRADE_PREFIX.match(_compact(line.text))
            ]
            local_note_start = min(
                (line.x1 for line in local_labels), default=note_start
            )
            criteria = self._criteria(lines, local_note_start, width, top, bottom)
            labels = tuple(label for label, _ in criteria)
            if len(labels) != len(block.rows):
                row_labels = self._row_labels(lines, block, width)
                if len(row_labels) != len(block.rows):
                    raise RulesetTableExtractionError(
                        f'第 {page_number} 頁「{name}」的等級標籤與矩陣尺寸不一致。'
                    )
                existing = {label: text for label, text in criteria}
                labels = row_labels
                criteria = tuple((label, existing.get(label, '')) for label in labels)
                warnings.append(
                    f'第 {page_number} 頁「{name}」的備註標籤不完整，已保留為待確認來源文字。'
                )
            grades = tuple(
                GradeDefinition(position, label)
                for position, label in enumerate(labels, start=1)
            )
            factor_id = f'{scope.value}:{name}'
            if factor_id in used_ids:
                suffix = 2
                while f'{factor_id}#{suffix}' in used_ids:
                    suffix += 1
                factor_id = f'{factor_id}#{suffix}'
                warnings.append(
                    f'第 {page_number} 頁「{name}」名稱重複，因素 ID 已加入序號並需人工確認。'
                )
            used_ids.add(factor_id)
            rule, compile_warnings = self._compile_rule(
                factor_id, name, grades, criteria, block.matrix
            )
            warnings.extend(
                f'第 {page_number} 頁「{name}」：{warning}'
                for warning in compile_warnings
            )
            factors.append(
                StructuredFactorRule(
                    name=name,
                    source_page=page_number,
                    criteria=criteria,
                    rule=rule,
                )
            )
        return factors, warnings

    def _intro_starts(
        self,
        lines: list[_Line],
        blocks: tuple[_MatrixBlock, ...],
        note_start: float,
        width: float,
    ) -> tuple[float | None, ...]:
        introductions = sorted(
            (
                line.center_y
                for line in lines
                if line.x1 >= note_start - width * 0.04
                and _compact(line.text).startswith('以')
                and any(
                    marker in _compact(line.text)
                    for marker in ('衡量', '制定', '判定', '計算')
                )
            )
        )
        result: list[float | None] = []
        previous: float | None = None
        for block in blocks:
            choices = [
                value
                for value in introductions
                if value <= block.first_y and (previous is None or value > previous)
            ]
            selected = max(choices) if choices else None
            result.append(selected)
            if selected is not None:
                previous = selected
        return tuple(result)

    def _matrix_blocks(
        self,
        lines: list[_Line],
        width: float,
        height: float,
        matrix_limit: float,
    ) -> tuple[_MatrixBlock, ...]:
        candidates = [
            line
            for line in lines
            if line.x1 >= width * 0.25 and line.center_x < matrix_limit
        ]
        visual_rows = _group_visual_rows(candidates, height)
        matrix_rows: list[_MatrixRow] = []
        for row in visual_rows:
            numbers: list[Decimal] = []
            source: list[_Line] = []
            center_y = sum(line.center_y for line in row) / len(row)
            note_start = min(
                (line.x1 for line in lines if _GRADE_PREFIX.match(_compact(line.text))
                 and abs(line.center_y - center_y) <= max(height * 0.008, line.height * 0.7)),
                default=matrix_limit,
            )
            for line in sorted(row, key=lambda item: item.x1):
                if line.center_x >= note_start:
                    continue
                values = _matrix_numbers(line.text)
                if values:
                    numbers.extend(values)
                    source.append(line)
            if len(numbers) >= 2:
                matrix_rows.append(
                    _MatrixRow(
                        center_y=sum(line.center_y for line in source) / len(source),
                        numbers=tuple(numbers),
                        source_lines=tuple(source),
                    )
                )

        blocks: list[_MatrixBlock] = []
        index = 0
        while index < len(matrix_rows):
            size = len(matrix_rows[index].numbers)
            possible = matrix_rows[index:index + size]
            if (
                2 <= size <= 20
                and len(possible) == size
                and all(len(row.numbers) == size for row in possible)
                and all(
                    0 < second.center_y - first.center_y < height * 0.04
                    for first, second in zip(possible, possible[1:])
                )
                and all(possible[position].numbers[position] == 0 for position in range(size))
            ):
                matrix = tuple(row.numbers for row in possible)
                validate_adjustment_matrix(matrix, size)
                blocks.append(_MatrixBlock(tuple(possible)))
                index += size
            else:
                index += 1
        return tuple(blocks)

    def _factor_name(
        self, lines: list[_Line], width: float, top: float, bottom: float
    ) -> str:
        header_positions = [
            line.x1
            for line in lines
            if _compact(line.text) in {'細', '項', '細項'}
        ]
        factor_column_x = (
            sum(header_positions) / len(header_positions)
            if header_positions
            else width * 0.21
        )
        fragments = [
            line
            for line in lines
            if abs(line.x1 - factor_column_x) <= width * 0.035
            and top <= line.center_y < bottom
            and _TITLE_MARKER not in line.text
            and not _structural_factor_fragment(_compact(line.text))
        ]
        columns: list[list[_Line]] = []
        tolerance = width * 0.008
        for line in sorted(fragments, key=lambda item: item.center_x, reverse=True):
            column = next(
                (
                    existing
                    for existing in columns
                    if abs(
                        sum(item.center_x for item in existing) / len(existing)
                        - line.center_x
                    )
                    <= tolerance
                ),
                None,
            )
            if column is None:
                columns.append([line])
            else:
                column.append(line)
        text = ''.join(
            _compact(line.text)
            for column in columns
            for line in sorted(column, key=lambda item: item.center_y)
        )
        return text.strip('：:`´＇\'"')

    def _criteria(
        self,
        lines: list[_Line],
        note_start: float,
        width: float,
        top: float,
        bottom: float,
    ) -> tuple[tuple[str, str], ...]:
        note_lines = [
            line
            for line in lines
            if line.x1 >= note_start - width * 0.015
            and top <= line.center_y < bottom
            and not _PAGE_NUMBER.fullmatch(_compact(line.text))
        ]
        rows = _group_visual_rows(note_lines, max(bottom - top, 1))
        anchors = sorted(
            (line for line in note_lines
             if line.x1 <= note_start + width * 0.04
             and _GRADE_PREFIX.match(_compact(line.text))),
            key=lambda line: line.center_y,
        )
        criteria = [[_GRADE_PREFIX.match(_compact(line.text)).group(1), ''] for line in anchors]
        for row in rows:
            text = ''.join(
                _compact(line.text) for line in sorted(row, key=lambda item: item.x1)
            )
            if not anchors or (text.startswith('以') and any(
                marker in text for marker in ('衡量', '制定', '判定', '計算')
            )):
                continue
            center_y = sum(line.center_y for line in row) / len(row)
            if len(anchors) > 1 and not (
                anchors[0].center_y - (anchors[1].center_y - anchors[0].center_y) / 2
                <= center_y <=
                anchors[-1].center_y + (anchors[-1].center_y - anchors[-2].center_y) / 2
            ):
                continue
            nearest = min(range(len(anchors)), key=lambda i: abs(anchors[i].center_y - center_y))
            match = _GRADE_PREFIX.match(text)
            criteria[nearest][1] += match.group(2) if match else text
        return tuple((label, _clean_criterion_body(text)) for label, text in criteria)

    def _row_labels(
        self, lines: list[_Line], block: _MatrixBlock, width: float
    ) -> tuple[str, ...]:
        labels: list[str] = []
        tolerance = width * 0.015
        for row in block.rows:
            numeric_start = min(line.x1 for line in row.source_lines)
            choices = [
                line
                for line in lines
                if width * 0.25 <= line.center_x < numeric_start
                and abs(line.center_y - row.center_y) <= tolerance
                and not _matrix_numbers(line.text)
            ]
            if not choices:
                return ()
            labels.append(_compact(min(choices, key=lambda item: item.x1).text).strip('：:'))
        return tuple(labels)

    def _compile_rule(
        self,
        factor_id: str,
        factor_name: str,
        grades: tuple[GradeDefinition, ...],
        criteria: tuple[tuple[str, str], ...],
        matrix: tuple[tuple[Decimal, ...], ...],
    ) -> tuple[FactorRule, tuple[str, ...]]:
        bodies = tuple(text for _, text in criteria)
        if any(not body for body in bodies):
            return self._manual_rule(factor_id, grades, matrix), (
                '分級條件不完整，未自動建立 grading rule。',
            )
        if any('詳備註' in body or '人工判定' in body for body in bodies):
            return self._manual_rule(factor_id, grades, matrix), (
                '來源明定需參照備註或人工判定，未自動推測 grade。',
            )

        facility = self._facility_rule(factor_id, grades, bodies, matrix)
        if facility is not None:
            return facility, ()
        if any('或無' in body for body in bodies):
            if any('區段內' in body for body in bodies):
                return self._manual_rule(factor_id, grades, matrix), (
                    '設施特殊狀態已辨識，但距離級距無法通過驗證，未猜測或修復來源數字。',
                )
            return self._manual_rule(factor_id, grades, matrix), (
                '規則含「無」但未同時定義區段內狀態，無法安全編譯成純數值規則。',
            )

        count_ranges = self._count_ranges(bodies)
        if count_ranges is not None:
            try:
                return FactorRule(
                    id=factor_id,
                    input_type='count',
                    grading_method='count',
                    grades=grades,
                    ranges=count_ranges,
                    matrix=matrix,
                ), ()
            except ValueError as error:
                return self._manual_rule(factor_id, grades, matrix), (
                    f'計數級距無法通過驗證（{error}），未猜測修正。',
                )

        numeric_ranges = self._numeric_ranges(bodies)
        if numeric_ranges is not None:
            try:
                return FactorRule(
                    id=factor_id,
                    input_type='numeric',
                    grading_method='numeric_range',
                    grades=grades,
                    ranges=numeric_ranges,
                    matrix=matrix,
                ), ()
            except ValueError as error:
                return self._manual_rule(factor_id, grades, matrix), (
                    f'數值級距無法通過驗證（{error}），未猜測修正。',
                )

        restatement_prefixes = [
            body[:-len(grade.label)]
            if body.endswith(grade.label) and len(body) > len(grade.label)
            else None
            for grade, body in zip(grades, bodies)
        ]
        if (
            all(prefix is not None for prefix in restatement_prefixes)
            and len(set(restatement_prefixes)) == 1
        ):
            return self._manual_rule(factor_id, grades, matrix), (
                '各列條件只重述等級標籤，必須由外部提供已決定 grade。',
            )
        if len(factor_name) >= 4 and all(
            body.startswith(factor_name)
            and 0 < len(body.removeprefix(factor_name)) <= 4
            for body in bodies
        ):
            return self._manual_rule(factor_id, grades, matrix), (
                '各列只有共同描述與短等級敘述，必須由外部提供已決定 grade。',
            )

        mapping: dict[str, int] = {}
        for grade_index, body in enumerate(bodies, start=1):
            values = [part for part in re.split(r'[、，,；;]', body) if part]
            if not values:
                return self._manual_rule(factor_id, grades, matrix), (
                    '分類條件無法辨識，未自動建立 mapping。',
                )
            for value in values:
                if value in mapping and mapping[value] != grade_index:
                    whole_values = {
                        whole: whole_index
                        for whole_index, whole in enumerate(bodies, start=1)
                    }
                    if len(whole_values) == len(bodies):
                        return FactorRule(
                            id=factor_id,
                            input_type='category',
                            grading_method='categorical',
                            grades=grades,
                            category_mapping=whole_values,
                            matrix=matrix,
                        ), (
                            f'分類片段「{value}」跨等級重複，改以各列完整原文作精確比對。',
                        )
                    return self._manual_rule(factor_id, grades, matrix), (
                        f'分類值「{value}」同時出現在不同等級，未猜測修正。',
                    )
                mapping[value] = grade_index
        return FactorRule(
            id=factor_id,
            input_type='category',
            grading_method='categorical',
            grades=grades,
            category_mapping=mapping,
            matrix=matrix,
        ), ()

    def _facility_rule(
        self,
        factor_id: str,
        grades: tuple[GradeDefinition, ...],
        bodies: tuple[str, ...],
        matrix: tuple[tuple[Decimal, ...], ...],
    ) -> FactorRule | None:
        in_section = [index for index, body in enumerate(bodies, start=1) if '區段內' in body]
        absent = [
            index
            for index, body in enumerate(bodies, start=1)
            if '或無' in body or body in {'無', '不存在'}
        ]
        if not in_section or not absent:
            return None
        ranges = self._numeric_ranges(bodies)
        if ranges is None:
            return None
        ordered_indexes = [
            item.grade_index
            for item in sorted(
                ranges,
                key=lambda item: (
                    item.min_value is not None,
                    item.min_value or Decimal('0'),
                ),
            )
        ]
        if ordered_indexes == sorted(ordered_indexes):
            preference = DistancePreference.CLOSER_IS_BETTER
        elif ordered_indexes == sorted(ordered_indexes, reverse=True):
            preference = DistancePreference.FARTHER_IS_BETTER
        else:
            return None
        try:
            return FactorRule(
                id=factor_id,
                input_type='facility',
                grading_method='facility_distance',
                grades=grades,
                facility_rule=FacilityDistanceRule(
                    nonexistent_grade_index=absent[0],
                    in_section_grade_index=in_section[0],
                    ranges=ranges,
                    preference=preference,
                ),
                matrix=matrix,
            )
        except ValueError:
            return None

    def _numeric_ranges(
        self, bodies: tuple[str, ...]
    ) -> tuple[NumericRangeRule, ...] | None:
        result: list[NumericRangeRule] = []
        for grade_index, body in enumerate(bodies, start=1):
            intervals = _parse_numeric_intervals(body)
            if not intervals:
                return None
            result.extend(
                NumericRangeRule(
                    grade_index=grade_index,
                    min_value=minimum,
                    min_inclusive=min_inclusive,
                    max_value=maximum,
                    max_inclusive=max_inclusive,
                )
                for minimum, min_inclusive, maximum, max_inclusive in intervals
            )
        return tuple(result)

    def _count_ranges(
        self, bodies: tuple[str, ...]
    ) -> tuple[NumericRangeRule, ...] | None:
        if not any('項' in body for body in bodies):
            return None
        result: list[NumericRangeRule] = []
        for grade_index, body in enumerate(bodies, start=1):
            compact = _compact(body)
            if compact == '無':
                number, at_least = 0, False
            else:
                match = re.fullmatch(r'([零一二兩三四五六七八九十]|\d+)項(以上)?', compact)
                if match is None:
                    return None
                number = _COUNT_WORDS.get(match.group(1), int(match.group(1)) if match.group(1).isdigit() else -1)
                at_least = match.group(2) is not None
            if number < 0:
                return None
            result.append(
                NumericRangeRule(
                    grade_index=grade_index,
                    min_value=Decimal(number),
                    max_value=None if at_least else Decimal(number + 1),
                )
            )
        return tuple(result)

    def _manual_rule(
        self,
        factor_id: str,
        grades: tuple[GradeDefinition, ...],
        matrix: tuple[tuple[Decimal, ...], ...],
    ) -> FactorRule:
        return FactorRule(
            id=factor_id,
            input_type='manual',
            grading_method='manual',
            grades=grades,
            matrix=matrix,
        )

    def _build_ruleset(
        self,
        *,
        title: str,
        locality: str,
        land_use: str,
        scope: RulesetScope,
        factors: tuple[StructuredFactorRule, ...],
        source_name: str,
    ) -> StructuredRuleset:
        identity = f'{locality}|{land_use}|{scope.value}'.encode()
        ruleset_id = 'ruleset-' + hashlib.sha256(identity).hexdigest()[:16]
        content = [
            {
                'id': factor.rule.id,
                'criteria': factor.criteria,
                'matrix': [
                    [format(cell, 'f') for cell in row]
                    for row in factor.rule.matrix or ()
                ],
            }
            for factor in factors
        ]
        digest = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:16]
        return StructuredRuleset(
            id=ruleset_id,
            version='ocr-' + digest,
            title=title,
            locality=locality,
            land_use=land_use,
            scope=scope,
            factors=factors,
            source_name=source_name,
        )


def _group_visual_rows(lines: Iterable[_Line], height: float) -> list[list[_Line]]:
    rows: list[list[_Line]] = []
    tolerance = max(2.0, height * 0.008)
    for line in sorted(lines, key=lambda item: (item.center_y, item.x1)):
        row = next(
            (
                existing
                for existing in reversed(rows[-3:])
                if abs(
                    sum(item.center_y for item in existing) / len(existing)
                    - line.center_y
                )
                <= max(tolerance, line.height * 0.7)
            ),
            None,
        )
        if row is None:
            rows.append([line])
        else:
            row.append(line)
    return rows


def _matrix_numbers(text: str) -> tuple[Decimal, ...]:
    normalized = _numeric_text(text)
    tokens = _NUMBER.findall(normalized)
    if not tokens:
        return ()
    residue = _NUMBER.sub('', normalized)
    if residue.strip():
        return ()
    try:
        return tuple(Decimal(token.lstrip('+')) for token in tokens)
    except InvalidOperation:
        return ()


def _parse_numeric_intervals(
    text: str,
) -> tuple[tuple[Decimal | None, bool, Decimal | None, bool], ...]:
    normalized = _numeric_text(text)
    intervals: list[tuple[Decimal | None, bool, Decimal | None, bool]] = []
    for segment in re.split(r'或', normalized):
        between = _BETWEEN.search(segment)
        if between:
            intervals.append((Decimal(between.group(1)), True, Decimal(between.group(2)), False))
            continue
        below = _BELOW.search(segment)
        if below:
            intervals.append((None, True, Decimal(below.group(1)), False))
            continue
        at_least = _AT_LEAST.search(segment)
        if at_least:
            intervals.append((Decimal(at_least.group(1)), True, None, False))
            continue
        at_most = _AT_MOST.search(segment)
        if at_most:
            intervals.append((None, True, Decimal(at_most.group(1)), True))
    return tuple(intervals)


def _numeric_text(value: str) -> str:
    text = _normalize_ocr_text(value).strip().translate(
        str.maketrans({'＋': '+', '－': '-', '−': '-', '﹣': '-', '％': '%'})
    )
    text = re.sub(r'm[\{\^]?[2²]\}?\$?', 'm2', text, flags=re.IGNORECASE)
    return re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', text)


def _compact(value: str) -> str:
    normalized = _normalize_ocr_text(value)
    return re.sub(r'\s+', '', normalized).replace('（', '(').replace('）', ')')


def _normalize_ocr_text(value: str) -> str:
    return value.translate(_OCR_CHARACTER_NORMALIZATION)


def _clean_criterion_body(value: str) -> str:
    for marker in (
        '以都市',
        '以建',
        '以容',
        '以區',
        '以該',
        '以各',
        '以接近',
        '以宗地',
        '以道路',
        '以使用',
        '以其他足以',
    ):
        position = value.find(marker, 1)
        if position >= 0 and any(
            ending in value[position:]
            for ending in ('衡量', '制定', '判定', '計算', '影響地價')
        ):
            return value[:position]
    return value


def _structural_factor_fragment(text: str) -> bool:
    if text in {'細', '項', '細項', '價', '價格', '主要', '主要項目', '基準', '目標', '區段', '宗'}:
        return True
    return any(marker in text for marker in ('比較標的', '比準地', '比凖地', '準地', '凖地', '宗地'))


def _finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _positive_number(value) -> bool:
    return _finite_number(value) and float(value) > 0
