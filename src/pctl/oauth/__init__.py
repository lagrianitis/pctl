"""The `oauth` case: a JWT from any OAuth 2.0 provider.

Two case-level actions and no services, like `azure token`: there is nothing to list or
get, only a token to fetch. `token` is for machines, using the client credentials grant.
`login` is for people, opening a browser for the authorization code flow with PKCE.

Subcommands are declared as import strings so `pctl oauth --help` imports nothing heavy.
"""

from __future__ import annotations

import click

from ..config import AppContext
from ..lazy import PctlGroup

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "token": (
        "pctl.oauth.token:command",
        "Fetch a token with client credentials, for machines.",
    ),
    "login": (
        "pctl.oauth.login:command",
        "Log in through the browser and fetch a user token.",
    ),
}


@click.group(
    name="oauth",
    cls=PctlGroup,
    lazy_subcommands=LAZY_SUBCOMMANDS,
    context_settings=CONTEXT_SETTINGS,
)
@click.pass_context
def oauth(ctx: click.Context) -> None:
    """OAuth 2.0: fetch a JWT from Auth0, Okta, Keycloak or any compatible provider.

    \b
    Every setting is a flag and an environment variable. A flag wins:
      --issuer          OAUTH_ISSUER          discover the endpoints from here
      --token-url       OAUTH_TOKEN_URL       or name the token endpoint directly
      --client-id       OAUTH_CLIENT_ID
      --client-secret   OAUTH_CLIENT_SECRET   prefer the variable: a flag is in your history
      --audience        OAUTH_AUDIENCE
      --scope           OAUTH_SCOPE
      --secret-id       PCTL_OAUTH_SECRET_ID  read the client from AWS Secrets Manager

    \b
    Browser login (login) also takes:
      --authorize-url   OAUTH_AUTHORIZE_URL   or discovered from --issuer
      --redirect-uri    OAUTH_REDIRECT_URI    must be registered on the client
      --login-timeout   OAUTH_LOGIN_TIMEOUT   seconds to wait for the browser
    """
    ctx.ensure_object(AppContext)


__all__ = ["CONTEXT_SETTINGS", "LAZY_SUBCOMMANDS", "oauth"]
