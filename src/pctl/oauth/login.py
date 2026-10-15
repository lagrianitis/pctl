"""Action: `pctl oauth login`, the authorization code flow with PKCE for people."""

from __future__ import annotations

import click

from ..config import AppContext, OAuthConfig
from ..errors import ConfigError
from ..options import oauth_login_options, oauth_options, output_options
from ..tokencache import CachedToken
from .browser import (
    authorize_url,
    check_redirect,
    is_loopback,
    new_pkce,
    open_browser,
    parse_redirect,
)
from .client import OAuthClient
from .common import Display, display_options, emit, token_record

PASTE_PROMPT = "After login, paste the full address from the browser (or just the code)"


@click.command(name="login")
@oauth_options
@oauth_login_options
@display_options
@output_options
@click.pass_context
def command(ctx: click.Context, raw: bool, decode: bool) -> None:
    """Log in through the browser and fetch a user access token.

    For people: opens the provider's login page, then exchanges the code it returns for a
    token, using PKCE so an intercepted code is useless. Nothing is written to disk, the
    token and any refresh token included.

    With a loopback redirect, pctl catches the browser's return itself. With any other
    registered redirect, the browser lands on a page you do not control: copy the address
    from the address bar, even if the page shows an error, and paste it back here.

    The token is masked by default. --raw prints it verbatim.

    \b
      pctl oauth login --issuer https://idp.example.com --client-id ID \\
          --redirect-uri http://127.0.0.1:8765/callback
      pctl oauth login --raw --audience https://api.example.com
    """
    app = ctx.ensure_object(AppContext)
    config = app.oauth()
    with OAuthClient(config, timeout=app.timeout, log=app.log) as client:
        token = _authenticate(client, config)
    emit(app, token_record(config, token, "authorization_code"), Display(raw, decode))


def _authenticate(client: OAuthClient, config: OAuthConfig) -> CachedToken:
    """Run the flow: send the user to the provider, read the code, and trade it."""
    redirect = _require_redirect(config)
    pkce = new_pkce()
    url = authorize_url(client.endpoints(authorize=True).authorize_url or "", config, pkce)
    if is_loopback(redirect):
        from .loopback import wait_for_redirect

        params = wait_for_redirect(redirect, config.login_timeout, lambda: open_browser(url))
        code = check_redirect(params, pkce.state, require_state=True)
    else:
        open_browser(url)
        pasted = parse_redirect(click.prompt(PASTE_PROMPT, err=True))
        code = check_redirect(pasted, pkce.state, require_state=False)
    return client.exchange_code(code, pkce.verifier)


def _require_redirect(config: OAuthConfig) -> str:
    if not config.redirect_uri:
        raise ConfigError(
            "Missing redirect URI. Set OAUTH_REDIRECT_URI or pass --redirect-uri; "
            "it must be one registered on the client."
        )
    return config.redirect_uri
