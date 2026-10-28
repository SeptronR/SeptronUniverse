"""Microsoft identity platform client-credentials token for Graph (Teams / workspace) — Prompts/41 §41.6."""

from typing import Any

from app.integrations.base import IntegrationFailed


async def graph_token(config: dict[str, Any]) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"https://login.microsoftonline.com/{config.get('tenant')}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.get("client_id"),
                "client_secret": config.get("client_secret"),
                "scope": "https://graph.microsoft.com/.default",
            },
        )
    if r.status_code != 200:
        raise IntegrationFailed("microsoft", f"HTTP_{r.status_code}", "Microsoft token request failed")
    return str(r.json()["access_token"])
