"""Normalize only explicitly supported dates; never infer applicability."""
import re
from datetime import date


def valuation_day(value: str) -> date:
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    if re.fullmatch(r'\d{7}', value):
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
    raise ValueError('請填寫估價日期：西元 YYYY-MM-DD 或民國 YYYMMDD。')


def require_ruleset_scope(case, ruleset):
    if case.locality != ruleset['locality'] or case.land_use != ruleset['land_use']:
        raise ValueError('案件地區或用地類別與指定基準不符，請先核對適用性。')
