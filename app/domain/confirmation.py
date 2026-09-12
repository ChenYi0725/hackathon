"""Confirmation applies to persisted content, not merely to a factor ID."""
from app.domain.models import Case


CONFIRMATION_CONTEXT = (
    'ruleset_id', 'document_id', 'locality', 'land_use', 'valuation_date',
    'subject_name', 'comparable_name', 'subject_section', 'comparable_section',
    'document_ids', 'field_sources',
)


def invalidate_confirmations(previous: Case | None, proposed: Case) -> Case:
    """Copy the proposal and clear confirmations affected by substantive changes.

    A changed value must be saved before a subsequent request can confirm it.
    Unchanged content can be explicitly confirmed or unconfirmed by the caller.
    """
    saved = proposed.model_copy(deep=True)
    context_changed = previous is None or any(
        getattr(previous, field) != getattr(saved, field) for field in CONFIRMATION_CONTEXT
    )
    old_factors = {factor.id: factor for factor in previous.factors} if previous else {}
    factors_changed = old_factors.keys() != {factor.id for factor in saved.factors}
    for factor in saved.factors:
        old = old_factors.get(factor.id)
        changed = old is None or old.model_dump(exclude={'confirmed'}) != factor.model_dump(exclude={'confirmed'})
        factors_changed |= changed
        if context_changed or changed:
            factor.confirmed = False
    if context_changed or factors_changed or previous.totals != saved.totals:
        saved.totals_confirmed = False
    old_comparisons = {c.id: c for c in previous.additional_comparisons} if previous else {}
    for comparison in saved.additional_comparisons:
        old = old_comparisons.get(comparison.id)
        changed_context = context_changed or old is None or (old.name, old.section) != (comparison.name, comparison.section)
        old_rows = {f.id: f for f in old.factors} if old else {}
        changed_rows = old_rows.keys() != {f.id for f in comparison.factors}
        for factor in comparison.factors:
            before = old_rows.get(factor.id)
            changed = before is None or before.model_dump(exclude={'confirmed'}) != factor.model_dump(exclude={'confirmed'})
            changed_rows |= changed
            if changed_context or changed:
                factor.confirmed = False
        if changed_context or changed_rows or old.totals != comparison.totals:
            comparison.totals_confirmed = False
    return saved
