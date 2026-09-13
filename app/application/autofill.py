"""Complete missing fields with registered functions; preserve unconfirmed provenance."""
import re
import time
import uuid
from app.application.autofill_contracts import AutofillRequest, FieldDataSource, AutofillDraftStore
from app.application.drafts import parse_case
from app.application.ports import RevisionConflict, ReviewRepository
from app.domain.applicability import require_ruleset_scope
from app.domain.confirmation import invalidate_confirmations
from app.domain.engine import classify, review
from app.domain.models import Factor, FieldSource, Evidence
from app.domain.calculations import (calculate_average_road_width, calculate_building_density,
                                     calculate_straight_line_distance)

CASE_FIELDS = ('case_number', 'valuation_date', 'subject_name', 'comparable_name',
               'subject_address', 'comparable_address', 'subject_section', 'comparable_section')
FIELDS = ('subject', 'comparable', 'subject_grade', 'comparable_grade', 'entered_rate')
METHODS = {
    '區段內道路平均寬度': (calculate_average_road_width, ('opened_road_widths_m',), 'm'),
    '道路平均寬度': (calculate_average_road_width, ('opened_road_widths_m',), 'm'),
    '建築密度': (calculate_building_density, ('built_land_area_m2', 'section_total_area_m2'), '%'),
}
ALIASES = {'接近公園廣場之程度': '接近公園廣場徒步區之程度',
           '停車方便性': '停車場地之便利程度', '學校': '接近學校之程度',
           '市場': '接近市場之程度', '公園': '接近公園廣場徒步區之程度'}


def compact(value):
    return re.sub(r'[\s、，,（）()／/]', '', str(value))


def empty(value):
    return value is None or isinstance(value, str) and not value.strip()


def marked_choices(pages, rule):
    """Read only explicit checked options on a row naming both sides."""
    values = set(v for band in rule['bands'] for v in (band.get('values') or []))
    values.update(band['label'] for band in rule['bands'])
    results = {}
    for page in pages:
        for line in page['text'].splitlines():
            if compact(rule['name']) not in compact(line):
                continue
            if '比準地' not in line or '比較標的' not in line:
                continue
            if re.search(r'比較標的[二三23]', line):
                continue
            match = re.search(r'比準地[：:]?(.*?)比較標的[：:]?(.*)', line)
            if not match:
                continue
            for side, text in zip(('subject', 'comparable'), match.groups()):
                selected = [v for v in values if re.search(r'[☑■●]\s*'+re.escape(v)+r'(?![\w])', text)]
                if len(selected) == 1:
                    results.setdefault(side, []).append((selected[0], page['page'], line))
    return {side: items[0] for side, items in results.items() if len({v[0] for v in items}) == 1}


class AutofillService:
    def __init__(self, repository: ReviewRepository, data: FieldDataSource, drafts: AutofillDraftStore):
        self.repository, self.data, self.drafts = repository, data, drafts

    def preview(self, case_id, request: AutofillRequest):
        case = self.repository.get_case(case_id)
        if case.revision != request.revision:
            raise RevisionConflict('案件已更新，請重新查詢。')
        rules = self.repository.get_rules(case.ruleset_id)
        working = case.model_copy(deep=True)
        saved = {f.id: f for f in working.factors}
        patches, gaps, trace = [], [], []
        rule_ref = f'{rules["id"]}/{rules["version"]}'
        for rule in rules['rules']:
            if rule['id'] not in saved:
                saved[rule['id']] = Factor(id=rule['id'])
                working.factors.append(saved[rule['id']])

        def add(fid, field, value, kind, reference, detail=''):
            target = saved[fid] if fid else (working if field in CASE_FIELDS else working.totals)
            if value is None or not empty(getattr(target, field)):
                return
            # Validate values with the same models used by normal case edits.
            setattr(target, field, value)
            validated = type(target).model_validate(target.model_dump())
            value = getattr(validated, field)
            setattr(target, field, value)
            origin = FieldSource(factor_id=fid, field=field, kind=kind, value=str(value),
                                 reference=reference, detail=detail[:3000])
            patches.append(dict(factor_id=fid, field=field, value=value, source=origin.model_dump()))

        if case.document_id:
            document = self.repository.get_document(case.document_id)
            parsed = parse_case(document['pages'], case.title, rules)
            multiple = any('多筆已填比較標的' in w for w in parsed.extraction_warnings)
            if multiple:
                gaps.append(dict(reason='題目含多比較標的，未混合填入單一標的案件。'))
            else:
                for rule in rules['rules']:
                    if saved[rule['id']].exempt or saved[rule['id']].note.strip():
                        continue
                    for field, (value, page, quote) in marked_choices(document['pages'], rule).items():
                        add(rule['id'], field, value, 'document', f'document:{case.document_id}:p{page}', quote)
                for factor in parsed.factors:
                    if factor.id not in saved or saved[factor.id].exempt or saved[factor.id].note.strip():
                        continue
                    # Text parsers must not read unchecked option labels as values.
                    if any(marker in factor.evidence.quote for marker in '☑☐□■●○'):
                        continue
                    ref = f'document:{case.document_id}:p{factor.evidence.page}'
                    for field in FIELDS:
                        add(factor.id, field, getattr(factor, field), 'document', ref, factor.evidence.quote)
                for field in CASE_FIELDS:
                    value = getattr(parsed, field)
                    if empty(value):
                        continue
                    source = next(((page['page'], line) for page in document['pages']
                        for line in page['text'].splitlines() if str(value) in line), None)
                    if source:
                        add(None, field, value, 'document', f'document:{case.document_id}:p{source[0]}', source[1])
                for field, value in parsed.totals.model_dump().items():
                    evidence = parsed.total_evidence.get(field)
                    if evidence:
                        add(None, field, value, 'document', f'document:{case.document_id}:p{evidence.page}', evidence.quote)
            trace.append(dict(function='parse_case / marked_choices', status='done'))

        catalog = self.data.catalog()
        coverage, keys = [], set()
        for rule in rules['rules']:
            name = ALIASES.get(compact(rule['name']), compact(rule['name']))
            sources = [s for s in catalog if compact(s['item']) == name]
            keys.update(s['key'] for s in sources)
            coverage.append(dict(factor_id=rule['id'], name=rule['name'], sources=sources))
        public = dict(sources=[], candidates=[], gaps=[])
        if request.query_public_data and keys:
            public = self.data.lookup(case.locality, sorted(keys), request.school_year)
            trace.append(dict(function='fetch_valuation_factors', status='done', sources=sorted(keys)))
        for row in coverage:
            factor = saved[row['factor_id']]
            if row['sources'] and (empty(factor.subject) or empty(factor.comparable)):
                gaps.append(dict(factor_id=factor.id, reason=('已查設施清冊；' if request.query_public_data else '本次未查詢設施清冊；')+'尚缺標的定位、區段／設施關聯及適用量測方式，未將候選填成有或無。'))

        try:
            require_ruleset_scope(case, rules)
            applicable = not rules.get('requires_confirmation', False)
        except ValueError:
            applicable = False
        for rule in rules['rules']:
            factor = saved[rule['id']]
            if not applicable or rule.get('blocked') or factor.exempt or factor.note.strip():
                gaps.append(dict(factor_id=factor.id, reason='基準適用性、封鎖項目或特殊調整須先核對。'))
                continue
            method = METHODS.get(compact(rule['name']))
            # A distance function may be used only when the configured rule
            # explicitly requires planar straight-line distance.
            if '直線距離' in rule['name'] and rule.get('unit') in ('m', '公尺'):
                method = (calculate_straight_line_distance, ('coordinates_m',), 'm')
            if method:
                function, required, unit = method
                for side in ('subject', 'comparable'):
                    observation = getattr(request, side)
                    if not empty(getattr(factor, side)):
                        continue
                    if not observation.source.strip() or any(getattr(observation, key) is None for key in required):
                        gaps.append(dict(factor_id=factor.id, field=side, reason='缺少量測來源與輸入：'+', '.join(required)))
                        continue
                    if rule.get('unit') not in (unit, '公尺' if unit == 'm' else unit):
                        gaps.append(dict(factor_id=factor.id, reason='量測函式與基準單位不同。'))
                        continue
                    args = [getattr(observation, key) for key in required]
                    try:
                        value = function(*args[0]) if required == ('coordinates_m',) else function(*args)
                    except ValueError:
                        gaps.append(dict(factor_id=factor.id, field=side, reason='量測輸入無效，未填值。'))
                        continue
                    add(factor.id, side, str(value), 'calculation', function.__name__,
                        observation.source+'；'+str(observation.model_dump(mode='json', include=set(required))))
                    trace.append(dict(function=function.__name__, factor_id=factor.id, side=side, status='done'))
            indices = [classify(getattr(factor, side), rule) for side in ('subject', 'comparable')]
            labels = [band['label'] for band in rule['bands']]
            for side, index in zip(('subject', 'comparable'), indices):
                if index is not None:
                    add(factor.id, side+'_grade', labels[index], 'calculation', 'classify', rule_ref)
            # Only the existing deterministic review supplies rates. Do not
            # silently confirm the working copy just to make it calculate.
        result = review(invalidate_confirmations(case, working), rules)
        for item in result['checks']:
            if item.get('expected') is None:
                continue
            if item.get('factor_id'):
                add(item['factor_id'], 'entered_rate', item['expected'], 'calculation', 'review', rule_ref)
            elif item.get('total_field'):
                add(None, item['total_field'], item['expected'], 'calculation', 'review', item['title']+'；'+rule_ref)
        trace.append(dict(function='classify / review', status='done'))
        for field in CASE_FIELDS:
            if empty(getattr(working, field)):
                gaps.append(dict(field=field, reason='題目未提供可唯一辨識的值，現有設施 API 不提供此案件欄位。'))
        for field, value in working.totals.model_dump().items():
            if empty(value):
                gaps.append(dict(field=field, reason='尚缺計算輸入或人工確認，未推定數值。'))
        for row in coverage:
            factor = saved[row['factor_id']]
            row['missing_fields'] = [field for field in FIELDS if empty(getattr(factor, field))]
            row['status'] = 'pending' if row['missing_fields'] else 'draft'
        if self.repository.get_case(case_id).revision != request.revision:
            raise RevisionConflict('查詢期間案件已更新，請重新查詢。')
        token = uuid.uuid4().hex
        draft = dict(case_id=case_id, revision=request.revision, created_at=time.time(), patches=patches)
        self.drafts.put(token, draft)
        return dict(token=token, revision=request.revision, patches=patches, coverage=coverage,
                    public_data=public, gaps=gaps, trace=trace,
                    message='僅補有來源的空欄；套用後仍待確認。查無設施不等於無，未確認資料不自動核准。')

    def apply(self, case_id, revision, token):
        draft = self.drafts.get(token)
        if not draft or draft['case_id'] != case_id or draft['revision'] != revision or time.time()-draft['created_at'] > 900:
            raise ValueError('選填草稿不存在或已過期，請重新查詢。')
        case = self.repository.get_case(case_id)
        if case.revision != revision:
            raise RevisionConflict('案件已更新，請重新查詢；未套用舊結果。')
        if not draft['patches']:
            return case
        proposed = case.model_copy(deep=True)
        factors = {f.id: f for f in proposed.factors}
        new_sources = []
        for patch in draft['patches']:
            fid, field = patch['factor_id'], patch['field']
            if fid and fid not in factors:
                factors[fid] = Factor(id=fid)
                proposed.factors.append(factors[fid])
            target = factors[fid] if fid else (proposed if field in CASE_FIELDS else proposed.totals)
            if not empty(getattr(target, field)):
                raise RevisionConflict('欄位已有值，未覆寫現有資料。')
            setattr(target, field, patch['value'])
            source = FieldSource.model_validate(patch['source'])
            if fid and source.kind == 'document' and not target.evidence.quote:
                page = re.search(r':p(\d+)$', source.reference)
                if page:
                    target.evidence = Evidence(page=int(page[1]), quote=source.detail, method='autofill-document')
            new_sources.append(source)
        proposed = invalidate_confirmations(case, proposed)
        replaced = {(s.factor_id, s.field) for s in new_sources}
        proposed.field_sources = [s for s in proposed.field_sources if (s.factor_id, s.field) not in replaced] + new_sources
        return self.repository.save_case(proposed, '依來源自動選填空欄（待確認）')
