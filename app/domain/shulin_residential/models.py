"""Value objects for grading. Plain dataclasses; the domain layer stays free of Pydantic here."""
from dataclasses import dataclass
from decimal import Decimal

from app.domain.shulin_residential.enums import GradeLabel
from app.domain.shulin_residential.validation import (
    require_bool,
    require_non_negative_decimal,
)

L = GradeLabel

#: Label ordering per grade-scheme size. Index 1 is always the best grade.
#: Every scheme the handbook defines is supported, including the 9-grade scheme,
#: which Shulin ordinary-residential does not currently use: its rows are 2, 3, 5
#: and 7 grades only.
GRADE_SCHEMES: dict[int, tuple[GradeLabel, ...]] = {
    2: (L.EXCELLENT, L.POOR),
    3: (L.EXCELLENT, L.NORMAL, L.POOR),
    5: (L.EXCELLENT, L.SLIGHTLY_BETTER, L.NORMAL, L.SLIGHTLY_WORSE, L.POOR),
    7: (L.EXTREMELY_EXCELLENT, L.EXCELLENT, L.SLIGHTLY_BETTER, L.NORMAL,
        L.SLIGHTLY_WORSE, L.POOR, L.EXTREMELY_POOR),
    9: (L.SUPREMELY_EXCELLENT, L.EXTREMELY_EXCELLENT, L.EXCELLENT, L.SLIGHTLY_BETTER,
        L.NORMAL, L.SLIGHTLY_WORSE, L.POOR, L.EXTREMELY_POOR, L.SUPREMELY_POOR),
}


@dataclass(frozen=True)
class GradeResult:
    """One factor's 優劣等級.

    `index` is 1-based and counts from the best grade; `count` is the size of the
    grade scheme, so the pair keeps its meaning without the caller having to
    remember which schedule row it came from. `label` must agree with
    `GRADE_SCHEMES[count][index - 1]`.
    """
    index: int
    count: int
    label: GradeLabel

    def __post_init__(self):
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count not in GRADE_SCHEMES:
            raise ValueError('等級制僅支援 ' + '、'.join(str(k) for k in sorted(GRADE_SCHEMES)) + ' 級。')
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise ValueError('等級序號必須為整數。')
        if not 1 <= self.index <= self.count:
            raise ValueError(f'等級序號 {self.index} 超出 {self.count} 級制範圍。')
        expected = GRADE_SCHEMES[self.count][self.index - 1]
        if self.label is not expected:
            raise ValueError(f'{self.count} 級制第 {self.index} 級應為「{expected.value}」。')

    @classmethod
    def of(cls, index: int, count: int) -> 'GradeResult':
        """Build a result from its position in the scheme, deriving the label."""
        if isinstance(count, bool) or not isinstance(count, int) or count not in GRADE_SCHEMES:
            raise ValueError('等級制僅支援 ' + '、'.join(str(k) for k in sorted(GRADE_SCHEMES)) + ' 級。')
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= count:
            raise ValueError(f'等級序號 {index!r} 超出 {count} 級制範圍。')
        return cls(index=index, count=count, label=GRADE_SCHEMES[count][index - 1])

    @classmethod
    def best(cls, count: int) -> 'GradeResult':
        """The best grade of a scheme."""
        return cls.of(1, count)

    @classmethod
    def worst(cls, count: int) -> 'GradeResult':
        """The worst grade of a scheme."""
        return cls.of(count, count)


@dataclass(frozen=True)
class FacilityProximity:
    """A surveyed facility's relationship to the land-price section.

    The schedule's bands read like 「區段內有大型車站或距離未滿500m」and
    「2000m以上或無」, so "absent", "inside the section" and "a measured distance"
    are three distinct states and are kept in three fields.

    The consistency rules in `__post_init__` are implementation validation, not
    schedule rules: the schedule says nothing about how a survey record should be
    encoded. They exist so that "no such facility" can never silently arrive as a
    distance of 0 m, which would grade as the best instead of the worst band for a
    公共建設 row.

    Attributes:
        exists: Whether such a facility exists for this section at all.
        in_section: Whether the facility lies inside the section (區段內有).
        distance_m: Section-centroid-to-facility distance in metres. Required
            when the facility exists and lies outside the section.
    """
    exists: bool
    in_section: bool = False
    distance_m: Decimal | float | int | None = None

    def __post_init__(self):
        # Implementation validation only; see the class docstring.
        require_bool(self.exists, '設施有無')
        require_bool(self.in_section, '是否位於區段內')
        if not self.exists:
            if self.in_section:
                raise ValueError('設施不存在時不得標記為位於區段內。')
            if self.distance_m is not None:
                raise ValueError('設施不存在時不得填距離，不得以 0 公尺代表無設施。')
            return
        if self.distance_m is not None:
            require_non_negative_decimal(self.distance_m, '設施距離')
        elif not self.in_section:
            raise ValueError('設施位於區段外時必須提供距離。')
