"""Application-owned result contract for OCR ruleset extraction."""

from dataclasses import dataclass
from typing import Any

from app.domain.ruleset_models import StructuredRuleset


@dataclass(frozen=True)
class RulesetExtractionResult:
    """OCR-derived rulesets are drafts until a human confirms source wording."""

    rulesets: tuple[StructuredRuleset, ...]
    warnings: tuple[str, ...]
    requires_confirmation: bool = True

    def __post_init__(self) -> None:
        if not self.rulesets:
            raise ValueError('OCR 未產生任何 structured ruleset。')
        if self.requires_confirmation is not True:
            raise ValueError('OCR ruleset 草稿必須經人工確認。')

    def to_dict(self) -> dict[str, Any]:
        return {
            'rulesets': [ruleset.to_dict() for ruleset in self.rulesets],
            'warnings': list(self.warnings),
            'requires_confirmation': self.requires_confirmation,
        }
