"""Explicit synthetic-only integration: publish, ingest, retrieve and verify scope.

Run with RAG_BACKEND=bedrock-kb and the documented AWS settings. A dedicated
temporary SQLite store is used; no user documents or cases are read.
"""
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from app.application.rag_contracts import EvidenceQuery
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.settings import Settings
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.aws_rag_runtime import AwsRagRuntime
from app.infrastructure.knowledge_base import S3KnowledgeBasePublisher, BedrockKnowledgeBaseRetriever


def main():
    with tempfile.TemporaryDirectory(prefix='landwise-kb-smoke-') as directory:
        settings = Settings(data_dir=Path(directory))
        if settings.rag_backend != 'bedrock-kb':
            raise ValueError('This smoke requires explicit bedrock-kb configuration.')
        repository = SQLiteReviewRepository(settings.data_dir)
        repository.initialize()
        rules = dict(repository.get_rules('jinshan-commercial-v1'), id='synthetic-kb-smoke-v1')
        rules = repository.add_rules(rules)
        quote = 'SYNTHETIC TEST ONLY. Opened road widths are added and divided by the road count. Verify the original source before appraisal.'
        writer = PdfWriter()
        page = writer.add_blank_page(width=800, height=600)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 10 Tf 20 550 Td ({quote}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
        data = BytesIO(); writer.write(data)
        saved = repository.save_evidence_document(data.getvalue(), 'synthetic-kb-smoke.pdf',
            [dict(page=1, text=quote, method='synthetic')], rules, date(2025,1,1), date(2025,12,31))
        runtime = AwsRagRuntime(BedrockFieldExtractor(settings, repository))
        publisher = S3KnowledgeBasePublisher(settings, repository, runtime)
        status = publisher.sync_ruleset(rules['id'])
        print(json.dumps(status), flush=True)
        deadline = time.monotonic() + 600
        while status['status'] in {'starting', 'in_progress'} and time.monotonic() < deadline:
            time.sleep(10)
            status = publisher.status()
            print(json.dumps(status), flush=True)
        assert status['status'] == 'complete', status
        retriever = BedrockKnowledgeBaseRetriever(settings, repository, runtime)
        query = EvidenceQuery(question='How do I calculate average opened road width?', ruleset_id=rules['id'],
            ruleset_version=rules['version'], locality=rules['locality'], land_use=rules['land_use'], valuation_date=date(2025,9,1))
        hits = retriever.retrieve(query)
        assert len(hits) == 1 and hits[0].source.quote == quote, hits
        assert hits[0].source.document_id == saved['document_id']
        assert retriever.retrieve(query.model_copy(update={'ruleset_version': 'wrong'})) == []
        assert retriever.retrieve(query.model_copy(update={'valuation_date': date(2026,1,1)})) == []
        print(json.dumps(dict(result='passed', citation=hits[0].id, page=hits[0].source.page,
                              exact_quote=True, wrong_version_excluded=True, expired_excluded=True)), flush=True)
        if '--agent' in sys.argv:
            from app.application.agentic_rag import AgenticRagService
            from app.domain.models import Case
            from app.infrastructure.bedrock_agent import BedrockAgentModel
            from app.infrastructure.public_data import GovernmentDataLookup
            case = repository.save_case(Case(title='Synthetic AWS routing smoke', ruleset_id=rules['id'],
                valuation_date='2025-09-01'), 'synthetic-test', new=True)
            before = repository.audit(case.id)
            class TraceModel(BedrockAgentModel):
                def next_turn(self, context, history, tools):
                    turn = super().next_turn(context, history, tools)
                    print(json.dumps(dict(turn=len(history)+1, tools=[c.name for c in turn.calls],
                        previous_statuses=[r['status'] for r in history[-1].get('results', [])] if history else [])), flush=True)
                    return turn
            agent = AgenticRagService(repository, retriever,
                TraceModel(BedrockFieldExtractor(settings, repository)), GovernmentDataLookup())
            result = agent.query(case.id, case.revision,
                '合成測試：請先找已開闢道路平均寬度的規範與引用，檢查缺欄位，選用既有函式計算比準地道路平均寬度。'
                '再從已登錄 API 選擇公園來源，查詢本案金山區的候選公園並附來源；最後執行案件審查。'
                '這些是合成量測資料，政府資料只作候選，不套用案件。', True,
                measurements={'subject': {'opened_road_widths_m': ['6', '8', '10']}})
            print(json.dumps(dict(agent_status=result['status'], tool_trace=result['tool_trace'],
                calculations=result['calculations'], api_source_count=len(result['api_sources']),
                review_present=result['review'] is not None), ensure_ascii=False), flush=True)
            assert any(c.get('result') == '8' for c in result['calculations']), 'Agent did not select the requested calculation'
            assert any(t['tool']=='query_public_data' and t['status']=='success' for t in result['tool_trace'])
            assert result['review'] is not None and repository.audit(case.id)==before
            print('AWS agent routing passed; case and audit unchanged.', flush=True)


if __name__ == '__main__':
    main()
