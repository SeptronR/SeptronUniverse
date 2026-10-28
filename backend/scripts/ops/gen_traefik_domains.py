"""Generate the Traefik dynamic configuration for verified custom domains (Prompts/44 §44.6 docker 4).

Cron every 5 minutes on the edge host:
    EDGE_TOKEN=… python gen_traefik_domains.py --api https://api.septronuniverse.in --out /etc/traefik/dynamic/universe-domains.yml
Reads Phase 40 ``GET /api/v1/internal/domains`` (``X-Edge-Token``) and writes one router per host (ACME HTTP challenge,
``universe-web`` service, security-headers middleware). The file is replaced atomically; Traefik watches it.
"""

import argparse
import json
import os
import tempfile
import urllib.request
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    req = urllib.request.Request(f"{a.api}/api/v1/internal/domains", headers={"X-Edge-Token": os.environ["EDGE_TOKEN"]})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed https API URL from the operator
        data = json.load(r).get("data") or []
    lines = ["http:", "  routers:"]
    for d in data:
        host = d["hostname"]
        name = "site-" + host.replace(".", "-")
        lines += [f"    {name}:", f"      rule: \"Host(`{host}`)\"", "      service: universe-api@docker", "      entryPoints: [websecure]",
                  "      middlewares: [universe-headers@file]", "      tls: { certResolver: letsencrypt }"]
    if not data:
        lines = ["http: {}"]
    out = Path(a.out)
    with tempfile.NamedTemporaryFile("w", dir=out.parent, delete=False) as tmp:
        tmp.write("\n".join(lines) + "\n")
    os.replace(tmp.name, out)
    print(f"{len(data)} custom domain router(s) → {out}")  # noqa: T201


if __name__ == "__main__":
    main()
