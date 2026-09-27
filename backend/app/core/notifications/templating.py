"""Sandboxed Jinja2 rendering of notification templates (Prompts/04 §04.6 ``templating.py``).

``SandboxedEnvironment`` (no attribute access to internals, no imports) with autoescape off (SMS/push bodies are plain
text; e-mail HTML is escaped by the e-mail adapter). Variables are validated against ``template.variables``: missing
ones render as empty strings in production and are reported by ``missing_variables`` (the preview endpoint shows
them); unknown keys in the context are ignored.
"""

from typing import Any

from jinja2 import TemplateSyntaxError, meta
from jinja2.sandbox import SandboxedEnvironment

_env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


def render(template: str | None, context: dict[str, Any]) -> str:
    if not template:
        return ""
    return _env.from_string(template).render(**context).strip()


def referenced_variables(template: str | None) -> set[str]:
    if not template:
        return set()
    return set(meta.find_undeclared_variables(_env.parse(template)))


def validate(template: str) -> str | None:
    """Syntax check for template editors — the error message, or ``None`` when the template compiles."""
    try:
        _env.parse(template)
    except TemplateSyntaxError as exc:
        return f"line {exc.lineno}: {exc.message}"
    return None


def missing_variables(declared: list[str] | None, context: dict[str, Any], *templates: str | None) -> list[str]:
    needed = set(declared or [])
    for t in templates:
        needed |= referenced_variables(t)
    return sorted(v for v in needed if v not in context)
