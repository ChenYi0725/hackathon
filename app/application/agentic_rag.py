"""Bounded agent orchestration; all executable functions are explicitly registered."""
import hashlib
import json
from app.application.ports import ExtractionUnavailable, RevisionConflict, ReviewRepository, EvidenceRetriever, AgentModel
from app.application.agent_contracts import TOOL_INPUTS, ToolResult, tool_catalog, CaseMeasurements
from app.application.agent_calculations import METHODS, calculate_measurement
from app.application.rag_contracts import EvidenceQuery
from app.domain.applicability import require_ruleset_scope, valuation_day
from app.domain.engine import review

MAX_TURNS = 8
MAX_TOOLS = 12


class AgenticRagService:
    def __init__(self, repository: ReviewRepository, retriever: EvidenceRetriever, model: AgentModel, public_data=None):
        self.repository, self.retriever, self.model = repository, retriever, model
        self.public_data = public_data

    def query(self, case_id, revision, question, cloud_data_approved=False, *, measurements=None):
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
        measurements = CaseMeasurements.model_validate(measurements or {})
        hits, trace, history, seen_calls = {}, [], [], set()
        api_sources, public_results, computations = {}, [], []
        field_gaps = []
        calculation = None
        repair_used = False
        rule_ids = [rule["id"] for rule in rules["rules"]]
        context = dict(question=scope.question, case_revision=revision, ruleset_id=rules['id'], ruleset_version=rules['version'],
                       locality=case.locality, land_use=case.land_use, valuation_date=case.valuation_date,
                       factors=[dict(id=r['id'], name=r['name']) for r in rules['rules']],
                       calculation_methods={name: dict(required_fields=list(spec[1]), unit=spec[2])
                                            for name, spec in METHODS.items()})

        def execute(name, args):
            nonlocal calculation
            if name == 'inspect_case':
                saved = {f.id: f for f in case.factors}
                for rule in rules['rules']:
                    factor = saved.get(rule['id'])
                    missing = [key for key in ('subject', 'comparable', 'entered_rate')
                               if factor is None or getattr(factor, key) is None or
                               (isinstance(getattr(factor, key), str) and not getattr(factor, key).strip())]
                    if missing and not any(g['rule_id'] == rule['id'] for g in field_gaps):
                        field_gaps.append(dict(rule_id=rule['id'], name=rule['name'], missing_fields=missing))
                return dict(factors=[f.model_dump(mode='json') for f in case.factors], field_gaps=field_gaps,
                            measurements=measurements.model_dump(mode='json'),
                            warning='未確認欄位與 API 候選需人工核對；使用 list_data_sources 尋找可補資料的來源。')
            if name == 'list_data_sources':
                if self.public_data is None:
                    raise ValueError('政府資料工具未設定。')
                return self.public_data.catalog()
            if name == 'query_public_data':
                if self.public_data is None:
                    raise ValueError('政府資料工具未設定。')
                result = self.public_data.lookup(case.locality, args.source_key, args.school_year)
                api_sources.update((s['id'], s) for s in result.get('sources', []))
                public_results.append(result)
                return result
            if name == 'calculate_measurement':
                if args.citation_id not in hits:
                    raise ValueError('須先取得適用的規範文件引用。')
                result = dict(calculate_measurement(getattr(measurements, args.side), args.method),
                              side=args.side, citation_id=args.citation_id, case_revision=revision)
                computations.append(result)
                return result
            if name == 'calculate_factor':
                if args.rule_id not in rule_ids:
                    raise ValueError('未知案件規則。')
                result = review(case, rules)
                item = next(c for c in result['checks'] if c['id'] == args.rule_id)
                output = dict(method='configured_factor_review', rule_id=args.rule_id,
                              ruleset_id=rules['id'], ruleset_version=rules['version'],
                              case_revision=revision, check=item, source='deterministic-engine',
                              inputs=next((f.model_dump(mode='json') for f in case.factors if f.id == args.rule_id), None))
                computations.append(output)
                return output
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

        for turn_index in range(MAX_TURNS):
            check_revision()
            context.update(remaining_turns=MAX_TURNS-turn_index, remaining_tools=MAX_TOOLS-len(trace))
            turn = self.model.next_turn(context, history, tool_catalog(rule_ids))
            check_revision()
            if turn.calls and turn.answer is not None:
                raise ExtractionUnavailable('模型同時回傳工具與答案，請重試。')
            if not turn.calls:
                draft = turn.answer
                invalid_citations = draft is None or any(
                    not set(statement.citation_ids).issubset(hits.keys() | api_sources.keys()) for statement in draft.statements
                )
                stopped_after_error = draft is not None and draft.insufficient_evidence and (
                    calculation is None and trace and trace[-1]['status'] == 'error'
                )
                if (invalid_citations or stopped_after_error) and not repair_used and turn_index < MAX_TURNS - 1:
                    repair_used = True
                    history.append(dict(continuation=turn.continuation, feedback=dict(
                        error='答案未通過引用檢查或工具失敗後提前結束。請修正工具參數並完成使用者要求；不要自行計算。',
                        valid_rule_ids=rule_ids, valid_citation_ids=list(hits) + list(api_sources),
                        instruction='只能引用 valid_citation_ids 中支持該段說明的文件。規則設定與程式計算另行呈現，刪除無文件支持的段落；來源不足時回空 statements。',
                    )))
                    continue
                if invalid_citations and calculation is None and not computations and not public_results:
                    raise ExtractionUnavailable('Agent 未提供有效來源引用，請重新查找來源。')
                # Keep deterministic results even if the model cannot repair its prose.
                statements = [] if invalid_citations or draft.insufficient_evidence else [s.model_dump() for s in draft.statements]
                message = ('Agent 說明未通過來源引用檢查，已隱藏；程式審查結果仍保留。'
                           if invalid_citations else 'Agent 說明為待核對草稿；下方審查結果由確定性引擎產生。')
                return dict(case_revision=revision, ruleset_id=rules['id'], ruleset_version=rules['version'],
                            status='draft' if statements else 'insufficient_evidence', statements=statements,
                            hits=[h.model_dump(mode='json') for h in hits.values()], tool_trace=trace, review=calculation,
                            api_sources=list(api_sources.values()), public_data=public_results,
                            calculations=computations, field_gaps=field_gaps,
                            message=message)
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
                except ExtractionUnavailable:
                    status='error';data=dict(error='工具服務暫時無法使用，請稍後重試；保留其他已取得結果。')
                except (ValueError, KeyError):
                    status='error';data=dict(error='工具或參數無效，請依工具定義與已取得來源修正。')
                    if call.name in {'get_rule', 'calculate_factor'}:
                        data.update(error='rule_id 必須是 valid_rule_ids 中的完整值，不加基準 ID 或其他前綴。',
                                    valid_rule_ids=rule_ids)
                    elif call.name == 'read_source_page':
                        data.update(valid_citation_ids=list(hits))
                results.append(ToolResult(id=call.id,status=status,data=data).model_dump())
                trace.append(dict(tool=call.name,status=status))
            history.append(dict(continuation=turn.continuation,results=results))
        raise ExtractionUnavailable('Agent 已達推論輪數上限，請縮小問題範圍。')
