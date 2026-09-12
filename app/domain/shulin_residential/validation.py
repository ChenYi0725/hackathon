"""Input validation shared by this ruleset. Follows the project's `ValueError` pattern.

Two numeric families are kept apart on purpose:

- `require_decimal` and friends back everything that is a price-adjustment rate or
  is compared against a published grade boundary. Per `app/domain/AGENTS.md`
  these stay in `Decimal`, so band edges are hit exactly.
- `require_number` and friends back the 表3 arithmetic in `calculations.py`,
  which returns plain floats.
"""
import math
from decimal import Decimal, InvalidOperation


def require_number(value, field: str) -> float:
    """Return `value` as float, rejecting bool, non-numeric and non-finite input."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f'{field} 必須為數值。')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{field} 必須為有限數值。')
    return result


def require_non_negative(value, field: str) -> float:
    """Return `value` as a finite float that is not negative."""
    result = require_number(value, field)
    if result < 0:
        raise ValueError(f'{field} 不得為負數。')
    return result


def require_positive(value, field: str) -> float:
    """Return `value` as a finite float greater than zero; guards division by zero."""
    result = require_number(value, field)
    if result <= 0:
        raise ValueError(f'{field} 必須大於 0。')
    return result


def require_decimal(value, field: str) -> Decimal:
    """Return `value` as a finite `Decimal`.

    `Decimal` and `int` convert exactly. `float` and `str` go through
    `Decimal(str(value))`, the same conversion `app/domain/engine.py` already
    uses, so a caller reading a matrix out of JSON still works. Matrices shipped
    in this package are built from strings and never pass through `float`.
    """
    if isinstance(value, bool):
        raise ValueError(f'{field} 必須為數值。')
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, float, str)):
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation:
            raise ValueError(f'{field} 必須為數值。') from None
    else:
        raise ValueError(f'{field} 必須為數值。')
    if not result.is_finite():
        raise ValueError(f'{field} 必須為有限數值。')
    return result


def require_non_negative_decimal(value, field: str) -> Decimal:
    """Return `value` as a finite `Decimal` that is not negative."""
    result = require_decimal(value, field)
    if result < 0:
        raise ValueError(f'{field} 不得為負數。')
    return result


def require_bool(value, field: str) -> bool:
    """Return `value` when it is a real bool; rejects truthy substitutes."""
    if not isinstance(value, bool):
        raise ValueError(f'{field} 必須為布林值。')
    return value
