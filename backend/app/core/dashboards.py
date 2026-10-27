"""Dashboard registry — Prompts/35 §35.3 / §35.6 (``dashboard_service``).

``register_dashboard(role_slug, widgets=[WidgetSpec(...)])`` declares the default composition of a role's dashboard.
A widget points at exactly one of:

* ``chart_key`` — a chart of :data:`app.core.charts.CHART_REGISTRY` (rendered with its table twin);
* ``stat_key`` — a headline number of :data:`STAT_KEYS` (a ``mv_kpi_daily`` column at institution / college scope, the
  ``scoped_chart`` number chart under narrower scopes);
* ``list_key`` — a fixed-filter list of :data:`LIST_KEYS` (approvals inbox, today's receipts, open discrepancies …);
* ``action_key`` — a quick action of :data:`ACTION_KEYS` (route + permission).

Platform defaults are the registered compositions; ``platform_settings['dashboards.defaults']`` may override them per role,
an institution's ``dashboards.layout.<role>`` (layout editor) overrides those, and user pins / hidden keys apply last.
Widgets whose permission or feature fails are dropped at render time.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "ACTION_KEYS",
    "DASHBOARD_REGISTRY",
    "LIST_KEYS",
    "STAT_KEYS",
    "ActionDef",
    "ListDef",
    "StatDef",
    "WidgetSpec",
    "register_dashboard",
]

SIZES = ("sm", "md", "lg", "xl")


@dataclass(frozen=True)
class WidgetSpec:
    key: str
    chart_key: str | None = None
    stat_key: str | None = None
    list_key: str | None = None
    action_key: str | None = None
    size: str = "md"
    permission: tuple[str, ...] = ()  # any of; empty → the target's own permission
    feature: str | None = None
    default_scope: str | None = None
    title: str | None = None

    @property
    def kind(self) -> str:
        if self.chart_key:
            return "chart"
        if self.stat_key:
            return "stat"
        if self.list_key:
            return "list"
        return "action"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["permission"] = list(self.permission)
        d["kind"] = self.kind
        return d


@dataclass(frozen=True)
class StatDef:
    key: str
    label: str
    column: str | None  # mv_kpi_daily column (institution / college scope)
    module: str
    permission: tuple[str, ...]
    fmt: str = "int"  # int | pct | inr | decimal
    target_key: str | None = None  # analytics.targets key
    direction: str = "higher"  # higher | lower is better
    scoped_chart: str | None = None  # number / gauge chart for department / own / self scopes
    feature: str | None = None
    route: str | None = None
    public: bool = False


@dataclass(frozen=True)
class ListDef:
    key: str
    title: str
    module: str
    permission: tuple[str, ...]
    route: str
    provider: Callable[..., Any] | None = None
    feature: str | None = None


@dataclass(frozen=True)
class ActionDef:
    key: str
    label: str
    route: str
    permission: tuple[str, ...]
    icon: str = "zap"
    feature: str | None = None


DASHBOARD_REGISTRY: dict[str, list[WidgetSpec]] = {}
STAT_KEYS: dict[str, StatDef] = {}
LIST_KEYS: dict[str, ListDef] = {}
ACTION_KEYS: dict[str, ActionDef] = {}


def register_dashboard(role_slug: str, widgets: list[WidgetSpec]) -> list[WidgetSpec]:
    keys = [w.key for w in widgets]
    assert len(keys) == len(set(keys)), f"dashboard {role_slug}: duplicate widget keys"
    for w in widgets:
        assert w.size in SIZES, f"dashboard {role_slug}: widget {w.key} size {w.size!r}"
        assert sum(bool(x) for x in (w.chart_key, w.stat_key, w.list_key, w.action_key)) == 1, (
            f"dashboard {role_slug}: widget {w.key} must point at exactly one chart / stat / list / action"
        )
    DASHBOARD_REGISTRY[role_slug] = list(widgets)
    return widgets


def register_stat(stat: StatDef) -> StatDef:
    STAT_KEYS[stat.key] = stat
    return stat


def register_list(item: ListDef) -> ListDef:
    LIST_KEYS[item.key] = item
    return item


def register_action(item: ActionDef) -> ActionDef:
    ACTION_KEYS[item.key] = item
    return item


@dataclass
class Layout:
    """``{columns, widgets[{key, size, position, hidden}]}`` — stored per role / user."""

    columns: int = 4
    widgets: list[dict[str, Any]] = field(default_factory=list)
