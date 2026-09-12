"""v1 export artifacts: no persistence changes and no renderer dependencies."""
from dataclasses import dataclass
from typing import Protocol
from app.domain.models import Case


class ExportUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportArtifact:
    data: bytes
    filename: str
    media_type: str
    revision: int


class FormRenderer(Protocol):
    def render(self, case: Case, result: dict, rules: dict,
               kind: str, generated_at: str) -> ExportArtifact: ...
