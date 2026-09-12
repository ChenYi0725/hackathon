"""Valuation use cases. No imports of FastAPI, AWS, Paddle or SQLite."""
from app.application.drafts import parse_case
from app.application.rag import RagService
from app.application.ports import FieldExtractor, PdfReader, ReviewRepository, RevisionConflict
from app.domain.engine import review
from app.domain.confirmation import invalidate_confirmations
from app.domain.models import Case
from app.domain.rule_validation import validate_ruleset
from app.domain.sample import sample_case
from app.application.export_contracts import ExportUnavailable, FormRenderer


class ReviewService:
    def __init__(self, repository: ReviewRepository, pdf: PdfReader, ai: FieldExtractor, rag: RagService | None = None, renderer: FormRenderer | None = None):
        self.repository, self.pdf, self.ai = repository, pdf, ai
        self.rag = rag
        self.renderer = renderer

    def export_document(self, case_id, kind, revision, generated_at):
        case = self.repository.get_case(case_id)
        if case.revision != revision:
            raise RevisionConflict('案件已更新，請重新載入後再匯出。')
        if self.renderer is None:
            raise ExportUnavailable('書表輸出尚未設定。')
        rules = self.repository.get_rules(case.ruleset_id)
        run = self.workflow.run(case_id, revision) if hasattr(self, 'workflow') else None
        result = dict(run['review'], run_id=run['id'], dispositions=self.repository.dispositions(case_id)) if run else review(case, rules)
        try:
            artifact = self.renderer.render(case.model_copy(deep=True), result, rules, kind, generated_at)
        except (ImportError, OSError) as error:
            raise ExportUnavailable('書表產製失敗；請檢查輸出套件、模板與中文字型設定。') from error
        if self.repository.get_case(case_id).revision != revision:
            raise RevisionConflict('產製期間案件已更新，請重新匯出。')
        if run:
            self.workflow.validated_run(case_id, revision, run['id'])
            if result['dispositions'] != self.repository.dispositions(case_id):
                raise RevisionConflict('產製期間人工處置已更新，請重新匯出。')
        return artifact

    def seed_examples(self, document=None):
        if self.repository.list_cases():
            return
        document_id = self.repository.save_document(*document) if document else None
        for demo in (False, True):
            case = sample_case(demo)
            case.document_id = document_id
            self.repository.save_case(case, '建立內建範例', new=True)

    def payload(self, case):
        if hasattr(self, 'workflow'):
            run = self.workflow.run(case.id, case.revision)
            return {'case': case.model_dump(), 'review': run['review'], 'run': {k: v for k, v in run.items() if k not in ('case', 'rules', 'evidence', 'review')},
                    'dispositions': self.repository.dispositions(case.id)}
        return {'case': case.model_dump(), 'review': review(case, self.repository.get_rules(case.ruleset_id))}

    def get_case(self, case_id):
        return self.payload(self.repository.get_case(case_id))

    def list_cases(self):
        return [dict(id=case.id, title=case.title, case_number=case.case_number, demo=case.demo,
                     updated=updated, counts=self.payload(case)['review']['counts'], source_kind=case.source_kind)
                for case, updated in self.repository.list_cases()]

    def validate_case(self, case):
        self.repository.get_rules(case.ruleset_id)
        ids = [f.id for f in case.factors]
        if len(ids) != len(set(ids)):
            raise ValueError('因素 ID 不可重複。')
        comparison_ids = [c.id for c in case.additional_comparisons]
        if 'primary' in comparison_ids or len(comparison_ids) != len(set(comparison_ids)):
            raise ValueError('比較標的 ID 不可重複或使用保留名稱 primary。')
        for comparison in case.additional_comparisons:
            ids = [f.id for f in comparison.factors]
            if len(ids) != len(set(ids)):
                raise ValueError('比較標的內的因素 ID 不可重複。')
        if case.document_id:
            self.repository.get_document(case.document_id)
        for docid in case.document_ids:
            self.repository.get_document(docid)

    def save_case(self, case: Case, *, new=False):
        self.validate_case(case)
        previous = None if new else self.repository.get_case(case.id)
        if previous is not None and previous.revision != case.revision:
            raise RevisionConflict('案件已更新，請重新載入。')
        candidate = invalidate_confirmations(previous, case)
        action = '建立或匯入案件' if new else '儲存欄位與重新審查' + ('；原因：' + case.change_reason.strip() if case.change_reason.strip() else '；未提供額外修改原因')
        saved = self.repository.save_case(candidate, action, new=new)
        return self.payload(saved)

    def create_sample(self, kind, document=None):
        if kind not in ('original', 'errors'):
            raise ValueError('未知的範例類型。')
        case = sample_case(kind == 'errors')
        if document:
            case.document_id = self.repository.save_document(*document)
        return self.payload(self.repository.save_case(case, '建立範例副本', new=True))

    def upload(self, data, name, ruleset_id):
        ruleset = self.repository.get_rules(ruleset_id)
        pages = self.pdf.read(data)
        case = parse_case(pages, name.removesuffix('.pdf')[:140] or '匯入案件', ruleset)
        case.extraction_warnings.insert(0, 'PaddleOCR 已辨識頁面文字；表格欄位及比較方向仍須人工核對。')
        for factor in case.factors:
            factor.evidence.method = 'paddleocr-layout'
        case.document_id = self.repository.save_document(data, name[:200], pages)
        for factor in case.factors:
            factor.evidence.document_id = case.document_id
        for source in case.field_sources.values():
            source.document_id = case.document_id
            source.method = "paddleocr-layout"
        return self.payload(self.repository.save_case(case, '上傳 PDF 與 PaddleOCR 辨識', new=True))

    def fix(self, case_id, check_id, revision):
        case = self.repository.get_case(case_id)
        previous = case.model_copy(deep=True)
        if revision != case.revision:
            raise RevisionConflict('案件已更新，請重新載入。')
        target = case
        if ':' in check_id:
            comparison_id, check_id = check_id.split(':', 1)
            comparison = next((c for c in case.additional_comparisons if c.id == comparison_id), None)
            if comparison is None:
                raise ValueError('未知比較標的。')
            target = comparison
            view = case.model_copy(update=dict(comparable_name=comparison.name, comparable_section=comparison.section,
                factors=comparison.factors, totals=comparison.totals, totals_confirmed=comparison.totals_confirmed))
        else:
            view = case
        result = review(view, self.repository.get_rules(case.ruleset_id))
        item = next((row for row in result['checks'] if row['id'] == check_id), None)
        if not item or item['status'] != 'error' or item['expected'] is None:
            raise ValueError('此項目前沒有可直接採用的修正建議。')
        if item.get('factor_id'):
            factor = next(f for f in target.factors if f.id == item['factor_id'])
            factor.entered_rate = item['expected']
            if factor.subject_grade is not None:
                factor.subject_grade = item['subject_grade']
            if factor.comparable_grade is not None:
                factor.comparable_grade = item['comparable_grade']
        elif item.get('total_field'):
            setattr(target.totals, item['total_field'], item['expected'])
        else:
            raise ValueError('請手動處理此項。')
        return self.payload(self.repository.save_case(invalidate_confirmations(previous, case), '採用建議：' + item['title']))

    def extract_ai(self, case_id, revision, cloud_data_approved=False):
        if cloud_data_approved is not True:
            raise ValueError('請先確認本文件符合競賽上雲規範；含個資或財務資訊的文件不可直接送至 AWS。')
        case = self.repository.get_case(case_id)
        if revision != case.revision:
            raise RevisionConflict('案件已更新，請重新載入。')
        if not case.document_id:
            raise ValueError('請先匯入 PDF。')
        document = self.repository.get_document(case.document_id)
        factors = self.ai.extract(document['pages'], self.repository.get_rules(case.ruleset_id))
        if self.repository.get_case(case_id).revision != revision:
            raise RevisionConflict('抽取期間案件已更新，請重新載入後再試。')
        for factor in factors:
            factor.evidence.document_id = case.document_id
        return dict(factors=[f.model_dump() for f in factors], revision=revision,
                    message='Bedrock 草稿尚未套用。引用與欄位值已做原文存在性檢查，兩側對應仍須人工確認。')

    def create_ruleset(self, ruleset):
        draft = dict(validate_ruleset(ruleset), approval_state='draft')
        for key in ('approved_at', 'approval_reason', 'approved_from'):
            draft.pop(key, None)
        return self.repository.add_rules(draft)

    def publish_ruleset(self, ruleset_id, reason, source_confirmed, matrix_confirmed, valid_from, valid_to):
        from app.domain.applicability import valuation_day
        from datetime import datetime, timezone
        if source_confirmed is not True or matrix_confirmed is not True or not reason.strip():
            raise ValueError('請核對原文及矩陣並填寫核准原因。')
        if valuation_day(valid_from) > valuation_day(valid_to):
            raise ValueError('基準適用期間前後顛倒。')
        original = self.repository.get_rules(ruleset_id)
        if original.get('approval_state') == 'published':
            raise ValueError('此版本已發布；請另建草稿版本。')
        published = dict(original, approval_state='published', valid_from=valid_from, valid_to=valid_to,
                         approved_at=datetime.now(timezone.utc).isoformat(), approval_reason=reason,
                         approved_from=ruleset_id)
        return self.repository.add_rules(validate_ruleset(published))
