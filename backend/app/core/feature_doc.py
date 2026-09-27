"""Parser for ``docs/Feature_Flags.md`` §2 (the human-readable feature registry) shared by guards, seeders and
``/install`` (Prompts/02 §02.6 ``install_service``).

Table rows: ``| key | name | what it gates | default (on/off) | tier | depends on |`` under ``### 2.x <Group>``
headings. A default written as ``on (core)`` counts as on. The file is optional at runtime (containers ship only the
backend): ``find_feature_doc()`` returns ``None`` when it is not on disk and callers fall back to the code registry.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


@dataclass(frozen=True)
class DocFeature:
    key: str
    name: str
    description: str
    default_enabled: bool
    min_plan_tier: str
    depends_on: tuple[str, ...]
    group: str


def find_feature_doc() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        Path(os.environ["FEATURE_DOC_PATH"]) if os.environ.get("FEATURE_DOC_PATH") else None,
        here.parents[3] / "docs" / "Feature_Flags.md",  # <repo>/docs (app/core → app → backend → repo)
        here.parents[2] / "docs" / "Feature_Flags.md",  # <backend>/docs (container copy)
        Path.cwd() / "docs" / "Feature_Flags.md",
        Path.cwd().parent / "docs" / "Feature_Flags.md",
    ]
    for c in candidates:
        if c is not None and c.is_file():
            return c
    return None


def _group_slug(heading: str) -> str:
    text = re.sub(r"\(.*?\)", "", heading).strip()
    text = text.split(".", 1)[-1].strip() if re.match(r"^\d+\.\d+", text) else text
    first = re.split(r"[,&/]| and ", text)[0].strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", first).strip("_")[:40] or "misc"


def load_doc_features(path: Path | None = None) -> dict[str, DocFeature]:
    path = path or find_feature_doc()
    if path is None:
        return {}
    features: dict[str, DocFeature] = {}
    group = "misc"
    in_registry = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_registry = line.startswith("## 2.")
            continue
        if line.startswith("### ") and in_registry:
            group = _group_slug(line[4:])
            continue
        if not in_registry or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6 or not KEY_RE.match(cells[0]):
            continue
        key, name, gates, default, tier, depends = cells[:6]
        deps = tuple(
            d.strip().strip("`") for d in re.split(r"[,;]", depends) if d.strip() and d.strip() not in {"—", "-", "–"}
        )
        features[key] = DocFeature(
            key=key,
            name=name,
            description=gates,
            default_enabled=default.lower().startswith("on"),
            min_plan_tier=tier.lower(),
            depends_on=deps,
            group=group,
        )
    return features
