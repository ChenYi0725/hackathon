"""Read-only public data contracts, separate from case-bound valuation evidence."""
from typing import Literal, Protocol
from pydantic import Field, StrictInt
from app.application.rag_contracts import Contract


class DatasetSearch(Contract):
    keyword: str = Field(min_length=1, max_length=100)
    unit: Literal['1110000', '1130000', '1050000', '1060000', '1070000',
                  '1090000', '1220000', '1240000', '1280000', '1040000'] = '1110000'


class DatasetRead(Contract):
    dataset_id: str = Field(pattern=r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')
    page: StrictInt = Field(default=0, ge=0, le=10000)
    size: StrictInt = Field(default=5, ge=1, le=10)


class OpenDataUnavailable(RuntimeError):
    """Public data unavailable; never interpret an outage as an empty dataset."""


class OpenDataProvider(Protocol):
    def search(self, query: DatasetSearch) -> dict: ...
    def read(self, query: DatasetRead) -> dict: ...
