"""What the `oauth` actions share: the token record, and how it is shown.

Both `token` and `login` end the same way, with a token that is masked unless `--raw` is
passed and claims that are shown on request. Keeping that here means the two cannot
disagree about what counts as leaking a token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import click

from ..config import AppContext, OAuthConfig
from ..jwt import decode_claims, mask
from ..output import Renderer
from ..tokencache import CachedToken


@dataclass(slots=True, frozen=True)
class Display:
    """How the caller asked to see the token."""

    raw: bool
    decode: bool


def display_options(func: Any) -> Any:
    """Add `--raw` and `--decode`, which both actions offer in the same words."""
    func = click.option(
        "--decode", is_flag=True, help="Show the token's claims (no signature check)."
    )(func)
    return click.option("--raw", is_flag=True, help="Print only the access token, unmasked.")(func)


def token_record(config: OAuthConfig, token: CachedToken, flow: str) -> dict[str, Any]:
    """Describe a token without choosing yet whether to reveal it."""
    return {
        "flow": flow,
        "clientId": config.client_id,
        "audience": config.audience,
        "scope": config.scope,
        "expiresInSeconds": token.expires_in,
        "accessToken": token.access_token,
    }


def emit(app: AppContext, record: dict[str, Any], display: Display) -> None:
    """Write the record, masking the token unless `--raw` asked for it bare.

    `--raw` alone prints the token and nothing else, so it can sit inside
    `$(...)`. With `--decode` as well there is more to say, so the record is written.
    """
    token = str(record["accessToken"])
    if display.decode:
        record["claims"] = decode_claims(token)
    if display.raw and not display.decode:
        click.echo(token)
        return
    if not display.raw:
        record["accessToken"] = mask(token)
    with Renderer(app.output, single=True) as renderer:
        renderer.write(record)
