"""Field-level PII masking — docs/Authorization_and_Visibility.md §1; Prompts/02 §02.6 ``core/authz/masking.py``.

Masking happens in the schema layer, never in the DB. Response schemas annotate sensitive fields with one of the
``Masked*`` annotated types below and the service calls ``mask_pii(obj, principal, module)``:

* ``MaskedPhone`` keeps the last 4 digits (``******7890``);
* ``MaskedEmail`` keeps the first 2 characters (``hr*******@demo-uni.edu``);
* ``MaskedSecret`` hides everything (``salary``, ``bank_details``);
* ``MaskedStr`` / ``Masked`` (generic, last 4 kept) for ``aadhaar``, ``pan`` and similar identifiers.

The prompt writes this as ``Masked[str]``; the concrete aliases are the mypy-friendly spelling of the same idea (an
``Annotated`` type carrying ``json_schema_extra={"pii": <kind>}``), so ``pii_fields()`` — and Phase 43's
``check_pii_masking.py`` — can find every masked field from the schema alone. Unmasking needs ``<module>:view_pii``
for one of the modules named by the caller (``users`` records also honour ``hr:view_pii``).
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field

MASK_KEEP_LAST = 4
PII_EXTRA_KEY = "pii"


def _pii(kind: str) -> Any:
    return Field(default=None, json_schema_extra={PII_EXTRA_KEY: kind})


MaskedStr = Annotated[str, Field(json_schema_extra={PII_EXTRA_KEY: "generic"})]
Masked = Annotated[str | None, _pii("generic")]
MaskedPhone = Annotated[str | None, _pii("phone")]
MaskedEmail = Annotated[str | None, _pii("email")]
MaskedSecret = Annotated[str | None, _pii("secret")]
MaskedAmount = Annotated[int | None, _pii("secret")]


def mask_value(value: Any, kind: str = "generic") -> Any:
    if value is None:
        return None
    s = str(value)
    if kind == "secret":
        return "********"
    if kind == "email":
        local, _, domain = s.partition("@")
        if not domain:
            return "**"
        keep = local[:2]
        return f"{keep}{'*' * max(len(local) - len(keep), 3)}@{domain}"
    # phone / generic: keep the last 4 characters
    if len(s) <= MASK_KEEP_LAST:
        return "*" * len(s)
    return "*" * (len(s) - MASK_KEEP_LAST) + s[-MASK_KEEP_LAST:]


def pii_fields(schema: type[BaseModel]) -> dict[str, str]:
    """``{field: kind}`` for fields declared through one of the ``Masked*`` annotated types."""
    out: dict[str, str] = {}
    for name, f in schema.model_fields.items():
        extra = f.json_schema_extra
        if isinstance(extra, dict) and extra.get(PII_EXTRA_KEY):
            kind = extra[PII_EXTRA_KEY]
            out[name] = kind if isinstance(kind, str) else "generic"
    return out


def may_unmask(principal: Any, modules: str | tuple[str, ...]) -> bool:
    if principal is None:
        return False
    mods = (modules,) if isinstance(modules, str) else modules
    return any(principal.has(m, "view_pii") for m in mods)


def mask_pii(obj: Any, principal: Any, module: str | tuple[str, ...]) -> Any:
    """Return a copy of ``obj`` with PII fields masked unless the principal holds ``<module>:view_pii``."""
    if may_unmask(principal, module):
        return obj
    fields = pii_fields(type(obj))
    if not fields:
        return obj
    return obj.model_copy(update={name: mask_value(getattr(obj, name), kind) for name, kind in fields.items()})


def mask_all(objs: list[Any], principal: Any, module: str | tuple[str, ...]) -> list[Any]:
    return [mask_pii(o, principal, module) for o in objs]
