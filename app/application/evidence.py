"""Validate extraction drafts against the source and the selected rule version."""
import re
import unicodedata
from pydantic import ValidationError
from app.domain.models import Evidence, Factor


def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value)))


def verified_factors(raw, pages, ruleset, method):
    valid_ids = {r['id'] for r in ruleset['rules']}
    sources = {p['page']: p['text'] for p in pages}
    accepted, duplicates = {}, set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] not in valid_ids:
            continue
        page, quote = item.get('page'), item.get('quote')
        if type(page) is int and page in sources and ('line_start' in item or 'line_end' in item):
            start, end = item.get('line_start'), item.get('line_end')
            source_lines = sources[page].splitlines()
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(source_lines) or end - start > 7:
                continue
            # Copy the canonical excerpt ourselves; the model only selects source lines.
            quote = '\n'.join(source_lines[start - 1:end])
        if type(page) is not int or not isinstance(quote, str) or not quote.strip():
            continue
        item = dict(item)
        if item.get('entered_rate') is not None and not any(marker in quote for marker in ('%', '％', '修正率', '差異率', '修正百分')):
            item['entered_rate'] = None
        if all(item.get(key) is None for key in ('subject', 'comparable', 'entered_rate')):
            continue
        # Some models wrap the excerpt in quotation marks inside the JSON string.
        # Remove only a matching outer pair, then still require a source substring.
        quote = quote.strip()
        if page in sources and normalized(quote) not in normalized(sources[page]):
            for left, right in [('"', '"'), ('「', '」'), ('“', '”')]:
                if quote.startswith(left) and quote.endswith(right):
                    candidate = quote[1:-1].strip()
                    if candidate and normalized(candidate) in normalized(sources[page]):
                        quote = candidate
                        break
        if page not in sources or normalized(quote) not in normalized(sources[page]):
            continue
        # The quote must contain the claimed values, in addition to existing on the page.
        found = True
        for key in ('subject', 'comparable', 'entered_rate'):
            value = item.get(key)
            if value is None:
                continue
            needle = normalized(value).replace(',', '').removesuffix('%')
            haystack = unicodedata.normalize('NFKC', quote)
            # Keep separators between adjacent table values ("5 7" must not become "57").
            haystack = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', haystack)
            if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', needle):
                needle = format(float(needle), 'g')
                found &= re.search(r'(?<![\d.])' + re.escape(needle) + r'(?:\.0+)?(?![\d.])', haystack) is not None
            else:
                found &= bool(needle) and needle in normalized(haystack)
        if not found:
            continue
        try:
            factor = Factor(
                id=item['id'], subject=item.get('subject'), comparable=item.get('comparable'),
                entered_rate=item.get('entered_rate'), confirmed=False,
                evidence=Evidence(page=page, quote=quote, method=method),
            )
        except (ValueError, TypeError, ValidationError):
            continue
        previous = accepted.get(factor.id)
        if previous and (previous.subject, previous.comparable, previous.entered_rate) != (factor.subject, factor.comparable, factor.entered_rate):
            duplicates.add(factor.id)
        else:
            accepted[factor.id] = factor
    return [factor for key, factor in accepted.items() if key not in duplicates]
