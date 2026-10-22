"""Payment gateways — Prompts/12 §12.6 ``payment_service`` (2).

``PaymentGateway`` is the interface every provider implements: ``create_order`` → ``{order_id, amount, key,
checkout}``, ``verify_signature`` (mandatory for webhooks and client verification), ``fetch_status`` (Beat poll of
``initiated`` orders). Razorpay ships first (HMAC-SHA256 of ``order_id|payment_id`` with the key secret; webhooks sign
the raw body with the webhook secret). Development uses the **mock** gateway: deterministic signatures with a fixed
dev secret so ``/_dev`` fixtures can sign callbacks — no real keys anywhere. ``UpiCollect.generate_qr`` builds a
dynamic ``upi://pay`` intent with a reference.
"""

import hashlib
import hmac
import uuid
from typing import Any, Protocol

from app.integrations.registry import register_adapter

MOCK_SECRET = "septron-dev-mock-secret"  # noqa: S105 - development-only mock gateway, not a credential


def hmac_hex(secret: str, message: str | bytes) -> str:
    raw = message.encode() if isinstance(message, str) else message
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class PaymentGateway(Protocol):
    provider: str

    async def create_order(
        self, *, amount_paise: int, receipt: str, notes: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...
    def verify_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool: ...
    def verify_webhook(self, *, body: bytes, signature: str) -> bool: ...
    async def fetch_status(self, order_id: str) -> str: ...


@register_adapter("payment", "mock")
class MockGateway:
    """Mock checkout. Also serves the Phase 08 ``create_order(amount_paise, purpose, payer_type, payer_ref)`` call."""

    capability = "payment"
    provider = "mock"

    def __init__(self, **config: Any):
        self.secret = str(config.get("secret") or MOCK_SECRET)

    async def health(self) -> tuple[bool, str]:
        return True, "mock"

    async def create_order(self, *, amount_paise: int, receipt: str | None = None, **kw: Any) -> dict[str, Any]:
        order_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        return {
            "order_id": order_id,
            "reference": order_id,
            "amount": int(amount_paise),
            "key": "rzp_test_mock",
            "checkout": {"mode": "mock", "receipt": receipt, "url": f"/mock-checkout/{order_id}"},
        }

    def sign(self, order_id: str, payment_id: str) -> str:
        return hmac_hex(self.secret, f"{order_id}|{payment_id}")

    def verify_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(order_id, payment_id), signature or "")

    def verify_webhook(self, *, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(hmac_hex(self.secret, body), signature or "")

    async def fetch_status(self, order_id: str) -> str:
        return "created"


@register_adapter("payment", "razorpay")
class RazorpayGateway:
    capability = "payment"
    provider = "razorpay"
    base = "https://api.razorpay.com/v1"

    def __init__(self, **config: Any):
        self.key_id = str(config.get("key_id") or "")
        self.key_secret = str(config.get("key_secret") or "")
        self.webhook_secret = str(config.get("webhook_secret") or "")

    async def health(self) -> tuple[bool, str]:
        return bool(self.key_id and self.key_secret), "configured" if self.key_id else "missing keys"

    async def create_order(self, *, amount_paise: int, receipt: str | None = None, **kw: Any) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=15, auth=(self.key_id, self.key_secret)) as c:
            r = await c.post(
                f"{self.base}/orders",
                json={
                    "amount": int(amount_paise),
                    "currency": "INR",
                    "receipt": (receipt or "")[:40],
                    "notes": kw.get("notes") or {},
                },
            )
            r.raise_for_status()
            data = r.json()
        return {
            "order_id": data["id"],
            "reference": data["id"],
            "amount": data["amount"],
            "key": self.key_id,
            "checkout": {"mode": "razorpay"},
        }

    def verify_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        return bool(self.key_secret) and hmac.compare_digest(
            hmac_hex(self.key_secret, f"{order_id}|{payment_id}"), signature or ""
        )

    def verify_webhook(self, *, body: bytes, signature: str) -> bool:
        return bool(self.webhook_secret) and hmac.compare_digest(hmac_hex(self.webhook_secret, body), signature or "")

    async def fetch_status(self, order_id: str) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=15, auth=(self.key_id, self.key_secret)) as c:
            r = await c.get(f"{self.base}/orders/{order_id}")
            r.raise_for_status()
            return str(r.json().get("status") or "created")


class UpiCollect:
    """Dynamic UPI QR: ``upi://pay?pa=<vpa>&pn=<name>&am=<rupees>&tr=<ref>&cu=INR`` rendered as a PNG data URL."""

    def __init__(self, vpa: str | None, payee: str):
        self.vpa = vpa or "septron.dev@upi"
        self.payee = payee

    def generate_qr(self, amount_paise: int, ref: str) -> dict[str, Any]:
        from urllib.parse import quote

        uri = f"upi://pay?pa={self.vpa}&pn={quote(self.payee)}&am={amount_paise / 100:.2f}&tr={ref}&cu=INR"
        png = None
        try:
            import base64
            import io

            import qrcode  # type: ignore[import-untyped]

            buf = io.BytesIO()
            qrcode.make(uri).save(buf, format="PNG")
            png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001 - qrcode missing: the client renders the intent itself
            png = None
        return {"qr_png": png, "upi_uri": uri, "vpa": self.vpa, "amount": amount_paise, "ref": ref}


def gateway(provider: str | None = None, **config: Any) -> Any:
    from app.integrations.registry import get_adapter

    return get_adapter("payment", provider or "mock", **config)
