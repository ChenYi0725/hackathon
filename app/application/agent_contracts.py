"""Vendor-independent tool turns and validated, bounded function inputs."""
from typing import Annotated, Literal
from decimal import Decimal
from pydantic import Field, StrictInt, field_validator
from app.application.rag_contracts import Contract, AnswerDraft


class SearchInput(Contract):
    question: str = Field(min_length=1, max_length=1000)


class ReadInput(Contract):
    citation_id: str = Field(min_length=1, max_length=64)
    start: StrictInt = Field(default=0, ge=0)


class RuleInput(Contract):
    rule_id: str = Field(min_length=1, max_length=200)


class EmptyInput(Contract):
    pass


MeasurementValue = Annotated[Decimal, Field(max_digits=24, decimal_places=8)]


class Measurements(Contract):
    """User-supplied observations, never model-generated numeric arguments."""
    opened_road_widths_m: list[MeasurementValue] | None = Field(default=None, max_length=100)
    built_land_area_m2: MeasurementValue | None = None
    section_total_area_m2: MeasurementValue | None = None
    coordinates_m: tuple[MeasurementValue, MeasurementValue, MeasurementValue, MeasurementValue] | None = None

    @field_validator('*', mode='before')
    @classmethod
    def reject_booleans(cls, value):
        values = value if isinstance(value, (tuple, list)) else [value]
        if any(isinstance(v, bool) for v in values):
            raise ValueError('量測值不可為布林值。')
        return value


class CaseMeasurements(Contract):
    subject: Measurements = Field(default_factory=Measurements)
    comparable: Measurements = Field(default_factory=Measurements)


class PublicDataInput(Contract):
    source_key: str = Field(min_length=1, max_length=100)
    school_year: StrictInt | None = Field(default=None, ge=103, le=200)


class MeasurementInput(Contract):
    method: Literal['average_road_width', 'building_density', 'straight_line_distance']
    side: Literal['subject', 'comparable']
    citation_id: str = Field(min_length=1, max_length=64)


class ToolCall(Contract):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict


class AgentTurn(Contract):
    calls: tuple[ToolCall, ...] = Field(default=(), max_length=8)
    answer: AnswerDraft | None = None
    # Opaque adapter-owned message preserves signatures/reasoning blocks across turns.
    continuation: dict = Field(default_factory=dict)


class ToolResult(Contract):
    id: str
    status: Literal['success', 'error']
    data: dict


TOOL_INPUTS = {'search_evidence': SearchInput, 'read_source_page': ReadInput,
               'get_rule': RuleInput, 'review_case': EmptyInput,
               'inspect_case': EmptyInput, 'list_data_sources': EmptyInput,
               'query_public_data': PublicDataInput, 'calculate_factor': RuleInput,
               'calculate_measurement': MeasurementInput}
TOOL_DESCRIPTIONS = {
    'search_evidence': 'Search uploaded applicable rules documents; you may reformulate the question and search again. Returns citation IDs.',
    'read_source_page': 'Read up to 2000 characters from a previously retrieved citation page; start is a character offset. Returns an exact citation.',
    'get_rule': 'Inspect one configured factor. rule_id must exactly equal a factors[].id (for example width), without a ruleset prefix. This returns configuration, NOT a document citation.',
    'review_case': 'Run the existing deterministic valuation review on the saved case. Use this for arithmetic; never calculate yourself.',
    'inspect_case': 'Inspect saved inputs, missing fields, confirmation state and user-supplied measurements. Does not change the case.',
    'list_data_sources': 'List registered government API source keys and fields requiring survey. Select a source key before query_public_data.',
    'query_public_data': 'Query ONE registered government dataset in the case district. Returns bounded facility candidates, API citations and gaps, not confirmed case values. Education sources require an explicit school_year.',
    'calculate_factor': 'Run the existing deterministic engine for one exact configured rule_id on saved case inputs. Returns its grade/rate/check, or missing/pending. Does not invent or accept a formula.',
    'calculate_measurement': 'Choose an existing arithmetic function using an applicable document citation. Reads only user-supplied measurements for the selected side; returns exact inputs/result/unit or missing fields. Coordinates must already be on the same metre plane; no lat/lon or route-distance substitution. Preview only.',
}


def tool_catalog(rule_ids=None):
    catalog = [dict(name=name, description=TOOL_DESCRIPTIONS[name], input_schema=model.model_json_schema())
            for name, model in TOOL_INPUTS.items()]
    if rule_ids is not None:
        rule_tool = next(tool for tool in catalog if tool["name"] == "get_rule")
        rule_tool["input_schema"]["properties"]["rule_id"]["enum"] = list(rule_ids)
        next(t for t in catalog if t['name'] == 'calculate_factor')['input_schema']['properties']['rule_id']['enum'] = list(rule_ids)
    return catalog
