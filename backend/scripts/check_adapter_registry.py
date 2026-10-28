"""Adapter-registry guard — Prompts/41 §41.11 step 1.

Every capability of ``docs/Integrations_Catalogue.md`` §1 (the hub's ``CAPABILITY_INFO``) must have at least one real
provider registered plus a mock, and every real provider class must implement the capability's interface methods.
"""

import sys

import _bootstrap  # noqa: F401


def main() -> int:
    import app.integrations  # noqa: F401
    from app.integrations.catalogue import CAPABILITY_INFO
    from app.integrations.registry import ADAPTERS

    missing: list[str] = []
    for cap, info in CAPABILITY_INFO.items():
        real = [(p, f) for (c, p), f in ADAPTERS.items() if c == cap and p != "mock"]
        if not real:
            missing.append(f"{cap}: no real provider")
        if (cap, "mock") not in ADAPTERS:
            missing.append(f"{cap}: no mock")
        for provider, factory in real:
            cls = factory if isinstance(factory, type) else type(factory())
            absent = [m for m in info.methods if not hasattr(cls, m)]
            if absent and not hasattr(cls, "send"):
                missing.append(f"{cap}/{provider}: missing {', '.join(absent)}")
    print(f"adapter registry: {len(CAPABILITY_INFO)} capabilities, {len(ADAPTERS)} adapters")  # noqa: T201
    for m in missing:
        print(f"  MISSING {m}")  # noqa: T201
    print(f"{len(missing)} missing")  # noqa: T201
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
