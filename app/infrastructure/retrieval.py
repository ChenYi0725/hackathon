"""Local lexical baseline: exact applicability filter, then Chinese bigram BM25."""
from collections import Counter
import hashlib
import math
import re
from app.application.rag_contracts import EvidenceHit, SourceSpan


def tokens(text):
    result = []
    for part in re.findall(r'[\u3400-\u9fff]+|[a-zA-Z0-9]+', text.lower()):
        if re.fullmatch(r'[\u3400-\u9fff]+', part):
            result.extend(part[i:i + 2] for i in range(len(part) - 1))
            if len(part) == 1:
                result.append(part)
        else:
            result.append(part)
    return result


class LocalEvidenceRetriever:
    def __init__(self, repository):
        self.repository = repository

    def retrieve(self, query):
        documents = self.repository.evidence_sources(query)
        rules = self.repository.get_rules(query.ruleset_id)
        selected = [r for r in rules['rules'] if r['id'] in query.rule_ids]
        allowed_pages = {r['source_page'] for r in selected}
        terms = set(tokens(query.question))
        chunks = []
        for doc in documents:
            for page in doc['pages']:
                if allowed_pages and page['page'] not in allowed_pages:
                    continue
                text = page['text']
                for start in range(0, len(text), 680):
                    quote = text[start:start + 800]
                    counts = Counter(tokens(quote))
                    if counts:
                        chunks.append((doc, page, start, quote, counts))
        if not chunks or not terms:
            return []
        df = Counter(term for *_, counts in chunks for term in counts)
        average = sum(sum(c.values()) for *_, c in chunks) / len(chunks)
        ranked = []
        for doc, page, start, quote, counts in chunks:
            score = 0.0
            for term in terms & counts.keys():
                idf = math.log(1 + (len(chunks) - df[term] + .5) / (df[term] + .5))
                tf = counts[term]
                score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * sum(counts.values()) / average))
            if score <= 0:
                continue
            # A page rectangle is exact only when the excerpt covers the full page.
            full_page = start == 0 and len(quote) == len(page['text'])
            boxes = [line['bbox'] for line in page.get('lines', [])] if full_page else []
            bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes)) if boxes else None
            span = SourceSpan(document_id=doc['document_id'], document_sha256=doc['sha256'],
                              quote=quote, page=page['page'], start=start, end=start + len(quote),
                              bbox=bbox, page_width=page.get('width') if bbox else None,
                              page_height=page.get('height') if bbox else None,
                              method=page.get('method', 'unknown'))
            identity = f"{doc['document_id']}:{doc['sha256']}:{page['page']}:{start}:{span.end}"
            ranked.append(EvidenceHit(id=hashlib.sha256(identity.encode()).hexdigest(), source=span,
                document_name=doc['name'], ruleset_id=doc['ruleset_id'], ruleset_version=doc['ruleset_version'],
                locality=doc['locality'], land_use=doc['land_use'], valid_from=doc['valid_from'],
                valid_to=doc['valid_to'], score=round(score, 6)))
        ranked.sort(key=lambda hit: (-hit.score, hit.id))
        return ranked[:query.limit]
