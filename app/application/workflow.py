"""Core review use cases, all long work guarded by input and evidence versions."""
from datetime import datetime, timezone
import uuid
import re
from app.application.ports import RevisionConflict
from app.domain.models import Evidence
from app.domain.workflow import calculate, digest
from app.domain.confirmation import invalidate_confirmations


def stamp():
    return datetime.now(timezone.utc).isoformat()


class WorkflowService:
    def __init__(self, service, documents, renderer, external):
        self.service, self.repo = service, service.repository
        self.documents, self.renderer, self.external = documents, renderer, external

    def current(self, cid, revision):
        case = self.repo.get_case(cid)
        if case.revision != revision:
            raise RevisionConflict('案件已變更，請重新載入。')
        return case

    def run(self, cid, revision):
        case = self.current(cid, revision)
        rules = self.repo.get_rules(case.ruleset_id)
        evidence = self.repo.external_for(cid, revision)
        identity = dict(case_id=cid, case_revision=revision, input_hash=digest(case.model_dump()),
                        rules_hash=digest(rules), evidence_hash=digest(evidence), engine_version='core-1')
        run = dict(identity, id=digest(identity), generated_at=stamp(),
                   case=case.model_dump(), rules=rules, evidence=evidence,
                   review=calculate(case, rules, evidence))
        self.current(cid, revision)
        if digest(self.repo.external_for(cid, revision)) != identity['evidence_hash']:
            raise RevisionConflict('佐證已更新，請重新執行檢核。')
        return self.repo.save_run(run)

    def validated_run(self, cid, revision, run_id):
        case = self.current(cid, revision)
        run = self.repo.get_run(cid, run_id)
        if (run['case_revision'] != revision or run['input_hash'] != digest(case.model_dump()) or
            run['rules_hash'] != digest(self.repo.get_rules(case.ruleset_id)) or
            run['evidence_hash'] != digest(self.repo.external_for(cid, revision))):
            raise RevisionConflict('檢核結果已過期，請重新審查。')
        return run

    def disposition(self, cid, revision, run_id, check_id, decision, reason, operation_id):
        # An exact retry is idempotent, including after a later edit.
        for old in self.repo.dispositions(cid):
            if old['id'] == operation_id:
                if any(old[k] != v for k, v in dict(run_id=run_id, check_id=check_id, decision=decision, reason=reason).items()):
                    raise RevisionConflict('操作 ID 已用於不同處置。')
                return old
        run = self.validated_run(cid, revision, run_id)
        item = next((r for r in run['review']['checks'] if r['id'] == check_id), None)
        if not item or decision not in ('accept', 'reject') or not reason.strip():
            raise ValueError('請選擇有效檢核項目、接受或拒絕，並填寫原因。')
        return self.repo.save_disposition(dict(id=operation_id, case_id=cid, case_revision=revision,
            run_id=run_id, check_id=check_id, decision=decision, reason=reason.strip(), at=stamp(),
            original=item.get('actual'), expected=item.get('expected'), technical_status=item['status']))

    def upload(self, cid, revision, data, name):
        case = self.current(cid, revision)
        # No case mutation occurs until parsing succeeds and the revision is checked again.
        parsed = self.documents.read(data, name)
        self.current(cid, revision)
        docid = self.repo.save_document(data, name, parsed['pages'])
        candidate = case.model_copy(deep=True)
        candidate.document_ids = list(dict.fromkeys([*case.document_ids, *([case.document_id] if case.document_id else []), docid]))
        if parsed['kind'] == 'pdf':
            candidate.document_id = docid
        candidate.extraction_warnings = list(dict.fromkeys([*case.extraction_warnings, *parsed['warnings']]))[:100]
        candidate = self.repo.save_case(invalidate_confirmations(case, candidate), '新增文件版本：' + name)
        return dict(**self.service.payload(candidate), document_id=docid, parsed=parsed)

    def apply_cell(self, cid, revision, document_id, sheet, cell, target):
        case = self.current(cid, revision)
        if document_id not in case.document_ids:
            raise ValueError('來源文件不屬於此案件。')
        doc = self.repo.get_document(document_id)
        page = next((p for p in doc['pages'] if p.get('sheet') == sheet), None)
        item = page.get('cells', {}).get(cell) if page else None
        if page and item is None and re.fullmatch(r'[A-Z]{1,2}[1-9][0-9]{0,3}', cell):
            letters, digits = re.fullmatch(r'([A-Z]+)(\d+)', cell).groups()
            column = 0
            for char in letters:column = column * 26 + ord(char) - 64
            if int(digits) <= page.get('max_row', 0) and column <= page.get('max_column', 0):
                item = dict(value=None, formula=None, presence='blank')
        if not item:
            raise ValueError('找不到來源儲存格。')
        # Formula caches may be stale: preserve them for inspection but require manual transcription.
        if item.get('formula'):
            raise ValueError('公式儲存格只能查看原式及快取；請核對後人工填寫，不自動採用快取。')
        value = item['value']
        source = Evidence(document_id=document_id, page=page['page'], sheet=sheet, cell=cell,
                          quote=str(value) if value is not None else '', method='xlsx-cell', sha256=page['sha256'])
        parts = target.split('.')
        candidate = case.model_copy(deep=True)
        target_object = candidate
        if len(parts) >= 3 and parts[0] == 'comparisons':
            target_object = next((c for c in candidate.additional_comparisons if c.id == parts[1]), None)
            if target_object is None:
                raise ValueError('未知比較標的。')
            parts = parts[2:]
        if len(parts) == 3 and parts[0] == 'factors' and parts[2] in ('subject', 'comparable', 'entered_rate', 'subject_grade', 'comparable_grade'):
            factor = next((f for f in target_object.factors if f.id == parts[1]), None)
            if not factor:
                raise ValueError('未知因素。請先在資料核對中建立該因素。')
            if parts[2] != 'entered_rate' and value is not None:
                value = str(value)
            setattr(factor, parts[2], value)
            factor.evidence = source
        elif len(parts) == 2 and parts[0] == 'totals' and parts[1] in type(target_object.totals).model_fields:
            setattr(target_object.totals, parts[1], value)
        elif target in ('valuation_date', 'subject_section', 'comparable_section', 'subject_name', 'comparable_name'):
            setattr(candidate, target, '' if value is None else str(value))
        else:
            raise ValueError('不支援的目標欄位。')
        candidate.field_sources[target] = source
        # Re-validate typed numeric fields (setattr alone is not validation).
        return self.service.save_case(type(case).model_validate(candidate.model_dump()))

    def lookup(self, cid, revision, factor_id, query):
        case = self.current(cid, revision)
        rules = self.repo.get_rules(case.ruleset_id)
        if factor_id not in {r['id'] for r in rules['rules']}:
            raise ValueError('未知因素。')
        comparison_id = query.get('comparison_id', 'primary')
        if comparison_id not in {'primary', *(c.id for c in case.additional_comparisons)}:
            raise ValueError('未知比較標的。')
        result = self.external.query(query)
        result.update(id=uuid.uuid4().hex, factor_id=factor_id, queried_at=stamp(), query=query,
                      case_revision=revision, ruleset_id=rules['id'], ruleset_version=rules['version'])
        result['comparison_id'] = comparison_id
        self.current(cid, revision)
        return self.repo.save_external(cid, revision, result)

    def export(self, cid, revision, run_id, kind):
        run = self.validated_run(cid, revision, run_id)
        decisions = self.repo.dispositions(cid)
        artifact = self.renderer.render(run, decisions, kind)
        self.validated_run(cid, revision, run_id)
        if decisions != self.repo.dispositions(cid):
            raise RevisionConflict('匯出期間人工處置已更新，請重新匯出。')
        return artifact

    def plan(self, cid):
        case = self.repo.get_case(cid)
        rules = self.repo.get_rules(case.ruleset_id)
        return dict(mode='deterministic-plan', case_revision=case.revision, ruleset_id=rules['id'],
                    ruleset_version=rules['version'], items=[dict(factor_id=r['id'],
                    table_check='等級／矩陣／原填值',
                    external_required=r.get('external_required', r['unit'] == 'm'),
                    external_status='尚未佐證', tools=['get_rule', 'review_case', 'search_evidence'],
                    reason='依欄位及固定基準規劃；距離事實與表內級距分別查核。') for r in rules['rules']])
