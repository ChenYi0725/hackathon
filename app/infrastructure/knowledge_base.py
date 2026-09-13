"""S3 source publishing and Bedrock Knowledge Bases retrieval with exact provenance."""
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from filelock import FileLock, Timeout
from app.application.ports import ExtractionUnavailable
from app.application.rag_contracts import EvidenceHit, SourceSpan


def chunk_key(prefix, document_id, digest, page, start):
    return f'{prefix}chunks/{document_id}/{digest}/{page}/{start}.txt'


class BedrockKnowledgeBaseRetriever:
    def __init__(self, settings, repository, runtime):
        self.settings, self.repository, self.runtime = settings, repository, runtime

    def retrieve(self, query):
        documents = {d['document_id']: d for d in self.repository.evidence_sources(query)}
        if not documents:
            return []
        filters = [{'equals': {'key': key, 'value': getattr(query, key)}}
                   for key in ('ruleset_id', 'ruleset_version', 'locality', 'land_use')]
        day = query.valuation_date.toordinal()
        filters.extend([{'lessThanOrEquals': {'key': 'valid_from_day', 'value': day}},
                        {'greaterThanOrEquals': {'key': 'valid_to_day', 'value': day}}])
        rules = self.repository.get_rules(query.ruleset_id)
        pages = sorted({r['source_page'] for r in rules['rules'] if r['id'] in query.rule_ids})
        if pages:
            page_filters = [{'equals': {'key': 'page', 'value': page}} for page in pages]
            filters.append(page_filters[0] if len(pages) == 1 else {'orAll': page_filters})
        response = self.runtime.call('bedrock-agent-runtime', 'retrieve',
            knowledgeBaseId=self.settings.knowledge_base_id, retrievalQuery={'text': query.question},
            retrievalConfiguration={'vectorSearchConfiguration': {
                'numberOfResults': query.limit, 'overrideSearchType': 'SEMANTIC', 'filter': {'andAll': filters},
            }})
        hits = {}
        for result in response.get('retrievalResults', []):
            try:
                meta = result['metadata']
                doc = documents[meta['document_id']]
                if meta['document_sha256'] != doc['sha256']:
                    continue
                # Check scope again even if an upstream service ignores the filter.
                if any(meta[k] != doc[k] for k in ('ruleset_id', 'ruleset_version', 'locality', 'land_use')):
                    continue
                if any(meta[k + '_day'] != date.fromisoformat(doc[k]).toordinal() for k in ('valid_from', 'valid_to')):
                    continue
                page_number, start = meta['page'], meta['start']
                if isinstance(page_number, bool) or isinstance(start, bool):
                    continue
                if int(page_number) != page_number or int(start) != start or start < 0:
                    continue
                page_number, start = int(page_number), int(start)
                if pages and page_number not in pages:
                    continue
                page = next(p for p in doc['pages'] if p['page'] == page_number)
                quote = result['content']['text']
                expected = page['text'][start:start + 800]
                if not expected.strip() or quote != expected:
                    continue
                uri = f's3://{self.settings.evidence_bucket}/' + chunk_key(
                    self.settings.evidence_prefix, doc['document_id'], doc['sha256'], page_number, start)
                if result['location'].get('type') != 'S3' or result['location']['s3Location']['uri'] != uri:
                    continue
                score = float(result['score'])
                if not math.isfinite(score):
                    continue
                end = start + len(quote)
                identity = f"{doc['document_id']}:{doc['sha256']}:{page_number}:{start}:{end}"
                hit = EvidenceHit(id=hashlib.sha256(identity.encode()).hexdigest(),
                    source=SourceSpan(document_id=doc['document_id'], document_sha256=doc['sha256'],
                                      quote=quote, page=page_number, start=start, end=end,
                                      method=page.get('method', 'unknown')),
                    document_name=doc['name'], ruleset_id=doc['ruleset_id'], ruleset_version=doc['ruleset_version'],
                    locality=doc['locality'], land_use=doc['land_use'], valid_from=doc['valid_from'],
                    valid_to=doc['valid_to'], score=score)
                hits.setdefault(hit.id, hit)
            except (KeyError, ValueError, TypeError, AttributeError, StopIteration, OverflowError):
                continue  # Unverifiable passages never become citations.
        return list(hits.values())[:query.limit]


class S3KnowledgeBasePublisher:
    def __init__(self, settings, repository, runtime):
        self.settings, self.repository, self.runtime = settings, repository, runtime
        self.state_key = f'kb-sync:{settings.knowledge_base_id}:{settings.knowledge_base_data_source_id}'

    def status(self):
        saved = self.repository.cache_get(self.state_key)
        if not saved:
            return {'status': 'not_synced'}
        if 'job_id' not in saved:
            return saved
        response = self.runtime.call('bedrock-agent', 'get_ingestion_job',
            knowledgeBaseId=self.settings.knowledge_base_id,
            dataSourceId=self.settings.knowledge_base_data_source_id, ingestionJobId=saved['job_id'])
        job = response['ingestionJob']
        status = job['status'].lower()
        statistics = job.get('statistics', {})
        if status == 'complete' and statistics.get('numberOfDocumentsFailed', 0):
            status = 'failed'
        return dict(saved, status=status, statistics=statistics)

    def sync_ruleset(self, ruleset_id):
        try:
            with FileLock(str(self.repository.data_dir / 'kb-sync.lock'), timeout=1):
                current = self.status()
                if current['status'] in {'starting', 'in_progress', 'stopping'}:
                    raise ExtractionUnavailable('知識庫正在同步，完成後請再同步這個基準。')
                self.repository.get_rules(ruleset_id)
                sources = self.repository.list_evidence_documents(ruleset_id)
                if not sources:
                    raise ValueError('此基準尚未加入來源文件。')
                prepared = []
                for source in sources:
                    document = self.repository.get_document(source['document_id'])
                    data = Path(document['path']).read_bytes()
                    if hashlib.sha256(data).hexdigest() != source['sha256']:
                        raise ExtractionUnavailable('來源 PDF 與保存的指紋不符，停止同步。')
                    prepared.append((source, document, data))
                self.repository.cache_put(self.state_key, dict(status='publishing', ruleset_id=ruleset_id))
                for source, document, data in prepared:
                    self.put(f"{self.settings.evidence_prefix}originals/{source['document_id']}.pdf", data, 'application/pdf')
                    for page in document['pages']:
                        for start in range(0, len(page['text']), 680):
                            text = page['text'][start:start + 800]
                            if not text.strip():
                                continue
                            key = chunk_key(self.settings.evidence_prefix, source['document_id'], source['sha256'], page['page'], start)
                            metadata = {k: source[k] for k in ('locality', 'land_use')}
                            metadata.update(document_id=source['document_id'], document_sha256=source['sha256'],
                                ruleset_id=ruleset_id, ruleset_version=source['ruleset_version'],
                                valid_from_day=date.fromisoformat(source['valid_from']).toordinal(),
                                valid_to_day=date.fromisoformat(source['valid_to']).toordinal(), page=page['page'], start=start)
                            # Metadata first; the text object is the publish marker for this passage.
                            self.put(key + '.metadata.json', json.dumps({'metadataAttributes': metadata}, ensure_ascii=False).encode(), 'application/json')
                            self.put(key, text.encode(), 'text/plain; charset=utf-8')
                response = self.runtime.call('bedrock-agent', 'start_ingestion_job',
                    knowledgeBaseId=self.settings.knowledge_base_id,
                    dataSourceId=self.settings.knowledge_base_data_source_id)
                job = response['ingestionJob']
                saved = dict(job_id=job['ingestionJobId'], ruleset_id=ruleset_id)
                self.repository.cache_put(self.state_key, saved)
                return dict(saved, status=job['status'].lower())
        except Timeout:
            raise ExtractionUnavailable('另一個來源同步正在進行，請稍後再試。') from None

    def put(self, key, data, content_type):
        self.runtime.call('s3', 'put_object', Bucket=self.settings.evidence_bucket, Key=key,
                          Body=data, ContentType=content_type, ServerSideEncryption='AES256')
