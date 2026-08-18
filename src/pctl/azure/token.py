"""Action: `pctl azure token`. A case-level action, so it has no service package."""

from __future__ import annotations

from typing import Any

import click

from ..config import AppContext
from ..options import azure_options, output_options
from ..output import Renderer
from . import graph_client


@click.command(name="token")
@azure_options
@click.option("--raw", is_flag=True, help="Print only the bearer token, unmasked.")
@click.option("--decode", is_flag=True, help="Show the token's claims (no signature check).")
@click.option("--clear-cache", is_flag=True, help="Delete all cached tokens and exit.")
@output_options
@click.pass_context
def command(ctx: click.Context, raw: bool, decode: bool, clear_cache: bool) -> None:
    """Acquire an access token for Microsoft Graph.

    The token is masked by default. --raw prints it verbatim, which is handy for
    curl -H "Authorization: Bearer $(pctl azure token --raw)", but treat that
    output as a secret.
    """
    app = ctx.ensure_object(AppContext)
    if clear_cache:
        from ..tokencache import clear_all

        removed = clear_all()
        click.echo(f"Cleared {removed} cached token{'' if removed == 1 else 's'}.", err=True)
        return

    from .graph import run

    async def _run() -> dict[str, Any]:
        async with graph_client(app) as client:
            cached = await client.token()
            config = client.config
            record: dict[str, Any] = {
                "tenantId": config.tenant_id,
                "clientId": config.client_id,
                "scope": config.scope,
                "expiresInSeconds": cached.expires_in,
                "accessToken": cached.access_token if raw else _mask(cached.access_token),
            }
            if decode:
                record["claims"] = _decode_claims(cached.access_token)
            return record

    record = run(_run())
    if raw and not decode:
        click.echo(record["accessToken"])
        return
    with Renderer(app.output, single=True) as renderer:
        renderer.write(record)


def _mask(token: str) -> str:
    return f"{token[:8]}…{token[-6:]} ({len(token)} chars)" if len(token) > 20 else "…"


def _decode_claims(token: str) -> dict[str, Any]:
    """Decode the JWT payload for inspection. The signature is NOT verified."""
    import base64

    import orjson

    parts = token.split(".")
    if len(parts) < 2:
        return {"error": "not a JWT"}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = orjson.loads(base64.urlsafe_b64decode(payload))
    except ValueError, orjson.JSONDecodeError:
        return {"error": "could not decode payload"}
    return claims if isinstance(claims, dict) else {"value": claims}
