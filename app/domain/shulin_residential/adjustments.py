"""Grade pair to price-adjustment-rate lookup.

Kept separate from grading so that deriving a grade and pricing a grade
difference stay independently testable. Rates are `Decimal`, per
`app/domain/AGENTS.md`.
"""
from collections.abc import Sequence
from decimal import Decimal

from app.domain.shulin_residential.models import GradeResult
from app.domain.shulin_residential.validation import require_decimal


def calculate_adjustment_rate(
    target_grade: GradeResult,
    benchmark_grade: GradeResult,
    matrix: Sequence[Sequence[Decimal]],
) -> Decimal:
    """Look up the price-adjustment rate for a target/benchmark grade pair.

    Row is 目標區段, column is 基準區段, matching the schedule's own headings and
    `app/domain/rules.py`. The cell is returned exactly as the schedule prints
    it: no arithmetic, no rounding, no clamping.

    Args:
        target_grade: The target section's grade.
        benchmark_grade: The benchmark section's grade.
        matrix: A square matrix sized to the grade scheme, in percentage points.
            Cells should already be `Decimal`; `int`, `float` and `str` are
            accepted and converted the way `app/domain/engine.py` converts stored
            values.

    Returns:
        The adjustment rate in percentage points as a `Decimal`. Positive means
        the target section is better than the benchmark under this matrix.

    Raises:
        ValueError: If either grade is not a `GradeResult`, the two grades use
            different scheme sizes, the matrix is not square and sized to that
            scheme, or any matrix cell is non-numeric or non-finite.
    """
    for name, grade in (('目標區段等級', target_grade), ('基準區段等級', benchmark_grade)):
        if not isinstance(grade, GradeResult):
            raise ValueError(f'{name} 必須為 GradeResult。')
    if target_grade.count != benchmark_grade.count:
        raise ValueError(
            f'目標區段為 {target_grade.count} 級制、基準區段為 {benchmark_grade.count} 級制，無法比較。')
    count = target_grade.count
    rows = list(matrix)
    if len(rows) != count:
        raise ValueError(f'修正率矩陣需有 {count} 列，實際為 {len(rows)} 列。')
    cells: list[list[Decimal]] = []
    for i, row in enumerate(rows):
        if isinstance(row, (str, bytes)):
            raise ValueError(f'修正率矩陣第 {i + 1} 列格式錯誤。')
        values = list(row)
        if len(values) != count:
            raise ValueError(f'修正率矩陣第 {i + 1} 列需有 {count} 欄，實際為 {len(values)} 欄。')
        cells.append([require_decimal(v, f'修正率矩陣[{i + 1}][{j + 1}]') for j, v in enumerate(values)])
    # GradeResult already guarantees 1 <= index <= count, so this cannot go out of range.
    return cells[target_grade.index - 1][benchmark_grade.index - 1]
