"""ASGI entry point; adapters are composed in bootstrap."""
from app.interfaces.http import create_app
from app.domain.rule_validation import validate_ruleset

app = create_app()
