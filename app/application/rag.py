"""Read-only retrieval and grounded explanation; never calculate or edit a case."""
from datetime import date
from app.application.ports import (ExtractionUnavailable, RevisionConflict, ReviewRepository,
                                   PdfReader, EvidenceRetriever, EvidenceAnswerer, EvidencePublisher)
from app.application.rag_contracts import EvidenceQuery
from app.domain.applicability import require_ruleset_scope, valuation_day


class RagService:
    def __init__(self, repository: ReviewRepository, pdf: PdfReader,
                 retriever: EvidenceRetriever, answerer: EvidenceAnswerer, agent=None,
                 publisher: EvidencePublisher | None = None, cloud_retrieval=False):
        self.repository, self.pdf = repository, pdf
        self.retriever, self.answerer = retriever, answerer
        self.agent = agent
        self.publisher, self.cloud_retrieval = publisher, cloud_retrieval

    def sync_sources(self, ruleset_id, cloud_data_approved=False):
        if cloud_data_approved is not True:
            raise ValueError('請先確認來源文件符合上雲規範。')
        if self.publisher is None:
            raise ValueError('尚未設定 AWS 知識庫。')
        self.repository.get_rules(ruleset_id)
        return self.publisher.sync_ruleset(ruleset_id)

    def sync_status(self):
        return self.publisher.status() if self.publisher else {'status': 'disabled'}

    def upload_source(self, ruleset_id, data, name, valid_from, valid_to):
        rules = self.repository.get_rules(ruleset_id)
        start, end = date.fromisoformat(valid_from), date.fromisoformat(valid_to)
        if start > end:
            raise ValueError('適用起日不可晚於迄日。')
        pages = self.pdf.read(data)
        if not any(p['text'].strip() for p in pages):
            raise ValueError('文件沒有可檢索文字，請檢查 OCR 結果。')
        return self.repository.save_evidence_document(data, name[:200], pages, rules, start, end)

    def query(self, case_id, revision, question, *, generate=False, cloud_data_approved=False, rule_ids=()):
        question = question.strip()
        case = self.repository.get_case(case_id)
        if case.revision != revision:
            raise RevisionConflict('案件已更新，請重新載入。')
        rules = self.repository.get_rules(case.ruleset_id)
        require_ruleset_scope(case, rules)
        if not set(rule_ids).issubset({r['id'] for r in rules['rules']}):
            raise ValueError('未知的因素 ID。')
        query = EvidenceQuery(question=question, ruleset_id=rules['id'], ruleset_version=rules['version'],
                              locality=case.locality, land_use=case.land_use,
                              valuation_date=valuation_day(case.valuation_date), rule_ids=tuple(rule_ids))
        if (generate or self.cloud_retrieval) and cloud_data_approved is not True:
            raise ValueError('請先確認問題與檢索文件符合競賽上雲規範；不得傳送個資或財務資訊。')
        hits = self.retriever.retrieve(query)
        statements = []
        status = 'sources' if hits else 'no_evidence'
        if generate and hits:
            draft = self.answerer.answer(question, hits)
            allowed = {h.id for h in hits}
            if any(not set(s.citation_ids).issubset(allowed) for s in draft.statements):
                raise ExtractionUnavailable('模型引用不在檢索結果中，請改用原文核對。')
            if draft.insufficient_evidence or not draft.statements:
                status = 'insufficient_evidence'
            else:
                statements = [s.model_dump() for s in draft.statements]
                status = 'draft'
        if self.repository.get_case(case_id).revision != revision:
            raise RevisionConflict('查詢期間案件已更新，請重新查詢。')
        return dict(case_revision=revision, ruleset_id=rules['id'], ruleset_version=rules['version'],
                    status=status, hits=[h.model_dump(mode='json') for h in hits], statements=statements,
                    message='說明草稿須人工核對；引用存在不代表結論正確。估價運算請使用審查結果。' if statements else
                    '未找到足夠依據時請補充適用基準文件；檢索不會更換案件基準或修改資料。')
