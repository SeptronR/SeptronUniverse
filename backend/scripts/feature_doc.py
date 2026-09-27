"""Parser for ``docs/Feature_Flags.md`` §2 — thin wrapper over ``app.core.feature_doc`` (moved in Phase 02 so the
``/install`` bootstrap can seed ``platform_features`` in-process). Guards and seeders keep importing it from here."""

import _bootstrap  # noqa: F401

from app.core.feature_doc import DocFeature, load_doc_features

FEATURE_DOC = _bootstrap.DOCS_DIR / "Feature_Flags.md"

__all__ = ["DocFeature", "FEATURE_DOC", "load_doc_features"]


if __name__ == "__main__":
    docs = load_doc_features(FEATURE_DOC)
    print(f"{len(docs)} feature keys in {FEATURE_DOC.name}")
    for g in sorted({d.group for d in docs.values()}):
        print(f"  {g}: {sum(1 for d in docs.values() if d.group == g)}")
