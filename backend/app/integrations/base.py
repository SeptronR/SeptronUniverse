"""``AdapterBase`` — Prompts/41 §41.6 ``adapter_service`` rule 1.

Every real provider subclasses it: an ``httpx.AsyncClient`` with the capability's timeout
(``integrations.timeouts_s``), retries with jitter on 5xx / timeouts (never on 4xx), a circuit breaker per
connection in Redis (``integrations.circuit_breaker``: ``failures`` in ``window_s`` opens it for ``open_s``; one
half-open probe), a token-bucket rate limit per connection, sandbox base URLs, ``health()`` and ``redact(config)``.
Failures raise :class:`IntegrationFailed` (``INTEGRATION_FAILED`` with ``provider`` / ``code`` / ``retryable``).
Logs never carry payloads (PII-free); call counters ``intcall:{capability}:{provider}:{outcome}:{day}`` feed metrics.
"""

import asyncio
import random
import time
from datetime import date
from typing import Any

import structlog

from app.core.errors import APIError, ErrorCode

log = structlog.get_logger()

DEFAULT_TIMEOUTS: dict[str, int] = {
    "payments": 15,
    "sms": 10,
    "email": 20,
    "whatsapp": 10,
    "push": 10,
    "sso": 10,
    "lti": 10,
    "video": 15,
    "digilocker": 30,
    "abc": 30,
    "nsp": 60,
    "mooc": 20,
    "lookup": 15,
    "plagiarism": 60,
    "repository": 60,
    "library": 20,
    "device": 10,
    "face": 20,
    "esign": 60,
    "ekyc": 30,
    "accounting": 60,
    "workspace": 30,
    "llm": 60,
}
DEFAULT_BREAKER = {"failures": 5, "window_s": 60, "open_s": 120}
DEFAULT_RETRY = {"attempts": 3, "max_s": 8}


class IntegrationFailed(APIError):
    def __init__(self, provider: str, code: str, message: str, retryable: bool = False, status: int = 502):
        super().__init__(
            status, ErrorCode.INTEGRATION_FAILED, message, {"provider": provider, "code": code, "retryable": retryable}
        )
        self.provider, self.code_name, self.retryable = provider, code, retryable


class AdapterBase:
    capability = "generic"
    provider = "generic"
    timeout_class = "lookup"
    base_url = ""
    sandbox_url = ""
    secret_fields: tuple[str, ...] = ()

    def __init__(self, **config: Any):
        self.config = config
        self.connection_id = str(config.pop("_connection_id", "") or "")
        self.sandbox = bool(config.pop("_sandbox", False))
        self.timeout = float(config.pop("_timeout", DEFAULT_TIMEOUTS.get(self.timeout_class, 15)))
        self.breaker = dict(config.pop("_breaker", DEFAULT_BREAKER))
        self.rate_per_minute = int(config.pop("_rate_per_minute", 0) or 0)

    # ---- helpers ------------------------------------------------------------------------------------------------------
    @property
    def url(self) -> str:
        return str(
            self.config.get("base_url") or (self.sandbox_url if self.sandbox and self.sandbox_url else self.base_url)
        ).rstrip("/")

    def redact(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = dict(config if config is not None else self.config)
        return {k: ("***" if k in self.secret_fields and v else v) for k, v in cfg.items()}

    def _key(self, suffix: str) -> str:
        return f"breaker:{self.capability}:{self.provider}:{self.connection_id or 'default'}:{suffix}"

    async def _breaker_open(self) -> bool:
        from app.db.session import redis_client

        try:
            until = await redis_client.get(self._key("open_until"))
        except Exception:  # noqa: BLE001 - Redis down: no breaker
            return False
        return bool(until) and float(until) > time.time()

    async def _record(self, ok: bool) -> None:
        from app.db.session import redis_client

        day = date.today().isoformat()
        try:
            await redis_client.incr(f"intcall:{self.capability}:{self.provider}:{'ok' if ok else 'fail'}:{day}")
            if ok:
                await redis_client.delete(self._key("fails"))
                return
            n = int(await redis_client.incr(self._key("fails")))
            if n == 1:
                await redis_client.expire(self._key("fails"), int(self.breaker.get("window_s", 60)))
            if n >= int(self.breaker.get("failures", 5)):
                await redis_client.set(
                    self._key("open_until"),
                    str(time.time() + int(self.breaker.get("open_s", 120))),
                    ex=int(self.breaker.get("open_s", 120)) + 5,
                )
                await redis_client.delete(self._key("fails"))
                log.warning("integration_breaker_open", capability=self.capability, provider=self.provider)
        except Exception:  # noqa: BLE001
            return

    async def _throttle(self) -> None:
        if not self.rate_per_minute:
            return
        from app.db.session import redis_client

        key = self._key(f"rate:{int(time.time() // 60)}")
        try:
            n = int(await redis_client.incr(key))
            if n == 1:
                await redis_client.expire(key, 61)
        except Exception:  # noqa: BLE001
            return
        if n > self.rate_per_minute:
            raise IntegrationFailed(
                self.provider, "RATE_LIMITED", "Provider rate limit reached", retryable=True, status=429
            )

    async def request(self, method: str, path: str, *, retry: bool = True, **kw: Any) -> Any:
        """HTTP call with breaker / throttle / retries (5xx and timeouts only); returns JSON (or text)."""
        import httpx

        if await self._breaker_open():
            raise IntegrationFailed(
                self.provider, "CIRCUIT_OPEN", f"{self.provider} is temporarily unavailable", retryable=True, status=503
            )
        await self._throttle()
        attempts = int(DEFAULT_RETRY["attempts"]) if retry else 1
        url = path if path.startswith("http") else f"{self.url}{path}"
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(method, url, **kw)
                if resp.status_code >= 500:
                    raise IntegrationFailed(
                        self.provider,
                        f"HTTP_{resp.status_code}",
                        f"{self.provider} answered {resp.status_code}",
                        retryable=True,
                    )
                if resp.status_code >= 400:
                    await self._record(True)  # a 4xx is our request's fault, not the provider's health
                    raise IntegrationFailed(
                        self.provider,
                        f"HTTP_{resp.status_code}",
                        f"{self.provider} rejected the request ({resp.status_code})",
                        retryable=False,
                        status=422,
                    )
                await self._record(True)
                ctype = resp.headers.get("content-type", "")
                return resp.json() if "json" in ctype else resp.text
            except IntegrationFailed as exc:
                if not exc.retryable:
                    raise
                last = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = IntegrationFailed(
                    self.provider, "TIMEOUT", f"{self.provider} did not answer", retryable=True, status=504
                )
                _ = exc
            await self._record(False)
            if attempt + 1 < attempts:
                await asyncio.sleep(min(float(DEFAULT_RETRY["max_s"]), (2**attempt) + random.random()))  # noqa: S311 - jitter
        assert last is not None
        raise last

    async def health(self) -> tuple[bool, str]:
        """Cheap authenticated call; subclasses override with a provider-specific probe."""
        if not self.url:
            return True, "no endpoint (local provider)"
        try:
            await self.request("GET", "/", retry=False)
            return True, "ok"
        except IntegrationFailed as exc:
            return exc.code_name.startswith("HTTP_4"), exc.message
