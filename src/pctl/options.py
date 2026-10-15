"""Reusable click options.

Every option here uses `expose_value=False` with a callback that writes into the
shared `AppContext`. That keeps command signatures short and lets the same flags be
accepted at group level and on each leaf command: `pctl -o json azure groups list`
and `pctl azure groups list -o json` both work, with the leaf value winning because
its callback runs later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import click

from .config import AppContext, OutputFormat

OUTPUT_CHOICES = [fmt.value for fmt in OutputFormat]

# Shorter than this and a login could not finish before the wait gave up.
MIN_LOGIN_TIMEOUT = 0.1


def _set_attr(name: str, transform: Callable[[Any], Any] | None = None) -> Callable[..., Any]:
    """Build a click callback that stores a non-None value on the AppContext."""

    def callback(ctx: click.Context, _param: click.Parameter, value: Any) -> Any:
        if value is None:
            return value
        app = ctx.ensure_object(AppContext)
        setattr(app, name, transform(value) if transform else value)
        return value

    return callback


def _set_cred(ctx: click.Context, param: click.Parameter, value: Any) -> Any:
    """Collect credential-ish options into `AppContext.creds`."""
    if value is None or value is False:
        return value
    app = ctx.ensure_object(AppContext)
    app.creds[str(param.name)] = value
    return value


def split_columns(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def output_options(func: Any) -> Any:
    """Add `-o/--output`, `-q/--quiet` and `-v/--verbose`."""
    func = click.option(
        "-v",
        "--verbose",
        is_flag=True,
        default=None,
        expose_value=False,
        callback=_set_attr("verbose"),
        help="Log progress to stderr.",
    )(func)
    func = click.option(
        "-q",
        "--quiet",
        is_flag=True,
        default=None,
        expose_value=False,
        callback=_set_attr("quiet"),
        help="Suppress the result summary on stderr.",
    )(func)
    func = click.option(
        "-o",
        "--output",
        type=click.Choice(OUTPUT_CHOICES),
        default=None,
        expose_value=False,
        callback=_set_attr("output", OutputFormat),
        metavar="FORMAT",
        help="Output format: table, json, ndjson or csv.  [default: table]",
    )(func)
    return func


def columns_option(func: Any) -> Any:
    """Add `-c/--columns` for table and csv output."""
    return click.option(
        "-c",
        "--columns",
        default=None,
        expose_value=False,
        callback=_set_attr("columns", split_columns),
        metavar="COLS",
        help="Comma-separated columns for table/csv output.",
    )(func)


def azure_options(func: Any) -> Any:
    """Add Microsoft Graph credential options.

    A client secret is deliberately not accepted as a flag: pass it through
    AZURE_CLIENT_SECRET or keep it in Secrets Manager and use --secret-id.
    """
    func = click.option(
        "--no-token-cache",
        is_flag=True,
        default=None,
        expose_value=False,
        callback=_set_cred,
        help="Do not read or write the on-disk token cache.",
    )(func)
    func = click.option(
        "--secret-region",
        metavar="REGION",
        default=None,
        expose_value=False,
        callback=_set_cred,
        help="Region holding the secret.  [default: eu-central-1]",
    )(func)
    func = click.option(
        "--secret-id",
        metavar="NAME",
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar="PCTL_AZURE_SECRET_ID",
        help="Read client_id/client_secret from an AWS Secrets Manager JSON secret "
        "(e.g. azuread-client).  [env: PCTL_AZURE_SECRET_ID]",
    )(func)
    func = click.option(
        "--scope",
        metavar="SCOPE",
        default=None,
        expose_value=False,
        callback=_set_cred,
        help="OAuth scope.  [default: https://graph.microsoft.com/.default]",
    )(func)
    func = click.option(
        "--client-id",
        metavar="ID",
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar="AZURE_CLIENT_ID",
        help="App registration (client) id.  [env: AZURE_CLIENT_ID]",
    )(func)
    func = click.option(
        "--tenant-id",
        metavar="ID",
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar="AZURE_TENANT_ID",
        help="Tenant GUID or domain, e.g. contoso.onmicrosoft.com.  [env: AZURE_TENANT_ID]",
    )(func)
    return func


def aws_options(func: Any) -> Any:
    """Add AWS session options."""
    func = click.option(
        "--endpoint-url",
        metavar="URL",
        default=None,
        expose_value=False,
        callback=_set_cred,
        help="Override the service endpoint, e.g. http://localhost:8000.",
    )(func)
    func = click.option(
        "--region",
        metavar="REGION",
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar="AWS_REGION",
        help="AWS region.  [env: AWS_REGION]",
    )(func)
    func = click.option(
        "--profile",
        metavar="NAME",
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar="AWS_PROFILE",
        help="Shared-config profile.  [env: AWS_PROFILE]",
    )(func)
    return func


@dataclass(frozen=True, slots=True)
class _CredOption:
    """One setting that can be given as a flag or as an environment variable."""

    flag: str
    metavar: str
    envvar: str
    text: str


def _cred_option(spec: _CredOption, **extra: Any) -> Any:
    """Build the click option for a setting and store its value in `AppContext.creds`.

    Giving the variable to click as `envvar` is what makes a flag win over it: click
    consults the command line first and the variable only when the flag is absent.
    """
    return click.option(
        spec.flag,
        metavar=spec.metavar,
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar=spec.envvar,
        help=f"{spec.text}  [env: {spec.envvar}]",
        **extra,
    )


# Declared as data because the `oauth` commands take a dozen settings, each available as
# a flag and as a variable.
_OAUTH_OPTIONS = [
    _CredOption(
        "--issuer",
        "URL",
        "OAUTH_ISSUER",
        "Provider base URL. The endpoints are <issuer>/oauth/token and <issuer>/authorize "
        "unless the two URL options below name them.",
    ),
    _CredOption(
        "--token-url", "URL", "OAUTH_TOKEN_URL", "Token endpoint, instead of <issuer>/oauth/token."
    ),
    _CredOption("--client-id", "ID", "OAUTH_CLIENT_ID", "OAuth client id."),
    _CredOption(
        "--client-secret",
        "SECRET",
        "OAUTH_CLIENT_SECRET",
        "Client secret. A flag lands in shell history and the process list, so prefer the "
        "variable or --secret-id.",
    ),
    _CredOption("--audience", "API", "OAUTH_AUDIENCE", "API the token is for."),
    _CredOption("--scope", "SCOPES", "OAUTH_SCOPE", "Space-separated scopes to request."),
    _CredOption(
        "--secret-id",
        "NAME",
        "PCTL_OAUTH_SECRET_ID",
        "Read client_id/client_secret from an AWS Secrets Manager JSON secret.",
    ),
    _CredOption(
        "--secret-region",
        "REGION",
        "PCTL_SECRET_REGION",
        "Region holding the secret.  [default: eu-central-1]",
    ),
]

_OAUTH_LOGIN_OPTIONS = [
    _CredOption(
        "--authorize-url",
        "URL",
        "OAUTH_AUTHORIZE_URL",
        "Authorization endpoint, instead of <issuer>/authorize.",
    ),
    _CredOption(
        "--redirect-uri",
        "URI",
        "OAUTH_REDIRECT_URI",
        "Redirect registered on the client. A loopback address such as "
        "http://127.0.0.1:8765/callback is caught automatically; any other value means "
        "pasting the address back from the browser.",
    ),
]


def _apply(func: Any, specs: list[_CredOption]) -> Any:
    """Decorate in reverse, so `--help` lists the options in the order they are declared."""
    for spec in reversed(specs):
        func = _cred_option(spec)(func)
    return func


def oauth_options(func: Any) -> Any:
    """Add the settings every `oauth` command needs: provider, client, audience, scope.

    A client secret is accepted as a flag here, unlike `azure`. That is a deliberate
    exception recorded in `security.md`, and the help text steers people to the variable.
    """
    return _apply(func, _OAUTH_OPTIONS)


def oauth_login_options(func: Any) -> Any:
    """Add the settings only the browser login uses."""
    timeout = _CredOption(
        "--login-timeout",
        "SECONDS",
        "OAUTH_LOGIN_TIMEOUT",
        "How long to wait for the browser.  [default: 300]",
    )
    func = _cred_option(timeout, type=click.FloatRange(min=MIN_LOGIN_TIMEOUT))(func)
    return _apply(func, _OAUTH_LOGIN_OPTIONS)


def oauth_cache_option(func: Any) -> Any:
    """Add `--no-token-cache`, for the flow that caches. A user login never does."""
    return click.option(
        "--no-token-cache",
        is_flag=True,
        default=None,
        expose_value=False,
        callback=_set_cred,
        envvar="PCTL_NO_TOKEN_CACHE",
        help="Do not read or write the on-disk token cache.  [env: PCTL_NO_TOKEN_CACHE]",
    )(func)


def read_names(names: tuple[str, ...], from_file: str | None) -> list[str]:
    """Combine repeated flag values with names read from a file or stdin (`-`).

    Blank lines and `#` comments are ignored, so a curated group list can live in
    version control next to your infrastructure code.
    """
    collected: list[str] = [name.strip() for name in names if name.strip()]
    if from_file:
        from pathlib import Path

        if from_file == "-":
            lines = click.get_text_stream("stdin").read().splitlines()
        else:
            try:
                lines = Path(from_file).read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise click.BadParameter(f"cannot read {from_file}: {exc}") from exc
        collected.extend(
            candidate
            for line in lines
            if (candidate := line.strip()) and not candidate.startswith("#")
        )
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(collected))
