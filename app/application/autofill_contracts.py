"""Validated inputs and ports for source-backed field completion."""
from decimal import Decimal
from typing import Annotated, Protocol
from pydantic import Field, StrictBool, StrictInt, field_validator
from app.domain.models import StrictModel

Number = Annotated[Decimal, Field(max_digits=24, decimal_places=8)]


class SurveyMeasurements(StrictModel):
    opened_road_widths_m: list[Number] | None = Field(default=None, max_length=100)
    built_land_area_m2: Number | None = None
    section_total_area_m2: Number | None = None
    coordinates_m: tuple[Number, Number, Number, Number] | None = None
    source: str = Field(default='', max_length=500)

    @field_validator('*', mode='before')
    @classmethod
    def no_booleans(cls, value):
        if any(isinstance(v, bool) for v in (value if isinstance(value, (list, tuple)) else [value])):
            raise ValueError('量測值不可為布林值。')
        return value


class AutofillRequest(StrictModel):
    revision: StrictInt = Field(ge=0)
    school_year: StrictInt | None = Field(default=None, ge=103, le=200)
    query_public_data: StrictBool = True
    subject: SurveyMeasurements = Field(default_factory=SurveyMeasurements)
    comparable: SurveyMeasurements = Field(default_factory=SurveyMeasurements)


class AutofillApply(StrictModel):
    revision: StrictInt = Field(ge=0)
    token: str = Field(pattern=r'^[a-f0-9]{32}$')


class FieldDataSource(Protocol):
    def catalog(self) -> list[dict]: ...
    def lookup(self, locality: str, source_keys: list[str], school_year: int | None) -> dict: ...


class AutofillDraftStore(Protocol):
    def put(self, token: str, data: dict) -> None: ...
    def get(self, token: str) -> dict | None: ...
