"""Field-level PII masking — docs/Authorization_and_Visibility.md §1 (masking happens in the schema layer, never in the DB)."""

from typing import Any

from pydantic import BaseModel

MASK_KEEP_LAST = 4


def mask_value(value: Any) -> Any:
    if value is None:
        return None
    s = str(value)
    if len(s) <= MASK_KEEP_LAST:
        return "X" * len(s)
    return "X" * (len(s) - MASK_KEEP_LAST) + "-" + s[-MASK_KEEP_LAST:]


def pii_fields(schema: type[BaseModel]) -> set[str]:
    """Fields declared with ``Field(json_schema_extra={"pii": True})``."""
    out: set[str] = set()
    for name, f in schema.model_fields.items():
        extra = f.json_schema_extra
        if isinstance(extra, dict) and extra.get("pii"):
            out.add(name)
    return out


def mask_pii(obj: BaseModel, principal: Any, module: str) -> BaseModel:
    """Return a copy of ``obj`` with PII fields masked unless the principal holds ``<module>:view_pii``."""
    if principal is not None and principal.has(module, "view_pii"):
        return obj
    fields = pii_fields(type(obj))
    if not fields:
        return obj
    return obj.model_copy(update={name: mask_value(getattr(obj, name)) for name in fields})
