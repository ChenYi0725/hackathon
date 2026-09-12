"""Additive v1 RAG DTOs; no vendor SDK types cross application ports."""
from datetime import date
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)


class EvidenceQuery(Contract):
    question: str = Field(min_length=1, max_length=1000)
    ruleset_id: str
    ruleset_version: str
    locality: str
    land_use: str
    valuation_date: date
    rule_ids: tuple[str, ...] = ()
    limit: int = Field(default=5, ge=1, le=8)


class SourceSpan(Contract):
    document_id: str
    document_sha256: str
    quote: str
    page: int
    start: int
    end: int
    bbox: tuple[float, float, float, float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    method: str


class EvidenceHit(Contract):
    id: str
    source: SourceSpan
    document_name: str
    ruleset_id: str
    ruleset_version: str
    locality: str
    land_use: str
    valid_from: date
    valid_to: date
    score: float


class AnswerStatement(Contract):
    text: str = Field(min_length=1, max_length=1500)
    citation_ids: tuple[str, ...] = Field(min_length=1, max_length=8)


class AnswerDraft(Contract):
    statements: tuple[AnswerStatement, ...] = Field(default=(), max_length=8)
    insufficient_evidence: bool = False
