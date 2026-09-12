"""Vendor-independent tool turns and validated, bounded function inputs."""
from typing import Literal
from pydantic import Field, StrictInt
from app.application.rag_contracts import Contract, AnswerDraft
from app.application.open_data import DatasetSearch, DatasetRead


class SearchInput(Contract):
    question: str = Field(min_length=1, max_length=1000)


class ReadInput(Contract):
    citation_id: str = Field(min_length=1, max_length=64)
    start: StrictInt = Field(default=0, ge=0)


class RuleInput(Contract):
    rule_id: str = Field(min_length=1, max_length=200)


class EmptyInput(Contract):
    pass


class ToolCall(Contract):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict


class AgentTurn(Contract):
    calls: tuple[ToolCall, ...] = Field(default=(), max_length=3)
    answer: AnswerDraft | None = None
    # Opaque adapter-owned message preserves signatures/reasoning blocks across turns.
    continuation: dict = Field(default_factory=dict)


class ToolResult(Contract):
    id: str
    status: Literal['success', 'error']
    data: dict


TOOL_INPUTS = {'search_evidence': SearchInput, 'read_source_page': ReadInput,
               'get_rule': RuleInput, 'review_case': EmptyInput,
               'search_public_datasets': DatasetSearch, 'read_public_dataset': DatasetRead}
TOOL_DESCRIPTIONS = {
    'search_public_datasets': 'Find NTPC official dataset metadata by short keywords separated by spaces (all must match). Units: 1110000 land, 1130000 transport, 1050000 education, 1060000 construction, 1070000 water, 1090000 urban planning, 1220000 environment, 1240000 health, 1280000 metro, 1040000 tourism. Default land. Narrow keywords if truncated. Metadata is not a factual citation.',
    'read_public_dataset': 'Read one JSON page of an official dataset discovered in this query. Returns citation id, records, exact source URL and retrieval time. Start page 0; follow next_page within budget. No server-side record filtering. A page is not the entire dataset; current data is not historical evidence. Never infer zero or absence from missing records. Reduce size if response too large.',
    'search_evidence': 'Search uploaded applicable rules documents; you may reformulate the question and search again. Returns citation IDs.',
    'read_source_page': 'Read up to 2000 characters from a previously retrieved citation page; start is a character offset. Returns an exact citation.',
    'get_rule': 'Inspect one configured factor in the case-bound ruleset. Does not certify the rule or compute values.',
    'review_case': 'Run the existing deterministic valuation review on the saved case. Use this for arithmetic; never calculate yourself.',
}


def tool_catalog(public_data=False):
    return [dict(name=name, description=TOOL_DESCRIPTIONS[name], input_schema=model.model_json_schema())
            for name, model in TOOL_INPUTS.items() if public_data or name not in {'search_public_datasets', 'read_public_dataset'}]
