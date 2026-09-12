"""Legacy script helpers. Web uploads always use the injected PaddlePdfReader."""
from app.application.drafts import parse_case as _parse_case
from app.domain.rules import default_rules
from app.infrastructure.text_pdf import read_pdf


def parse_case(pages, title, ruleset=None):
    return _parse_case(pages, title, ruleset or default_rules())
