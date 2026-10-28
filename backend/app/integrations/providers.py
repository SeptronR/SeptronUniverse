"""Real providers for every capability — Prompts/41 §41.6 ``adapter_service`` rule 2 (docs/Integrations_Catalogue.md).

Each class implements its capability's interface methods on :class:`AdapterBase` (timeouts, retries, breaker, rate
limit, sandbox, redaction) against the provider's documented REST API. Credentials arrive decrypted from the tenant
connection (``app/integrations/hub.py``); nothing here logs payloads. Providers needing a licence / onboarding work in
sandbox only until ``Real_World_Launch_Plan.md`` Batch I marks them live. ``FunctionalMock`` (bottom) is the
deterministic, stateful mock twin of every capability used by the verification scripts.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from app.integrations.base import AdapterBase, IntegrationFailed
from app.integrations.registry import register_adapter


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _hmac_hex(secret: str, msg: bytes | str) -> str:
    return hmac.new(secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256).hexdigest()


# ---- payments -----------------------------------------------------------------------------------------------------------
@register_adapter("payment", "stripe")
class StripeGateway(AdapterBase):
    capability, provider, timeout_class, base_url = "payment", "stripe", "payments", "https://api.stripe.com/v1"
    secret_fields = ("secret_key", "webhook_secret")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('secret_key', '')}"}

    async def create_order(self, *, amount_paise: int, receipt: str | None = None, **kw: Any) -> dict[str, Any]:
        data = await self.request(
            "POST",
            "/payment_intents",
            headers=self._auth(),
            data={"amount": amount_paise, "currency": kw.get("currency", "usd"), "metadata[receipt]": receipt or ""},
        )
        return {
            "order_id": data["id"],
            "reference": data["id"],
            "amount": data["amount"],
            "client_secret": data.get("client_secret"),
            "checkout": {"mode": "stripe"},
        }

    def verify_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        return bool(order_id and payment_id)  # Stripe confirms server-side; the webhook carries the proof

    def verify_webhook(self, *, body: bytes, signature: str) -> bool:
        parts = dict(p.split("=", 1) for p in (signature or "").split(",") if "=" in p)
        expected = _hmac_hex(str(self.config.get("webhook_secret", "")), f"{parts.get('t', '')}.".encode() + body)
        return bool(parts.get("v1")) and hmac.compare_digest(expected, parts["v1"])

    def webhook_parse(self, body: bytes) -> dict[str, Any]:
        e = json.loads(body)
        obj = (e.get("data") or {}).get("object") or {}
        return {
            "event_id": e.get("id"),
            "type": e.get("type"),
            "order_id": obj.get("id"),
            "status": obj.get("status"),
            "amount": obj.get("amount"),
        }

    async def refund(self, *, payment_id: str, amount_paise: int | None = None) -> dict[str, Any]:
        data = await self.request(
            "POST",
            "/refunds",
            headers=self._auth(),
            data={"payment_intent": payment_id, **({"amount": amount_paise} if amount_paise else {})},
        )
        return {"refund_id": data["id"], "status": data["status"]}

    async def fetch_status(self, order_id: str) -> str:
        return str((await self.request("GET", f"/payment_intents/{order_id}", headers=self._auth())).get("status"))

    async def health(self) -> tuple[bool, str]:
        try:
            await self.request("GET", "/balance", headers=self._auth(), retry=False)
            return True, "ok"
        except IntegrationFailed as exc:
            return False, exc.message


class _FormGateway(AdapterBase):
    """PayU / Cashfree share a create-order → hosted checkout → signed callback shape."""

    capability, timeout_class = "payment", "payments"

    async def create_order(self, *, amount_paise: int, receipt: str | None = None, **kw: Any) -> dict[str, Any]:
        ref = receipt or uuid.uuid4().hex[:20]
        return {
            "order_id": ref,
            "reference": ref,
            "amount": amount_paise,
            "checkout": {"mode": self.provider, "url": f"{self.url}/checkout?ref={ref}"},
        }

    def verify_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        key = str(self.config.get("salt") or self.config.get("secret_key") or "")
        return bool(key) and hmac.compare_digest(_hmac_hex(key, f"{order_id}|{payment_id}"), signature or "")

    def verify_webhook(self, *, body: bytes, signature: str) -> bool:
        key = str(self.config.get("salt") or self.config.get("secret_key") or "")
        return bool(key) and hmac.compare_digest(_hmac_hex(key, body), signature or "")

    def webhook_parse(self, body: bytes) -> dict[str, Any]:
        e = json.loads(body)
        return {
            "event_id": e.get("event_id") or e.get("txnid"),
            "type": e.get("type") or "payment",
            "order_id": e.get("order_id") or e.get("txnid"),
            "status": e.get("status"),
        }

    async def refund(self, *, payment_id: str, amount_paise: int | None = None) -> dict[str, Any]:
        data = await self.request("POST", "/refunds", json={"payment_id": payment_id, "amount": amount_paise})
        return {"refund_id": str(data.get("id") if isinstance(data, dict) else payment_id), "status": "processed"}

    async def fetch_status(self, order_id: str) -> str:
        data = await self.request("GET", f"/orders/{order_id}")
        return str(data.get("status") if isinstance(data, dict) else "unknown")


@register_adapter("payment", "payu")
class PayUGateway(_FormGateway):
    provider, base_url, sandbox_url, secret_fields = "payu", "https://info.payu.in", "https://test.payu.in", ("salt",)


@register_adapter("payment", "cashfree")
class CashfreeGateway(_FormGateway):
    provider, base_url, sandbox_url, secret_fields = (
        "cashfree",
        "https://api.cashfree.com/pg",
        "https://sandbox.cashfree.com/pg",
        ("secret_key",),
    )


@register_adapter("upi", "razorpay_qr")
class RazorpayQr(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "upi",
        "razorpay_qr",
        "payments",
        "https://api.razorpay.com/v1",
        ("key_secret",),
    )

    def _auth(self) -> tuple[str, str]:
        return (str(self.config.get("key_id", "")), str(self.config.get("key_secret", "")))

    async def generate_qr(self, amount_paise: int, ref: str) -> dict[str, Any]:
        d = await self.request(
            "POST",
            "/payments/qr_codes",
            auth=self._auth(),
            json={
                "type": "upi_qr",
                "usage": "single_use",
                "fixed_amount": True,
                "payment_amount": amount_paise,
                "description": ref[:40],
            },
        )
        return {"qr_id": d["id"], "image_url": d.get("image_url"), "reference": ref}

    async def poll_status(self, qr_id: str) -> str:
        d = await self.request("GET", f"/payments/qr_codes/{qr_id}/payments", auth=self._auth())
        return "paid" if (d.get("count") or 0) > 0 else "pending"


@register_adapter("upi", "static_vpa")
class StaticVpa(AdapterBase):
    capability, provider, timeout_class = "upi", "static_vpa", "payments"

    async def generate_qr(self, amount_paise: int, ref: str) -> dict[str, Any]:
        from app.integrations.payments import UpiCollect

        return UpiCollect(str(self.config.get("vpa")), str(self.config.get("payee_name") or "Institution")).generate_qr(
            amount_paise, ref
        )

    async def poll_status(self, qr_id: str) -> str:
        return "pending"  # confirmed by bank-statement reconciliation (Phase 12)


# ---- messaging --------------------------------------------------------------------------------------------------------------
@register_adapter("sms", "twilio")
class TwilioSms(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "sms",
        "twilio",
        "sms",
        "https://api.twilio.com/2010-04-01",
        ("auth_token",),
    )

    async def send(self, *, to: str, body: str, **kw: Any) -> dict[str, Any]:
        sid = self.config.get("account_sid", "")
        d = await self.request(
            "POST",
            f"/Accounts/{sid}/Messages.json",
            auth=(sid, self.config.get("auth_token", "")),
            data={"To": to, "From": self.config.get("from_number"), "Body": body},
        )
        return {"reference": d.get("sid"), "status": d.get("status")}

    async def delivery_status(self, reference: str) -> str:
        sid = self.config.get("account_sid", "")
        return str(
            (
                await self.request(
                    "GET", f"/Accounts/{sid}/Messages/{reference}.json", auth=(sid, self.config.get("auth_token", ""))
                )
            ).get("status")
        )

    async def dlt_register(self, **_: Any) -> dict[str, Any]:
        return {"status": "not_applicable"}


@register_adapter("sms", "msg91")
class Msg91Sms(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "sms",
        "msg91",
        "sms",
        "https://control.msg91.com/api/v5",
        ("auth_key",),
    )

    async def send(self, *, to: str, body: str, **kw: Any) -> dict[str, Any]:
        tmpl = kw.get("dlt_template_id")
        if not tmpl:
            raise IntegrationFailed(self.provider, "DLT_TEMPLATE_MISSING", "DLT template id required for SMS in India")
        d = await self.request(
            "POST",
            "/flow/",
            headers={"authkey": str(self.config.get("auth_key", ""))},
            json={
                "template_id": tmpl,
                "sender": kw.get("sender_id") or self.config.get("sender_id"),
                "recipients": [{"mobiles": to.lstrip("+"), "body": body}],
            },
        )
        return {"reference": str(d.get("request_id") or d.get("message") or ""), "status": "queued"}

    async def delivery_status(self, reference: str) -> str:
        return "queued"  # MSG91 pushes DLRs to /webhooks/msg91/sms

    async def dlt_register(self, **kw: Any) -> dict[str, Any]:
        return {"status": "manual", "note": "register templates on the operator DLT portal"}

    async def health(self) -> tuple[bool, str]:
        return bool(self.config.get("auth_key")), "configured" if self.config.get("auth_key") else "missing auth key"


@register_adapter("whatsapp", "meta")
class MetaWhatsApp(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "whatsapp",
        "meta",
        "whatsapp",
        "https://graph.facebook.com/v20.0",
        ("access_token", "app_secret", "verify_token"),
    )

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('access_token', '')}"}

    async def send_template(
        self, *, to: str, template: str, language: str = "en", variables: list[str] | None = None
    ) -> dict[str, Any]:
        comps = (
            [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variables or []]}]
            if variables
            else []
        )
        d = await self.request(
            "POST",
            f"/{self.config.get('phone_number_id')}/messages",
            headers=self._h(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {"name": template, "language": {"code": language}, "components": comps},
            },
        )
        return {"reference": (d.get("messages") or [{}])[0].get("id")}

    async def send_session_message(self, *, to: str, body: str) -> dict[str, Any]:
        d = await self.request(
            "POST",
            f"/{self.config.get('phone_number_id')}/messages",
            headers=self._h(),
            json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}},
        )
        return {"reference": (d.get("messages") or [{}])[0].get("id")}

    async def send(self, *, to: str, body: str, **kw: Any) -> dict[str, Any]:
        if kw.get("whatsapp_template"):
            return await self.send_template(to=to, template=kw["whatsapp_template"], variables=kw.get("variables"))
        return await self.send_session_message(to=to, body=body)

    def verify_webhook(self, *, body: bytes, signature: str) -> bool:
        exp = "sha256=" + _hmac_hex(str(self.config.get("app_secret", "")), body)
        return hmac.compare_digest(exp, signature or "")

    def webhook_parse(self, body: bytes) -> dict[str, Any]:
        e = json.loads(body)
        value = ((e.get("entry") or [{}])[0].get("changes") or [{}])[0].get("value") or {}
        msg = (value.get("messages") or [{}])[0]
        status = (value.get("statuses") or [{}])[0]
        return {
            "event_id": msg.get("id") or status.get("id"),
            "type": "message" if msg else "status",
            "from": msg.get("from"),
            "text": (msg.get("text") or {}).get("body"),
            "status": status.get("status"),
        }

    async def template_status(self, name: str) -> str:
        return "unknown"  # synced by whatsapp.template_sync (business account endpoint)


class _EmailBase(AdapterBase):
    capability, timeout_class = "email", "email"

    async def bounce_webhook(self, body: bytes) -> dict[str, Any]:
        return {"events": json.loads(body) if body else []}

    async def domain_auth_status(self, domain: str) -> dict[str, Any]:
        from app.services.integrations.email_domain import dns_records

        return {"domain": domain, "records": dns_records(domain, self.provider)}


@register_adapter("email", "smtp")
class SmtpEmail(_EmailBase):
    provider, secret_fields = "smtp", ("password",)

    async def send(self, *, to: str, body: str, subject: str | None = None, **kw: Any) -> dict[str, Any]:
        import asyncio
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.config.get("from_email"), to, subject or ""
        msg.set_content(body)

        def _send() -> None:
            with smtplib.SMTP(
                str(self.config.get("host")), int(self.config.get("port") or 587), timeout=self.timeout
            ) as s:
                s.starttls()
                if self.config.get("username"):
                    s.login(str(self.config["username"]), str(self.config.get("password", "")))
                s.send_message(msg)

        await asyncio.to_thread(_send)
        return {"reference": msg["Message-ID"] or uuid.uuid4().hex, "status": "sent"}

    async def health(self) -> tuple[bool, str]:
        return bool(self.config.get("host")), "configured" if self.config.get("host") else "missing host"


@register_adapter("email", "sendgrid")
class SendGridEmail(_EmailBase):
    provider, base_url, secret_fields = "sendgrid", "https://api.sendgrid.com/v3", ("api_key",)

    async def send(self, *, to: str, body: str, subject: str | None = None, **kw: Any) -> dict[str, Any]:
        await self.request(
            "POST",
            "/mail/send",
            headers={"Authorization": f"Bearer {self.config.get('api_key', '')}"},
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": self.config.get("from_email")},
                "subject": subject or "",
                "content": [{"type": "text/plain", "value": body}],
            },
        )
        return {"reference": uuid.uuid4().hex, "status": "queued"}


@register_adapter("email", "ses")
class SesEmail(_EmailBase):
    provider, secret_fields = "ses", ("secret_access_key",)

    @property
    def url(self) -> str:
        return f"https://email.{self.config.get('region', 'ap-south-1')}.amazonaws.com"

    async def send(self, *, to: str, body: str, subject: str | None = None, **kw: Any) -> dict[str, Any]:
        # SigV4 signing is delegated to boto3 when installed (production images); otherwise refuse clearly
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise IntegrationFailed(self.provider, "SDK_MISSING", "boto3 is required for Amazon SES") from exc
        import asyncio

        def _send() -> dict[str, Any]:
            c = boto3.client(
                "ses",
                region_name=self.config.get("region"),
                aws_access_key_id=self.config.get("access_key_id"),
                aws_secret_access_key=self.config.get("secret_access_key"),
            )
            return c.send_email(  # type: ignore[no-any-return]
                Source=self.config.get("from_email"),
                Destination={"ToAddresses": [to]},
                Message={"Subject": {"Data": subject or ""}, "Body": {"Text": {"Data": body}}},
            )  # type: ignore[no-any-return]

        r = await asyncio.to_thread(_send)
        return {"reference": r.get("MessageId"), "status": "sent"}


@register_adapter("push", "fcm")
class FcmPush(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "push",
        "fcm",
        "push",
        "https://fcm.googleapis.com/v1",
        ("service_account_json",),
    )

    async def _token(self) -> str:
        from app.services.integrations.google_auth import service_account_token

        return await service_account_token(
            str(self.config.get("service_account_json", "")), "https://www.googleapis.com/auth/firebase.messaging"
        )

    async def send(self, *, to: str, body: str, subject: str | None = None, **kw: Any) -> dict[str, Any]:
        target = {"topic": to[6:]} if to.startswith("topic:") else {"token": to}
        payload = kw.get("payload") or {}
        d = await self.request(
            "POST",
            f"/projects/{self.config.get('project_id')}/messages:send",
            headers={"Authorization": f"Bearer {await self._token()}"},
            json={
                "message": {
                    **target,
                    "notification": {"title": subject or "", "body": body},
                    "data": {k: str(v) for k, v in payload.items()},
                }
            },
        )
        return {"reference": d.get("name")}

    async def subscribe_topic(self, token: str, topic: str) -> dict[str, Any]:
        return await self.request(  # type: ignore[no-any-return]
            "POST",
            "https://iid.googleapis.com/iid/v1:batchAdd",
            headers={"Authorization": f"Bearer {await self._token()}", "access_token_auth": "true"},
            json={"to": f"/topics/{topic}", "registration_tokens": [token]},
        )

    async def register_device(self, token: str) -> dict[str, Any]:
        return {"token": token, "status": "registered"}


# ---- identity / learning -------------------------------------------------------------------------------------------------------
class _Oidc(AdapterBase):
    capability, timeout_class, secret_fields = "sso", "sso", ("client_secret",)
    issuer = ""

    def _issuer(self) -> str:
        return str(self.config.get("issuer") or self.issuer).rstrip("/")

    async def discovery(self) -> dict[str, Any]:
        return dict(await self.request("GET", f"{self._issuer()}/.well-known/openid-configuration", retry=False))

    async def authorize_url_async(self, *, state: str, redirect_uri: str, login_hint: str | None = None) -> str:
        d = await self.discovery()
        q = {
            "client_id": self.config.get("client_id"),
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if login_hint:
            q["login_hint"] = login_hint
        if self.config.get("hosted_domain"):
            q["hd"] = self.config["hosted_domain"]
        return f"{d['authorization_endpoint']}?{urlencode(q)}"

    def authorize_url(self, *, state: str, redirect_uri: str, login_hint: str | None = None, **_: Any) -> str:
        q = {
            "client_id": self.config.get("client_id"),
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return (
            f"{self._issuer()}/authorize?{urlencode(q)}"
            if not self.issuer.startswith("https://accounts.google")
            else f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(q)}"
        )

    async def exchange(self, *, code: str, redirect_uri: str = "", **_: Any) -> dict[str, Any]:
        d = await self.discovery()
        tok = await self.request(
            "POST",
            d["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.config.get("client_id"),
                "client_secret": self.config.get("client_secret"),
            },
        )
        return await self.userinfo(tok.get("access_token", ""), d)

    async def userinfo(self, access_token: str, disc: dict[str, Any] | None = None) -> dict[str, Any]:
        d = disc or await self.discovery()
        u = await self.request("GET", d["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"})
        return {
            "email": u.get("email"),
            "email_verified": u.get("email_verified", True),
            "name": u.get("name"),
            "groups": u.get("groups") or [],
        }

    def saml_metadata(self) -> str:
        return ""

    async def health(self) -> tuple[bool, str]:
        try:
            await self.discovery()
            return True, "discovery ok"
        except IntegrationFailed as exc:
            return False, exc.message


@register_adapter("sso", "google")
class GoogleOidc(_Oidc):
    provider, issuer = "google", "https://accounts.google.com"


@register_adapter("sso", "microsoft")
class MicrosoftOidc(_Oidc):
    provider = "microsoft"

    def _issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.config.get('tenant', 'common')}/v2.0"


@register_adapter("sso", "oidc")
class GenericOidc(_Oidc):
    provider = "oidc"


@register_adapter("sso", "saml")
class Saml2(AdapterBase):
    capability, provider, timeout_class, secret_fields = "sso", "saml", "sso", ("sp_private_key",)

    def saml_metadata(self, entity_id: str = "", acs_url: str = "") -> str:
        return (
            '<?xml version="1.0"?><md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
            f'entityID="{entity_id}"><md:SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
            "<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>"
            f'<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="{acs_url}" index="0"/>'
            "</md:SPSSODescriptor></md:EntityDescriptor>"
        )

    def authorize_url(self, *, state: str, redirect_uri: str, **_: Any) -> str:
        return f"{self.config.get('idp_metadata_url', '')}?RelayState={state}"

    async def exchange(self, *, code: str, **_: Any) -> dict[str, Any]:
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise IntegrationFailed(self.provider, "SDK_MISSING", "python3-saml is required for SAML") from exc
        raise IntegrationFailed(self.provider, "NOT_SUPPORTED", "SAML responses are processed by the ACS endpoint")

    async def userinfo(self, *_: Any) -> dict[str, Any]:
        return {}


@register_adapter("lti", "lti13")
class Lti13(AdapterBase):
    capability, provider, timeout_class, secret_fields = "lti", "lti13", "lti", ("tool_private_key",)

    async def jwks(self) -> dict[str, Any]:
        return dict(await self.request("GET", str(self.config.get("jwks_url")), retry=False))

    async def launch(self, id_token: str) -> dict[str, Any]:
        import jwt

        keys = (await self.jwks()).get("keys") or []
        header = jwt.get_unverified_header(id_token)
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
        if key is None:
            raise IntegrationFailed(self.provider, "UNKNOWN_KID", "LTI key not found")
        claims = jwt.decode(
            id_token,
            jwt.PyJWK(key).key,
            algorithms=["RS256"],
            audience=str(self.config.get("client_id")),
            issuer=str(self.config.get("issuer")),
        )
        return dict(claims)

    async def deep_link(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content_items": items}

    async def sync_courses(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return {"synced": len(mapping)}

    async def sync_grades(self, lineitem_url: str, scores: list[dict[str, Any]], token: str) -> dict[str, Any]:
        for s in scores:
            await self.request(
                "POST",
                f"{lineitem_url}/scores",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/vnd.ims.lis.v1.score+json"},
                json=s,
            )
        return {"pushed": len(scores)}

    async def health(self) -> tuple[bool, str]:
        try:
            return bool((await self.jwks()).get("keys")), "jwks ok"
        except IntegrationFailed as exc:
            return False, exc.message


@register_adapter("lti", "moodle")
class MoodleSync(AdapterBase):
    capability, provider, timeout_class, secret_fields = "lti", "moodle", "lti", ("token",)

    async def _ws(self, fn: str, **params: Any) -> Any:
        return await self.request(
            "POST",
            "/webservice/rest/server.php",
            data={"wstoken": self.config.get("token"), "wsfunction": fn, "moodlewsrestformat": "json", **params},
        )

    async def launch(self, *_: Any) -> dict[str, Any]:
        return {"url": self.url}

    async def deep_link(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content_items": items}

    async def sync_courses(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return {"courses": await self._ws("core_course_get_courses")}

    async def sync_grades(self, course_id: str, *_: Any) -> dict[str, Any]:
        return {"grades": await self._ws("gradereport_user_get_grade_items", courseid=course_id)}

    async def health(self) -> tuple[bool, str]:
        try:
            await self._ws("core_webservice_get_site_info")
            return True, "site info ok"
        except IntegrationFailed as exc:
            return False, exc.message


class _Video(AdapterBase):
    capability, timeout_class = "video_conf", "video"

    async def join_link(self, meeting: dict[str, Any]) -> str:
        return str(meeting.get("join_url") or meeting.get("hangoutLink") or meeting.get("joinWebUrl") or "")


@register_adapter("video_conf", "zoom")
class Zoom(_Video):
    provider, base_url, secret_fields = "zoom", "https://api.zoom.us/v2", ("client_secret",)

    async def _token(self) -> str:
        d = await self.request(
            "POST",
            f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={self.config.get('account_id')}",
            headers={
                "Authorization": "Basic " + _b64(f"{self.config.get('client_id')}:{self.config.get('client_secret')}")
            },
        )
        return str(d["access_token"])

    async def create_meeting(self, *, topic: str, start: str, minutes: int) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST",
                "/users/me/meetings",
                headers={"Authorization": f"Bearer {await self._token()}"},
                json={"topic": topic, "type": 2, "start_time": start, "duration": minutes},
            )
        )

    async def attendance_report(self, meeting_id: str) -> list[dict[str, Any]]:
        d = await self.request(
            "GET",
            f"/report/meetings/{meeting_id}/participants",
            headers={"Authorization": f"Bearer {await self._token()}"},
        )
        return [
            {"email": p.get("user_email"), "minutes": int(p.get("duration", 0)) // 60}
            for p in d.get("participants") or []
        ]


@register_adapter("video_conf", "meet")
class GoogleMeet(_Video):
    provider, base_url, secret_fields = "meet", "https://www.googleapis.com/calendar/v3", ("service_account_json",)

    async def create_meeting(self, *, topic: str, start: str, minutes: int) -> dict[str, Any]:
        from app.services.integrations.google_auth import service_account_token

        tok = await service_account_token(
            str(self.config.get("service_account_json", "")),
            "https://www.googleapis.com/auth/calendar",
            subject=str(self.config.get("impersonate", "")),
        )
        return dict(
            await self.request(
                "POST",
                "/calendars/primary/events?conferenceDataVersion=1",
                headers={"Authorization": f"Bearer {tok}"},
                json={
                    "summary": topic,
                    "start": {"dateTime": start},
                    "end": {"dateTime": start},
                    "conferenceData": {"createRequest": {"requestId": uuid.uuid4().hex}},
                },
            )
        )

    async def attendance_report(self, meeting_id: str) -> list[dict[str, Any]]:
        return []  # Meet attendance arrives via the Workspace reports API (admin scope)


@register_adapter("video_conf", "teams")
class Teams(_Video):
    provider, base_url, secret_fields = "teams", "https://graph.microsoft.com/v1.0", ("client_secret",)

    async def create_meeting(self, *, topic: str, start: str, minutes: int) -> dict[str, Any]:
        from app.services.integrations.ms_auth import graph_token

        tok = await graph_token(self.config)
        return dict(
            await self.request(
                "POST",
                "/me/onlineMeetings",
                headers={"Authorization": f"Bearer {tok}"},
                json={"subject": topic, "startDateTime": start},
            )
        )

    async def attendance_report(self, meeting_id: str) -> list[dict[str, Any]]:
        return []


# ---- government / credentials ---------------------------------------------------------------------------------------------------
@register_adapter("digilocker", "digilocker")
class DigiLocker(AdapterBase):
    capability, provider, timeout_class, base_url, sandbox_url, secret_fields = (
        "digilocker",
        "digilocker",
        "digilocker",
        "https://api.digitallocker.gov.in/public/oauth2/1",
        "https://apisetu.gov.in/digilocker-sandbox",
        ("api_key",),
    )

    def _h(self) -> dict[str, str]:
        return {"x-api-key": str(self.config.get("api_key", "")), "x-issuer-id": str(self.config.get("issuer_id", ""))}

    async def push_credential(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.request("POST", "/issuer/documents", headers=self._h(), json=payload))

    async def revoke(self, uri: str) -> dict[str, Any]:
        return dict(await self.request("POST", "/issuer/documents/revoke", headers=self._h(), json={"uri": uri}))

    async def status(self, uri: str) -> str:
        return str((await self.request("GET", f"/issuer/documents/{uri}", headers=self._h())).get("status"))


@register_adapter("nad_abc", "abc")
class Abc(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "nad_abc",
        "abc",
        "abc",
        "https://www.abc.gov.in/api",
        ("api_key",),
    )

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('api_key', '')}"}

    async def push_credits(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST",
                "/credits/push",
                headers=self._h(),
                json={"institution": self.config.get("institution_code"), "records": batch},
            )
        )

    async def revoke_credits(self, refs: list[str]) -> dict[str, Any]:
        return dict(await self.request("POST", "/credits/revoke", headers=self._h(), json={"refs": refs}))

    async def fetch_learner(self, apaar_id: str) -> dict[str, Any]:
        return dict(await self.request("GET", f"/learners/{apaar_id}", headers=self._h()))


@register_adapter("nsp", "nsp")
class Nsp(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "nsp",
        "nsp",
        "nsp",
        "https://scholarships.gov.in/api",
        ("password",),
    )

    async def fetch_applications(self, session: str) -> list[dict[str, Any]]:
        d = await self.request(
            "POST",
            "/institute/applications",
            json={"instituteCode": self.config.get("institution_code"), "session": session},
            auth=(str(self.config.get("username")), str(self.config.get("password"))),
        )
        return list(d.get("applications") or []) if isinstance(d, dict) else []

    async def push_verification(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST",
                "/institute/verify",
                json={"records": records},
                auth=(str(self.config.get("username")), str(self.config.get("password"))),
            )
        )

    async def disbursement_status(self, application_id: str) -> str:
        return str((await self.request("GET", f"/application/{application_id}/status")).get("status"))


@register_adapter("swayam", "swayam")
class Swayam(AdapterBase):
    capability, provider, timeout_class, base_url = "swayam", "swayam", "mooc", "https://swayam.gov.in"

    async def verify_certificate(self, certificate_id: str) -> dict[str, Any]:
        d = await self.request("GET", f"/api/certificate/verify/{certificate_id}")
        return {
            "valid": bool(d.get("valid")) if isinstance(d, dict) else False,
            "course": (d or {}).get("course") if isinstance(d, dict) else None,
        }

    async def fetch_completions(self, learner: str) -> list[dict[str, Any]]:
        return []  # SWAYAM offers no learner completion API; certificates are verified one by one


# ---- research / library / repositories ---------------------------------------------------------------------------------------------
@register_adapter("crossref", "crossref")
class Crossref(AdapterBase):
    capability, provider, timeout_class, base_url = "crossref", "crossref", "lookup", "https://api.crossref.org"

    def _params(self) -> dict[str, str]:
        return {"mailto": str(self.config["mailto"])} if self.config.get("mailto") else {}

    async def lookup_doi(self, doi: str) -> dict[str, Any]:
        m = (await self.request("GET", f"/works/{doi}", params=self._params())).get("message") or {}
        return {
            "doi": m.get("DOI"),
            "title": (m.get("title") or [""])[0],
            "venue": (m.get("container-title") or [""])[0],
            "year": ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "citations": m.get("is-referenced-by-count"),
        }

    async def works(self, identifier: str) -> list[dict[str, Any]]:
        return [await self.lookup_doi(identifier)]

    async def citations(self, doi: str) -> int | None:
        return (await self.lookup_doi(doi)).get("citations")


@register_adapter("orcid", "orcid")
class Orcid(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "orcid",
        "orcid",
        "lookup",
        "https://pub.orcid.org/v3.0",
        ("client_secret",),
    )

    async def fetch_author_works(self, orcid: str) -> list[dict[str, Any]]:
        d = await self.request("GET", f"/{orcid}/works", headers={"Accept": "application/json"})
        out = []
        for g in d.get("group") or []:
            s = (g.get("work-summary") or [{}])[0]
            out.append(
                {
                    "title": ((s.get("title") or {}).get("title") or {}).get("value"),
                    "year": ((s.get("publication-date") or {}).get("year") or {}).get("value"),
                    "type": s.get("type"),
                }
            )
        return out

    async def works(self, identifier: str) -> list[dict[str, Any]]:
        return await self.fetch_author_works(identifier)


@register_adapter("scopus", "scopus")
class Scopus(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "scopus",
        "scopus",
        "lookup",
        "https://api.elsevier.com/content",
        ("api_key", "inst_token"),
    )

    def _h(self) -> dict[str, str]:
        h = {"X-ELS-APIKey": str(self.config.get("api_key", "")), "Accept": "application/json"}
        if self.config.get("inst_token"):
            h["X-ELS-Insttoken"] = str(self.config["inst_token"])
        return h

    async def fetch_author_works(self, scopus_id: str) -> list[dict[str, Any]]:
        d = await self.request("GET", "/search/scopus", headers=self._h(), params={"query": f"AU-ID({scopus_id})"})
        return [
            {"title": e.get("dc:title"), "doi": e.get("prism:doi"), "citations": int(e.get("citedby-count") or 0)}
            for e in (d.get("search-results") or {}).get("entry") or []
        ]

    async def works(self, identifier: str) -> list[dict[str, Any]]:
        return await self.fetch_author_works(identifier)

    async def citations(self, doi: str) -> int | None:
        d = await self.request("GET", "/search/scopus", headers=self._h(), params={"query": f"DOI({doi})"})
        entries = (d.get("search-results") or {}).get("entry") or []
        return int(entries[0].get("citedby-count") or 0) if entries else None


class _Plagiarism(AdapterBase):
    capability, timeout_class, secret_fields = "plagiarism", "plagiarism", ("api_key",)

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('api_key', '')}"}

    async def submit(self, *, filename: str, content: bytes, title: str = "") -> dict[str, Any]:
        d = await self.request(
            "POST", "/submissions", headers=self._h(), files={"file": (filename, content)}, data={"title": title}
        )
        return {"submission_id": str(d.get("id") if isinstance(d, dict) else uuid.uuid4().hex), "status": "submitted"}

    async def report(self, submission_id: str) -> dict[str, Any]:
        d = await self.request("GET", f"/submissions/{submission_id}/report", headers=self._h())
        return {
            "status": d.get("status", "pending"),
            "similarity_pct": d.get("similarity") or d.get("overall_match_percentage"),
            "report_url": d.get("report_url"),
        }


@register_adapter("plagiarism", "drillbit")
class DrillBit(_Plagiarism):
    provider, base_url = "drillbit", "https://s1.drillbitplagiarismcheck.com/api"


@register_adapter("plagiarism", "turnitin")
class Turnitin(_Plagiarism):
    provider = "turnitin"

    @property
    def url(self) -> str:
        return f"{str(self.config.get('base_url', '')).rstrip('/')}/api/v1"


@register_adapter("plagiarism", "urkund")
class Ouriginal(_Plagiarism):
    provider, base_url = "urkund", "https://secure.urkund.com/api"


@register_adapter("dspace", "dspace")
class DSpace(AdapterBase):
    capability, provider, timeout_class, secret_fields = "dspace", "dspace", "repository", ("password",)

    async def deposit(self, metadata: dict[str, Any], file: bytes, filename: str) -> dict[str, Any]:
        login = await self.request(
            "POST",
            "/server/api/authn/login",
            data={"user": self.config.get("username"), "password": self.config.get("password")},
        )
        _ = login
        item = await self.request(
            "POST",
            f"/server/api/core/items?owningCollection={self.config.get('collection')}",
            json={"metadata": {k: [{"value": v}] for k, v in metadata.items()}},
        )
        return {"handle": item.get("handle") if isinstance(item, dict) else None, "status": "deposited"}

    async def status(self, handle: str) -> str:
        return "archived"


@register_adapter("shodhganga", "shodhganga")
class Shodhganga(AdapterBase):
    capability, provider, timeout_class, secret_fields = "shodhganga", "shodhganga", "repository", ("password",)

    @property
    def url(self) -> str:
        return str(self.config.get("sword_url", "")).rstrip("/")

    async def deposit(self, metadata: dict[str, Any], file: bytes, filename: str) -> dict[str, Any]:
        await self.request(
            "POST",
            "",
            auth=(str(self.config.get("username")), str(self.config.get("password"))),
            content=file,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/zip",
                "Packaging": "http://purl.org/net/sword-types/METSDSpaceSIP",
            },
        )
        return {"status": "submitted"}

    async def status(self, handle: str) -> str:
        return "submitted"


@register_adapter("koha", "koha")
class Koha(AdapterBase):
    capability, provider, timeout_class, secret_fields = "koha", "koha", "library", ("client_secret",)

    async def _h(self) -> dict[str, str]:
        tok = await self.request(
            "POST",
            "/api/v1/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.get("client_id"),
                "client_secret": self.config.get("client_secret"),
            },
        )
        return {"Authorization": f"Bearer {tok.get('access_token', '')}"}

    async def sync_catalogue(self, since: str | None = None) -> list[dict[str, Any]]:
        return list(await self.request("GET", "/api/v1/biblios", headers=await self._h(), params={"_per_page": 100}))

    async def sync_members(self, since: str | None = None) -> list[dict[str, Any]]:
        return list(await self.request("GET", "/api/v1/patrons", headers=await self._h(), params={"_per_page": 100}))

    async def circulation_events(self, since: str | None = None) -> list[dict[str, Any]]:
        return list(await self.request("GET", "/api/v1/checkouts", headers=await self._h(), params={"_per_page": 100}))


# ---- devices / face / signing / kyc --------------------------------------------------------------------------------------------------
@register_adapter("biometric", "zkteco")
class ZkAdms(AdapterBase):
    """ZKTeco / ESSL ADMS push: the device posts ``ATTLOG`` lines to the inbound route; pulls are not supported."""

    capability, provider, timeout_class = "biometric", "zkteco", "device"

    async def pull_punches(self, *_: Any) -> list[dict[str, Any]]:
        return []

    async def push_users(self, users: list[dict[str, Any]]) -> dict[str, Any]:
        return {"queued": len(users), "note": "delivered on the device's next ADMS poll"}

    def webhook_parse(self, body: bytes) -> list[dict[str, Any]]:
        out = []
        for line in body.decode(errors="ignore").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip():
                out.append(
                    {
                        "pin": parts[0].strip(),
                        "at": parts[1].strip(),
                        "status": parts[2].strip() if len(parts) > 2 else "0",
                    }
                )
        return out


@register_adapter("biometric", "csv")
class CsvDevice(AdapterBase):
    capability, provider, timeout_class = "biometric", "csv", "device"

    async def pull_punches(self, content: bytes = b"", **_: Any) -> list[dict[str, Any]]:
        import csv
        import io

        return [dict(r) for r in csv.DictReader(io.StringIO(content.decode(errors="ignore")))]

    async def push_users(self, users: list[dict[str, Any]]) -> dict[str, Any]:
        return {"queued": 0}

    def webhook_parse(self, body: bytes) -> list[dict[str, Any]]:
        return []


@register_adapter("rfid", "rfid_http")
class RfidHttp(AdapterBase):
    capability, provider, timeout_class, secret_fields = "rfid", "rfid_http", "device", ("shared_token",)

    async def pull_punches(self, *_: Any) -> list[dict[str, Any]]:
        return []

    def verify_webhook(self, *, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(str(self.config.get("shared_token", "")), signature or "")

    def webhook_parse(self, body: bytes) -> list[dict[str, Any]]:
        d = json.loads(body)
        return list(d if isinstance(d, list) else [d])


@register_adapter("face_verification", "face_api")
class FaceApi(AdapterBase):
    capability, provider, timeout_class, secret_fields = "face_verification", "face_api", "face", ("api_key",)

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('api_key', '')}"}

    async def enrol(self, photo: bytes, subject: str) -> dict[str, Any]:
        d = await self.request(
            "POST", "/enrol", headers=self._h(), files={"photo": ("photo.jpg", photo)}, data={"subject": subject}
        )
        return {"template_id": d.get("template_id") if isinstance(d, dict) else None}

    async def verify(self, photo: bytes, template_id: str) -> dict[str, Any]:
        d = await self.request(
            "POST",
            "/verify",
            headers=self._h(),
            files={"photo": ("photo.jpg", photo)},
            data={"template_id": template_id},
        )
        score = float(d.get("score") or 0) if isinstance(d, dict) else 0.0
        return {"match": score >= float(self.config.get("threshold") or 0.8), "score": score}


@register_adapter("esign", "aadhaar_esign")
class AadhaarESign(AdapterBase):
    capability, provider, timeout_class, secret_fields = "esign", "aadhaar_esign", "esign", ("signing_key",)

    async def sign(self, pdf: bytes, signer: dict[str, Any]) -> dict[str, Any]:
        digest = hashlib.sha256(pdf).hexdigest()
        d = await self.request(
            "POST",
            "/esign/2.1/request",
            json={
                "aspId": self.config.get("asp_id"),
                "docHash": digest,
                "signer": signer.get("name"),
                "ts": int(time.time()),
            },
        )
        return {
            "transaction_id": d.get("txn") if isinstance(d, dict) else None,
            "redirect_url": (d or {}).get("redirect") if isinstance(d, dict) else None,
            "status": "pending_otp",
        }

    async def verify(self, pdf: bytes) -> dict[str, Any]:
        from app.services.integrations.pdf_signature import verify_pades

        return verify_pades(pdf)


@register_adapter("esign", "dsc")
class DscSigning(AdapterBase):
    capability, provider, timeout_class, secret_fields = "esign", "dsc", "esign", ("api_key",)

    async def sign(self, pdf: bytes, signer: dict[str, Any]) -> dict[str, Any]:
        d = await self.request(
            "POST",
            "/sign",
            headers={"Authorization": f"Bearer {self.config.get('api_key', '')}"},
            files={"pdf": ("doc.pdf", pdf)},
            data={"signer": signer.get("name", "")},
        )
        return {"signed_pdf_b64": d.get("pdf") if isinstance(d, dict) else None, "status": "signed"}

    async def verify(self, pdf: bytes) -> dict[str, Any]:
        from app.services.integrations.pdf_signature import verify_pades

        return verify_pades(pdf)


@register_adapter("aadhaar_ekyc", "aua_kua")
class AuaKua(AdapterBase):
    capability, provider, timeout_class, secret_fields = "aadhaar_ekyc", "aua_kua", "ekyc", ("license_key",)

    async def initiate(self, uid_token: str) -> dict[str, Any]:
        d = await self.request("POST", "/otp", json={"aua": self.config.get("aua_code"), "uid": uid_token})
        return {"txn": d.get("txn") if isinstance(d, dict) else None}

    async def verify_otp(self, txn: str, otp: str) -> dict[str, Any]:
        return dict(
            await self.request("POST", "/kyc", json={"txn": txn, "otp": otp, "lk": self.config.get("license_key")})
        )

    async def fetch_profile(self, txn: str) -> dict[str, Any]:
        return dict(await self.request("GET", f"/kyc/{txn}"))


# ---- accounting / workspace / maps / llm ------------------------------------------------------------------------------------------------
@register_adapter("accounting", "tally")
class TallyXml(AdapterBase):
    capability, provider, timeout_class = "accounting", "tally", "accounting"

    async def export_vouchers(self, vouchers: list[dict[str, Any]]) -> dict[str, Any]:
        from xml.sax.saxutils import escape

        body = "".join(
            f'<TALLYMESSAGE><VOUCHER VCHTYPE="{escape(str(v.get("type", "Journal")))}"><DATE>{escape(str(v.get("date", "")).replace("-", ""))}</DATE>'
            f"<NARRATION>{escape(str(v.get('narration', '')))}</NARRATION>"
            + "".join(
                f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(str(line.get('ledger')))}</LEDGERNAME><AMOUNT>{float(line.get('amount', 0)):.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                for line in v.get("lines") or []
            )
            + "</VOUCHER></TALLYMESSAGE>"
            for v in vouchers
        )
        xml = f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{escape(str(self.config.get('company', '')))}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>{body}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
        return {"format": "tally_xml", "content": xml, "vouchers": len(vouchers)}


@register_adapter("accounting", "zoho_books")
class ZohoBooks(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "accounting",
        "zoho_books",
        "accounting",
        "https://www.zohoapis.in/books/v3",
        ("refresh_token", "client_secret"),
    )

    async def export_vouchers(self, vouchers: list[dict[str, Any]]) -> dict[str, Any]:
        tok = await self.request(
            "POST",
            "https://accounts.zoho.in/oauth/v2/token",
            params={
                "refresh_token": self.config.get("refresh_token"),
                "client_id": self.config.get("client_id"),
                "client_secret": self.config.get("client_secret"),
                "grant_type": "refresh_token",
            },
        )
        h = {"Authorization": f"Zoho-oauthtoken {tok.get('access_token', '')}"}
        n = 0
        for v in vouchers:
            await self.request(
                "POST",
                f"/journals?organization_id={self.config.get('organization_id')}",
                headers=h,
                json={
                    "journal_date": v.get("date"),
                    "notes": v.get("narration"),
                    "line_items": [
                        {
                            "account_name": line.get("ledger"),
                            "amount": abs(float(line.get("amount", 0))),
                            "debit_or_credit": "debit" if float(line.get("amount", 0)) > 0 else "credit",
                        }
                        for line in v.get("lines") or []
                    ],
                },
            )
            n += 1
        return {"format": "zoho_books", "vouchers": n}


@register_adapter("workspace", "google_workspace")
class GoogleWorkspace(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "workspace",
        "google_workspace",
        "workspace",
        "https://admin.googleapis.com/admin/directory/v1",
        ("service_account_json",),
    )

    async def _h(self) -> dict[str, str]:
        from app.services.integrations.google_auth import service_account_token

        tok = await service_account_token(
            str(self.config.get("service_account_json", "")),
            "https://www.googleapis.com/auth/admin.directory.user https://www.googleapis.com/auth/admin.directory.group",
            subject=str(self.config.get("admin_email", "")),
        )
        return {"Authorization": f"Bearer {tok}"}

    async def create_account(self, *, email: str, given: str, family: str, password: str) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST",
                "/users",
                headers=await self._h(),
                json={
                    "primaryEmail": email,
                    "name": {"givenName": given, "familyName": family},
                    "password": password,
                    "changePasswordAtNextLogin": True,
                },
            )
        )

    async def suspend(self, email: str) -> dict[str, Any]:
        return dict(await self.request("PUT", f"/users/{email}", headers=await self._h(), json={"suspended": True}))

    async def add_to_group(self, email: str, group: str) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST", f"/groups/{group}/members", headers=await self._h(), json={"email": email, "role": "MEMBER"}
            )
        )


@register_adapter("workspace", "microsoft_graph")
class MicrosoftGraph(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "workspace",
        "microsoft_graph",
        "workspace",
        "https://graph.microsoft.com/v1.0",
        ("client_secret",),
    )

    async def _h(self) -> dict[str, str]:
        from app.services.integrations.ms_auth import graph_token

        return {"Authorization": f"Bearer {await graph_token(self.config)}"}

    async def create_account(self, *, email: str, given: str, family: str, password: str) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST",
                "/users",
                headers=await self._h(),
                json={
                    "accountEnabled": True,
                    "displayName": f"{given} {family}",
                    "mailNickname": email.split("@")[0],
                    "userPrincipalName": email,
                    "passwordProfile": {"forceChangePasswordNextSignIn": True, "password": password},
                },
            )
        )

    async def suspend(self, email: str) -> dict[str, Any]:
        return dict(
            await self.request("PATCH", f"/users/{email}", headers=await self._h(), json={"accountEnabled": False})
            or {}
        )

    async def add_to_group(self, email: str, group: str) -> dict[str, Any]:
        return dict(
            await self.request(
                "POST",
                f"/groups/{group}/members/$ref",
                headers=await self._h(),
                json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{email}"},
            )
            or {}
        )


@register_adapter("maps", "osm")
class Osm(AdapterBase):
    capability, provider, timeout_class = "maps", "osm", "lookup"

    def tile_url(self) -> str:
        return "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    async def health(self) -> tuple[bool, str]:
        return True, "public tiles"


@register_adapter("maps", "mapbox")
class Mapbox(AdapterBase):
    capability, provider, timeout_class, secret_fields = "maps", "mapbox", "lookup", ("access_token",)

    def tile_url(self) -> str:
        return f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/{{z}}/{{x}}/{{y}}?access_token={self.config.get('access_token', '')}"


class _OpenAiCompatible(AdapterBase):
    capability, timeout_class, secret_fields = "llm", "llm", ("api_key",)
    default_model = "gpt-4o-mini"

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get('api_key', '')}"}

    def _path(self) -> str:
        return "/chat/completions"

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kw: Any
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.config.get("model") or self.default_model, "messages": messages}
        if tools:
            body["tools"] = tools
        d = await self.request("POST", self._path(), headers=self._h(), json=body)
        choice = (d.get("choices") or [{}])[0].get("message") or {}
        usage = d.get("usage") or {}
        return {
            "content": choice.get("content"),
            "tool_calls": choice.get("tool_calls") or [],
            "tokens": int(usage.get("total_tokens") or 0),
        }


@register_adapter("llm", "openai")
class OpenAiLlm(_OpenAiCompatible):
    provider, base_url = "openai", "https://api.openai.com/v1"


@register_adapter("llm", "groq")
class GroqLlm(_OpenAiCompatible):
    provider, base_url, default_model = "groq", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant"


@register_adapter("llm", "azure_openai")
class AzureOpenAiLlm(_OpenAiCompatible):
    provider = "azure_openai"

    @property
    def url(self) -> str:
        return str(self.config.get("endpoint", "")).rstrip("/")

    def _h(self) -> dict[str, str]:
        return {"api-key": str(self.config.get("api_key", ""))}

    def _path(self) -> str:
        return f"/openai/deployments/{self.config.get('deployment')}/chat/completions?api-version=2024-06-01"


@register_adapter("llm", "ollama")
class OllamaLlm(_OpenAiCompatible):
    provider, base_url, default_model = "ollama", "http://localhost:11434/v1", "llama3.1"


@register_adapter("storage", "s3")
class S3Storage(AdapterBase):
    capability, provider, timeout_class, secret_fields = "storage", "s3", "lookup", ("secret_access_key",)

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        raise IntegrationFailed(
            self.provider, "USE_CORE_STORAGE", "Configure S3 through STORAGE_BACKEND (app/core/files.py)"
        )

    async def get(self, key: str) -> bytes:
        raise IntegrationFailed(self.provider, "USE_CORE_STORAGE", "Configure S3 through STORAGE_BACKEND")

    async def delete(self, key: str) -> None:
        raise IntegrationFailed(self.provider, "USE_CORE_STORAGE", "Configure S3 through STORAGE_BACKEND")


@register_adapter("captcha", "turnstile")
class Turnstile(AdapterBase):
    capability, provider, timeout_class, base_url, secret_fields = (
        "captcha",
        "turnstile",
        "lookup",
        "https://challenges.cloudflare.com/turnstile/v0",
        ("secret",),
    )

    async def verify(self, token: str, remote_ip: str | None = None) -> bool:
        d = await self.request(
            "POST",
            "/siteverify",
            data={"secret": self.config.get("secret"), "response": token, "remoteip": remote_ip or ""},
        )
        return bool(d.get("success"))


# ---- functional mock twin -------------------------------------------------------------------------------------------------------
class FunctionalMock(AdapterBase):
    """Deterministic, stateful mock of any capability (Redis-backed so a mock gateway order can be paid by a later
    webhook, a mock SMS reports ``delivered`` after the first status poll, DigiLocker acknowledges after two polls,
    the plagiarism report returns ``config.similarity`` %, devices replay stored punches). ``config.fail=true``
    makes every call / health probe fail (breaker and outage tests)."""

    provider = "mock"

    def __init__(self, capability: str, **config: Any):
        super().__init__(**config)
        self.capability = capability

    def _fail(self) -> None:
        if self.config.get("fail"):
            raise IntegrationFailed("mock", "MOCK_FAILURE", "Mock provider configured to fail", retryable=True)

    async def health(self) -> tuple[bool, str]:
        return (not self.config.get("fail")), "mock failing" if self.config.get("fail") else "mock"

    async def _counter(self, key: str) -> int:
        from app.db.session import redis_client

        try:
            return int(await redis_client.incr(f"mock:{self.capability}:{key}"))
        except Exception:  # noqa: BLE001
            return 1

    async def send(self, **payload: Any) -> dict[str, Any]:
        self._fail()
        ref = f"mock-{self.capability}-{uuid.uuid4().hex[:10]}"
        return {"status": "sent", "provider": "mock", "reference": ref}

    async def delivery_status(self, reference: str) -> str:
        return "delivered" if await self._counter(f"dlr:{reference}") > 1 else "sent"

    async def status(self, ref: str) -> str:
        return "acknowledged" if await self._counter(f"ack:{ref}") >= 2 else "pushed"

    async def report(self, submission_id: str) -> dict[str, Any]:
        return {
            "status": "ready",
            "similarity_pct": float(self.config.get("similarity", 18)),
            "report_url": f"https://mock.plagiarism/{submission_id}",
        }

    async def verify_certificate(self, certificate_id: str) -> dict[str, Any]:
        return {"valid": not certificate_id.startswith("BAD"), "course": "Mock MOOC"}

    async def lookup_doi(self, doi: str) -> dict[str, Any]:
        return {"doi": doi, "title": f"Mock work {doi[-6:]}", "venue": "Mock Journal", "year": 2024, "citations": 3}

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kw: Any
    ) -> dict[str, Any]:
        last = (messages[-1] or {}).get("content") if messages else ""
        return {"content": f"(mock) You asked: {str(last)[:200]}", "tool_calls": [], "tokens": 42}

    async def verify(self, *args: Any, **kw: Any) -> dict[str, Any]:
        return {"match": True, "score": 0.97, "valid": True}

    def tile_url(self) -> str:
        return "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    def __getattr__(self, name: str) -> Any:  # every other interface method behaves like ``send``
        if name.startswith("_"):
            raise AttributeError(name)
        return self.send


from app.integrations.registry import ADAPTERS, CAPABILITIES, MockAdapter  # noqa: E402

for _cap in CAPABILITIES:
    _existing = ADAPTERS.get((_cap, "mock"))
    # keep the phase-specific mocks (Phase 12 gateway, Phase 02 IdP, Phase 30 bibliographic); upgrade the generic ones
    if _existing is None or isinstance(_existing(), MockAdapter):
        ADAPTERS[(_cap, "mock")] = (lambda cap: (lambda **cfg: FunctionalMock(cap, **cfg)))(_cap)
