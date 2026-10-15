"""Action: `pctl oauth token`, the client credentials grant for machines."""

from __future__ import annotations

import click

from ..config import AppContext
from ..options import oauth_cache_option, oauth_options, output_options
from .client import OAuthClient
from .common import Display, display_options, emit, token_record


@click.command(name="token")
@oauth_options
@oauth_cache_option
@display_options
@output_options
@click.pass_context
def command(ctx: click.Context, raw: bool, decode: bool) -> None:
    """Fetch an access token with the client credentials grant.

    For machines: the client id and secret are exchanged for a token, with no browser and
    no user. The token is masked by default. --raw prints it verbatim, which is what
    curl -H "Authorization: Bearer $(pctl oauth token --raw)" needs, but treat that
    output as a secret. A valid token is cached on disk until it expires.

    Every setting is a flag and an environment variable, and the flag wins.

    \b
      pctl oauth token --issuer https://idp.example.com \\
          --client-id abc --audience https://api.example.com
      OAUTH_CLIENT_SECRET=... pctl oauth token --raw
    """
    app = ctx.ensure_object(AppContext)
    config = app.oauth()
    config.require_client_secret()
    with OAuthClient(config, timeout=app.timeout, log=app.log) as client:
        token = client.client_credentials()
    emit(app, token_record(config, token, "client_credentials"), Display(raw, decode))
