"""Parser for ``docs/Feature_Flags.md`` §2 (the human-readable feature registry) shared by the guards and seeders.

Table rows: ``| key | name | what it gates | default (on/off) | tier | depends on |`` under ``### 2.x <Group>`` headings.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import _bootstrap  # noqa: F401

FEATURE_DOC = _bootstrap.DOCS_DIR / "Feature_Flags.md"
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


def _group_slug(heading: str) -> str:
    text = re.sub(r"\(.*?\)", "", heading).strip()
    text = text.split(".", 1)[-1].strip() if re.match(r"^\d+\.\d+", text) else text
    first = re.split(r"[,&/]| and ", text)[0].strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", first).strip("_")[:40] or "misc"


def load_doc_features(path: Path = FEATURE_DOC) -> dict[str, DocFeature]:
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
            default_enabled=default.lower() == "on",
            min_plan_tier=tier.lower(),
            depends_on=deps,
            group=group,
        )
    return features


if __name__ == "__main__":
    docs = load_doc_features()
    print(f"{len(docs)} feature keys in {FEATURE_DOC.name}")
    for g in sorted({d.group for d in docs.values()}):
        print(f"  {g}: {sum(1 for d in docs.values() if d.group == g)}")
