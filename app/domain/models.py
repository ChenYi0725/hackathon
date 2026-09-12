from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Evidence(StrictModel):
    page: int = Field(ge=1, le=200, default=3)
    quote: str = Field(default='', max_length=3000)
    method: str = 'manual'
    document_id: str | None = None
    sheet: str | None = None
    cell: str | None = None
    sha256: str | None = None
    formula: str | None = None


class Factor(StrictModel):
    id: str
    subject: str | None = None
    comparable: str | None = None
    entered_rate: float | None = Field(default=None, ge=-1000, le=1000)
    subject_grade: str | None = None
    comparable_grade: str | None = None
    confirmed: bool = False
    exempt: bool = False
    note: str = Field(default='', max_length=3000)
    evidence: Evidence = Field(default_factory=Evidence)


class Totals(StrictModel):
    regional_detail: float | None = None
    regional_carried: float | None = None
    individual: float | None = None
    absolute: float | None = None
    time_rate: float | None = None
    normal_price: float | None = Field(default=None, ge=0)
    adjusted_price: float | None = Field(default=None, ge=0)
    trial_price: float | None = Field(default=None, ge=0)
    weight: float | None = Field(default=None, ge=0, le=100)


class Comparison(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    name: str = Field(default='', max_length=200)
    section: str = Field(default='', max_length=200)
    factors: list[Factor] = Field(default_factory=list, max_length=100)
    totals: Totals = Field(default_factory=Totals)
    totals_confirmed: bool = False


class Case(StrictModel):
    id: str = ''
    revision: int = 0
    title: str = Field(min_length=1,max_length=150)
    case_number: str = Field(default='',max_length=100)
    valuation_date: str = Field(default='',max_length=40)
    subject_name: str = Field(default='',max_length=200)
    comparable_name: str = Field(default='',max_length=200)
    subject_section: str = ''
    comparable_section: str = ''
    locality: str = '新北市金山區'
    land_use: str = '商業用地'
    ruleset_id: str = 'jinshan-commercial-v1'
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    field_sources: dict[str, Evidence] = Field(default_factory=dict)
    additional_comparisons: list[Comparison] = Field(default_factory=list, max_length=2)
    demo: bool = False
    source_kind: str = 'manual'
    factors: list[Factor] = Field(default_factory=list,max_length=100)
    totals: Totals = Field(default_factory=Totals)
    totals_confirmed: bool = False
    notes: str = Field(default='',max_length=12000)
    change_reason: str = Field(default='', max_length=3000)
    extraction_warnings: list[str] = Field(default_factory=list,max_length=100)
