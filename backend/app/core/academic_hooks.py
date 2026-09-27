"""Pluggable hooks of the academic session lifecycle — Prompts/03 §03.6 ``academic_session_service`` rules 3–4.

* ``TermCloseCheck`` registry: a term may move to ``closed`` only when every registered check passes. Phase 09
  registers "all offerings completed/cancelled", Phase 15 "results published"; Phase 03 ships the registry empty, so
  the status stepper shows no blockers until those modules exist.
* ``on_rollover`` hooks: ``POST /academic-years/rollover`` with ``promote_batches=true`` calls every hook (Phase 05
  batches / Phase 07 students register one) and reports ``{hook: promoted_count}``.

Hooks are plain async callables so ``app/core`` stays free of service imports (import-linter layers).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CloseCheckResult:
    key: str
    label: str
    passed: bool
    detail: str | None = None


CloseCheck = Callable[[Any, Any], Awaitable[CloseCheckResult]]  # (db, term) -> result
RolloverHook = Callable[[Any, Any, Any, Any], Awaitable[int]]  # (db, principal, previous_year, new_year) -> count

TERM_CLOSE_CHECKS: dict[str, CloseCheck] = {}
ROLLOVER_HOOKS: dict[str, RolloverHook] = {}


def register_term_close_check(key: str, check: CloseCheck) -> None:
    TERM_CLOSE_CHECKS[key] = check


def register_rollover_hook(key: str, hook: RolloverHook) -> None:
    ROLLOVER_HOOKS[key] = hook
