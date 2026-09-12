import json
from dataclasses import replace
import pytest
from botocore.exceptions import ClientError
from app.application.ports import ExtractionUnavailable
from app.domain.rules import default_rules
from app.infrastructure.bedrock import BedrockFieldExtractor, RequestGate
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.settings import Settings

PAGES = [{'page': 1, 'text': '寬度 5 7\n面前道路寬度 18 6'}]
WIDTH = {'id': 'width', 'subject': '5', 'comparable': '7', 'entered_rate': None, 'page': 1, 'quote': '寬度 5 7'}


class Client:
    def __init__(self, factors=None, failures=0, stop='end_turn'):
        self.factors = factors if factors is not None else [WIDTH]
        self.failures, self.stop, self.calls = failures, stop, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise ClientError({'Error': {'Code': 'ThrottlingException', 'Message': 'sensitive upstream response'}}, 'Converse')
        return {'output': {'message': {'content': [{'text': '```json\n' + json.dumps({'factors': self.factors}) + '\n```'}]}},
                'stopReason': self.stop, 'usage': {'inputTokens': 10, 'outputTokens': 20}}


@pytest.fixture
def repository(tmp_path):
    repo = SQLiteReviewRepository(tmp_path)
    repo.initialize()
    return repo


def extractor(repository, client, **settings):
    return BedrockFieldExtractor(Settings(data_dir=repository.data_dir, **settings), repository, client=client)


def test_uses_selected_ruleset_caches_and_never_confirms(repository):
    rules = default_rules()
    rules['rules'] = [dict(rules['rules'][1], id='custom-width')]
    client = Client([dict(WIDTH, id='custom-width')])
    ai = extractor(repository, client)
    first = ai.extract(PAGES, rules)
    second = ai.extract(PAGES, rules)
    assert first == second and len(client.calls) == 1
    assert first[0].id == 'custom-width' and first[0].confirmed is False
    assert first[0].evidence.method.startswith('bedrock:')
    prompt = client.calls[0]['messages'][0]['content'][0]['text']
    assert 'custom-width' in prompt and '"id": "area"' not in prompt


def test_invalid_citations_unknown_ids_and_unquoted_values_are_rejected(repository):
    invalid = [dict(WIDTH, id='made-up'), dict(WIDTH, id=['width']), dict(WIDTH, quote='不存在'), dict(WIDTH, subject='500'), dict(WIDTH, page=2)]
    ai = extractor(repository, Client(invalid))
    with pytest.raises(ExtractionUnavailable, match='有效原文引用'):
        ai.extract(PAGES, default_rules())


def test_conflicting_values_for_same_factor_are_not_silently_selected(repository):
    pages = [{'page': 1, 'text': '寬度 5 7\n寬度 8 9'}]
    ai = extractor(repository, Client([WIDTH, dict(WIDTH, subject='8', comparable='9', quote='寬度 8 9')]))
    with pytest.raises(ExtractionUnavailable):
        ai.extract(pages, default_rules())


def test_quoted_excerpt_is_normalized_but_still_verified(repository):
    ai = extractor(repository, Client([dict(WIDTH, quote='"寬度 5 7"')]))
    assert ai.extract(PAGES, default_rules())[0].evidence.quote == '寬度 5 7'


def test_line_references_copy_the_canonical_source(repository):
    raw = {key: value for key, value in WIDTH.items() if key != 'quote'}
    ai = extractor(repository, Client([dict(raw, line_start=1, line_end=1)]))
    assert ai.extract(PAGES, default_rules())[0].evidence.quote == '寬度 5 7'


def test_invalid_line_references_and_empty_drafts_are_rejected(repository):
    invalid = [dict(WIDTH, line_start=10, line_end=10), dict(WIDTH, subject=None, comparable=None)]
    with pytest.raises(ExtractionUnavailable):
        extractor(repository, Client(invalid)).extract(PAGES, default_rules())


def test_distance_cannot_be_relabelled_as_a_percentage(repository):
    raw = dict(WIDTH, subject=None, comparable=None, entered_rate=5)
    with pytest.raises(ExtractionUnavailable):
        extractor(repository, Client([raw])).extract(PAGES, default_rules())


def test_retry_attempts_all_use_shared_gate(repository):
    clock = [100.0]
    def sleep(seconds): clock[0] += seconds
    client = Client(failures=2)
    ai = extractor(repository, client)
    ai.sleep = sleep
    ai.gate = RequestGate(repository, clock=lambda: clock[0], sleep=sleep)
    calls = []
    original = client.converse
    def converse(**kwargs):
        calls.append(clock[0])
        return original(**kwargs)
    client.converse = converse
    assert ai.extract(PAGES, default_rules())
    assert len(calls) == 3
    assert all(b - a >= 1.0999 for a, b in zip(calls, calls[1:]))
    other = RequestGate(repository, clock=lambda: clock[0], sleep=sleep)
    other.wait()
    assert clock[0] - calls[-1] >= 1.0999


def test_truncated_output_never_becomes_a_draft(repository):
    with pytest.raises(ExtractionUnavailable, match='未完整'):
        extractor(repository, Client(stop='max_tokens')).extract(PAGES, default_rules())


def test_disabled_model_and_empty_document_make_no_cloud_calls(repository):
    client = Client()
    with pytest.raises(ExtractionUnavailable):
        extractor(repository, client, ai_enabled=False).extract(PAGES, default_rules())
    with pytest.raises(ValueError):
        extractor(repository, client).extract([{'page': 1, 'text': ''}], default_rules())
    assert client.calls == []


def test_bad_credentials_return_safe_message(repository):
    client = Client()
    def fail(**kwargs):
        raise ClientError({'Error': {'Code': 'ExpiredTokenException', 'Message': 'sensitive upstream response'}}, 'Converse')
    client.converse = fail
    with pytest.raises(ExtractionUnavailable) as result:
        extractor(repository, client).extract(PAGES, default_rules())
    assert '過期' in str(result.value)
    assert 'sensitive' not in str(result.value)


@pytest.mark.parametrize('kwargs', [{'region': 'ap-northeast-1'}, {'min_interval': .5}, {'model_id': 'global.some-model'}, {'model_id': 'us.some-model'}])
def test_competition_configuration_rejects_unsupported_regions_and_bursts(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
