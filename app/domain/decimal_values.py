"""Exact numeric conversion shared by generic valuation calculations.

The generic domain API deliberately rejects ``float`` inputs.  A binary float
cannot be proven to preserve a published decimal boundary or matrix cell; JSON
rulesets should therefore be decoded with ``parse_float=Decimal`` or carry
decimal values as strings.
"""

from decimal import Decimal, InvalidOperation
from typing import Any


def as_finite_decimal(value: Any, field: str) -> Decimal:
    """Return an exact finite ``Decimal`` from a Decimal, integer, or string.

    ``bool`` is rejected even though it is an ``int`` subclass.  ``float`` is
    also rejected instead of silently inheriting its binary approximation.
    No quantizing or rounding is performed.
    """

    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f'{field} 必須使用 Decimal、整數或十進位字串。')
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            text = str(value).strip()
            if not text:
                raise InvalidOperation
            result = Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValueError(f'{field} 必須為有效十進位數值。') from None
    else:
        raise ValueError(f'{field} 必須使用 Decimal、整數或十進位字串。')
    if not result.is_finite():
        raise ValueError(f'{field} 必須為有限數值。')
    return result
