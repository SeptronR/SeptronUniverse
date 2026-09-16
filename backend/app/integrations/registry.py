"""Adapter registry — Prompts/00 §2 tree; docs/Integrations_Catalogue.md.

``@register_adapter("sms", "msg91")`` registers a factory; ``get_adapter(capability, provider)`` returns an instance
(``mock`` for every capability so development never needs live credentials). Phase 41 completes the hub (per-tenant
``integration_connections``, health checks, circuit breakers, ``check_adapter_registry.py``).
"""

from collections.abc import Callable
from typing import Any, Protocol

import structlog

log = structlog.get_logger()

CAPABILITIES = (
    "sms",
    "whatsapp",
    "email",
    "push",
    "payment",
    "sso",
    "lti",
    "video_conf",
    "digilocker",
    "nad_abc",
    "nsp",
    "swayam",
    "scopus",
    "crossref",
    "orcid",
    "plagiarism",
    "koha",
    "dspace",
    "shodhganga",
    "biometric",
    "rfid",
    "face_verification",
    "esign",
    "aadhaar_ekyc",
    "workspace",
    "storage",
    "captcha",
    "maps",
)

Factory = Callable[..., Any]
ADAPTERS: dict[tuple[str, str], Factory] = {}


class Adapter(Protocol):
    capability: str
    provider: str

    async def health(self) -> tuple[bool, str]: ...


def register_adapter(capability: str, provider: str) -> Callable[[Factory], Factory]:
    def deco(factory: Factory) -> Factory:
        ADAPTERS[(capability, provider)] = factory
        return factory

    return deco


def get_adapter(capability: str, provider: str = "mock", **config: Any) -> Any:
    factory = ADAPTERS.get((capability, provider)) or ADAPTERS.get((capability, "mock"))
    if factory is None:
        raise KeyError(f"no adapter for {capability}/{provider}")
    return factory(**config)


def providers_for(capability: str) -> list[str]:
    return sorted(p for c, p in ADAPTERS if c == capability)


class MockAdapter:
    """Logs calls instead of contacting a provider; returned for ``provider='mock'`` of any capability."""

    def __init__(self, capability: str, **config: Any):
        self.capability = capability
        self.provider = "mock"
        self.config = config
        self.calls: list[dict[str, Any]] = []

    async def health(self) -> tuple[bool, str]:
        return True, "mock"

    async def send(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(payload)
        log.info("mock_adapter_send", capability=self.capability, keys=sorted(payload))
        return {"status": "sent", "provider": "mock", "reference": f"mock-{len(self.calls)}"}

    def __getattr__(self, name: str) -> Any:  # any other operation resolves to ``send``
        if name.startswith("_"):
            raise AttributeError(name)
        return self.send


for _cap in CAPABILITIES:
    ADAPTERS[(_cap, "mock")] = (lambda cap: (lambda **cfg: MockAdapter(cap, **cfg)))(_cap)
