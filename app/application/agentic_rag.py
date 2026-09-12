"""Bounded agent orchestration; all executable functions are explicitly registered."""
import hashlib
import json
from app.application.ports import ExtractionUnavailable, RevisionConflict, ReviewRepository, EvidenceRetriever, AgentModel
from app.application.agent_contracts import TOOL_INPUTS, ToolResult, tool_catalog
from app.application.rag_contracts import EvidenceQuery
from app.application.open_data import OpenDataProvider, OpenDataUnavailable
from app.domain.applicability import require_ruleset_scope, valuation_day
from app.domain.engine import review

MAX_TURNS = 5
MAX_TOOLS = 8


class AgenticRagService:
    def __init__(self, repository: ReviewRepository, retriever: EvidenceRetriever, model: AgentModel,
                 public_data: OpenDataProvider | None = None):
        self.repository, self.retriever, self.model = repository, retriever, model
        self.public_data = public_data

    def query(self, case_id, revision, question, cloud_data_approved=False):
        if cloud_data_approved is not True:
            raise ValueError('請先確認問題、案件資料與來源文件均符合上雲規範。')
        case = self.repository.get_case(case_id)
        rules = self.repository.get_rules(case.ruleset_id)
        require_ruleset_scope(case, rules)
        scope = EvidenceQuery(question=question.strip(), ruleset_id=rules['id'], ruleset_version=rules['version'],
                              locality=case.locality, land_use=case.land_use, valuation_date=valuation_day(case.valuation_date))
        def check_revision():
            if self.repository.get_case(case_id).revision != revision:
                raise RevisionConflict('Agent 查詢期間案件已更新，請重新查詢。')
        check_revision()
        hits, trace, history, seen_calls = {}, [], [], set()
        public_sources, datasets = {}, {}
        calculation = None
        context = dict(question=scope.question, case_revision=revision, ruleset_id=rules['id'], ruleset_version=rules['version'],
                       locality=scope.locality, land_use=scope.land_use, valuation_date=str(scope.valuation_date),
                       factors=[dict(id=r['id'], name=r['name']) for r in rules['rules']])

        def execute(name, args):
            nonlocal calculation
            if name == 'search_public_datasets' and self.public_data is not None:
                result = self.public_data.search(args)
                datasets.update((d['dataset_id'], d) for d in result['datasets'])
                return result
            if name == 'read_public_dataset' and self.public_data is not None:
                dataset = datasets.get(args.dataset_id.lower())
                if dataset is None:
                    raise ValueError('請先搜尋本次需要的官方資料集。')
                result = self.public_data.read(args)
                result['title'] = dataset['title']
                if result['records']:
                    public_sources[result['id']] = result
                else:
                    result.pop('id', None)
                return result
            if name == 'search_evidence':
                found = self.retriever.retrieve(scope.model_copy(update={'question': args.question}))
                hits.update((h.id, h) for h in found)
                return dict(hits=[h.model_dump(mode='json') for h in found])
            if name == 'read_source_page':
                old = hits.get(args.citation_id)
                if old is None:
                    raise ValueError('只能讀取本次已檢索來源。')
                eligible = self.repository.evidence_sources(scope)
                doc = next((d for d in eligible if d['document_id'] == old.source.document_id), None)
                if doc is None:
                    raise ValueError('來源不適用本案。')
                page = next(p for p in doc['pages'] if p['page'] == old.source.page)
                text = page['text']
                if args.start >= len(text):
                    raise ValueError('來源字元位置超出頁面。')
                end = min(args.start + 2000, len(text))
                source = old.source.model_copy(update=dict(start=args.start, end=end, quote=text[args.start:end],
                                                           bbox=None, page_width=None, page_height=None))
                identity = f'{source.document_id}:{source.document_sha256}:{source.page}:{args.start}:{end}'
                hit = old.model_copy(update=dict(id=hashlib.sha256(identity.encode()).hexdigest(), source=source))
                hits[hit.id] = hit
                return dict(hit=hit.model_dump(mode='json'), page_characters=len(text), next_start=end if end<len(text) else None)
            if name == 'get_rule':
                rule = next((r for r in rules['rules'] if r['id'] == args.rule_id), None)
                if rule is None:
                    raise ValueError('未知的案件規則。')
                return dict(ruleset_id=rules['id'], ruleset_version=rules['version'], rule=rule,
                            warning='程式中的規則設定，不代表原文或人工核准。')
            if name == 'review_case':
                calculation = review(case, rules)
                return dict(case_revision=revision, counts=calculation['counts'], computed=calculation['computed'],
                            complete=calculation['complete'], checks=calculation['checks'], source='deterministic-engine')
            raise ValueError('未開放的工具。')

        for _ in range(MAX_TURNS):
            check_revision()
            turn = self.model.next_turn(context, history, tool_catalog(public_data=self.public_data is not None))
            check_revision()
            if turn.calls and turn.answer is not None:
                raise ExtractionUnavailable('模型同時回傳工具與答案，請重試。')
            if not turn.calls:
                draft = turn.answer
                if draft is None or any(not set(s.citation_ids).issubset(set(hits) | set(public_sources)) for s in draft.statements):
                    raise ExtractionUnavailable('Agent 未提供有效來源引用，請使用本機查找。')
                statements = [] if draft.insufficient_evidence else [s.model_dump() for s in draft.statements]
                return dict(case_revision=revision, ruleset_id=rules['id'], ruleset_version=rules['version'],
                            status='draft' if statements else 'insufficient_evidence', statements=statements,
                            hits=[h.model_dump(mode='json') for h in hits.values()], tool_trace=trace, review=calculation,
                            public_sources=list(public_sources.values()),
                            message='Agent 說明為待核對草稿；下方審查結果由確定性引擎產生。')
            if len(trace)+len(turn.calls)>MAX_TOOLS:
                raise ExtractionUnavailable('Agent 已達工具次數上限，請縮小問題範圍。')
            results=[]
            for call in turn.calls:
                check_revision()
                if call.id in seen_calls:
                    raise ExtractionUnavailable('模型重複工具呼叫 ID，請重試。')
                seen_calls.add(call.id)
                try:
                    model=TOOL_INPUTS.get(call.name)
                    if model is None:
                        raise ValueError('未開放的工具。')
                    args=model.model_validate(call.arguments)
                    data=execute(call.name,args)
                    check_revision()
                    if len(json.dumps(data,ensure_ascii=False))>24000:
                        raise ValueError('工具結果過大，請縮小查詢。')
                    status='success'
                except RevisionConflict:
                    raise
                except OpenDataUnavailable as error:
                    status='error';data=dict(error=str(error), retryable=True)
                except (ValueError, KeyError):
                    status='error';data=dict(error='工具或參數無效，請依工具定義與已取得來源修正。')
                results.append(ToolResult(id=call.id,status=status,data=data).model_dump())
                trace.append(dict(tool=call.name,status=status))
            history.append(dict(continuation=turn.continuation,results=results))
        raise ExtractionUnavailable('Agent 已達推論輪數上限，請縮小問題範圍。')
