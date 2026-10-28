"""Per-tenant sending-domain authentication (``integrations.email_domain_auth``) — Prompts/41 §41.6 EmailProvider.

DNS records to publish (SPF include, DKIM selector CNAME / TXT, DMARC) per provider; verification resolves them with
``dnspython`` when installed (else the development resolver Redis ``dns:txt:<name>``, as Phase 40 domains). Until a
domain verifies the platform domain sends "on behalf of" the institution.
"""

from typing import Any

SPF = {"sendgrid": "include:sendgrid.net", "ses": "include:amazonses.com", "smtp": "a mx"}


def dns_records(domain: str, provider: str) -> list[dict[str, str]]:
    return [
        {"type": "TXT", "name": domain, "value": f"v=spf1 {SPF.get(provider, 'a mx')} ~all"},
        {"type": "CNAME", "name": f"s1._domainkey.{domain}", "value": f"s1.domainkey.{provider}.septron.in"},
        {"type": "TXT", "name": f"_dmarc.{domain}", "value": "v=DMARC1; p=none; rua=mailto:dmarc@septron.in"},
    ]


async def verify(domain: str, provider: str) -> dict[str, Any]:
    from app.services.website.domain_service import lookup_txt

    spf = await lookup_txt(domain)
    dmarc = await lookup_txt(f"_dmarc.{domain}")
    ok_spf = any("v=spf1" in r and SPF.get(provider, "") in r for r in spf)
    ok_dmarc = any("v=DMARC1" in r for r in dmarc)
    return {"domain": domain, "spf": ok_spf, "dmarc": ok_dmarc, "verified": ok_spf and ok_dmarc}
