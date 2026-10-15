"""Runtime configuration resolved from CLI flags, then environment, then defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import ConfigError

DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
DEFAULT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_GRAPH_SCOPE = "https://graph.microsoft.com/.default"

# How long `oauth login` waits for the browser to come back before giving up.
DEFAULT_LOGIN_TIMEOUT = 300.0

# Graph caps $top at 999 for directory objects; asking for the maximum minimises
# the number of sequential round trips, which dominates wall-clock time.
GRAPH_MAX_PAGE_SIZE = 999


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    NDJSON = "ndjson"
    CSV = "csv"


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return None


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppContext:
    """Global options shared by every command, carried on `click.Context.obj`.

    Option callbacks in `pctl.options` write here, so leaf commands read settings
    from one place instead of threading a dozen parameters through every signature.
    """

    output: OutputFormat = OutputFormat.TABLE
    verbose: bool = False
    quiet: bool = False
    timeout: float = 30.0
    concurrency: int = 16
    columns: list[str] | None = None
    creds: dict[str, Any] = field(default_factory=dict)

    def log(self, message: str) -> None:
        """Write progress to stderr so stdout stays a clean, pipeable data stream."""
        if self.verbose and not self.quiet:
            import click

            click.secho(f"[pctl] {message}", err=True, fg="cyan")

    # -- derived configs --------------------------------------------------
    def azure(self) -> AzureConfig:
        """Resolve Graph credentials from the collected options."""
        return AzureConfig.resolve(
            tenant_id=self.creds.get("tenant_id"),
            client_id=self.creds.get("client_id"),
            scope=self.creds.get("scope"),
            no_cache=bool(self.creds.get("no_token_cache")),
            secret_id=self.creds.get("secret_id"),
            secret_region=self.creds.get("secret_region"),
            aws_profile=self.creds.get("profile"),
        )

    def aws(self) -> AwsConfig:
        """Resolve AWS session settings from the collected options."""
        return AwsConfig.resolve(
            profile=self.creds.get("profile"),
            region=self.creds.get("region"),
            endpoint_url=self.creds.get("endpoint_url"),
        )

    def oauth(self) -> OAuthConfig:
        """Resolve OAuth client settings from the collected options."""
        return OAuthConfig.resolve(self.creds)


@dataclass(slots=True)
class AzureConfig:
    """Credentials and endpoints for Microsoft Graph."""

    tenant_id: str
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)
    scope: str = DEFAULT_GRAPH_SCOPE
    authority: str = DEFAULT_AUTHORITY
    base_url: str = DEFAULT_GRAPH_BASE_URL
    use_token_cache: bool = True

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority.rstrip('/')}/{self.tenant_id}/oauth2/v2.0/token"

    @property
    def has_client_secret(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def resolve(
        cls,
        *,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        scope: str | None = None,
        no_cache: bool = False,
        secret_id: str | None = None,
        secret_region: str | None = None,
        aws_profile: str | None = None,
    ) -> AzureConfig:
        """Build config from flags, environment, then AWS Secrets Manager.

        Client secrets are never accepted as a CLI flag, so they cannot leak into
        shell history or `ps` output: use the environment or `--secret-id`.
        """
        resolved_id = client_id or _env("AZURE_CLIENT_ID", "PCTL_CLIENT_ID")
        resolved_secret = client_secret or _env("AZURE_CLIENT_SECRET", "PCTL_CLIENT_SECRET")
        resolved_tenant = tenant_id or _env("AZURE_TENANT_ID", "PCTL_TENANT_ID")

        resolved_secret_id = secret_id or _env("PCTL_AZURE_SECRET_ID")
        if resolved_secret_id and not resolved_secret:
            from .secrets import load_client_secret

            from_secret = load_client_secret(
                resolved_secret_id,
                region=secret_region or _env("PCTL_SECRET_REGION"),
                profile=aws_profile,
            )
            resolved_id = resolved_id or from_secret.get("client_id")
            resolved_secret = from_secret.get("client_secret")
            resolved_tenant = resolved_tenant or from_secret.get("tenant_id")

        if not resolved_tenant:
            raise ConfigError(
                "Missing tenant. Set AZURE_TENANT_ID or pass --tenant-id "
                "(a GUID or a domain such as contoso.onmicrosoft.com)."
            )
        return cls(
            tenant_id=resolved_tenant,
            client_id=resolved_id,
            client_secret=resolved_secret,
            scope=scope or _env("PCTL_GRAPH_SCOPE") or DEFAULT_GRAPH_SCOPE,
            authority=_env("PCTL_AUTHORITY") or DEFAULT_AUTHORITY,
            base_url=(_env("PCTL_GRAPH_BASE_URL") or DEFAULT_GRAPH_BASE_URL).rstrip("/"),
            use_token_cache=not (no_cache or _env_flag("PCTL_NO_TOKEN_CACHE")),
        )


@dataclass(slots=True)
class OAuthConfig:
    """Client settings for an OAuth 2.0 provider, Auth0 by default.

    The provider is described by an `issuer`, from which the endpoints follow Auth0's
    layout, or by explicit `token_url` and `authorize_url` for a provider that differs.
    `client_secret` is optional because a browser login can use a public client, and is
    checked by `require_client_secret` for the machine-to-machine flow that cannot.
    """

    client_id: str
    client_secret: str | None = field(default=None, repr=False)
    issuer: str | None = None
    token_url: str | None = None
    authorize_url: str | None = None
    audience: str | None = None
    scope: str | None = None
    redirect_uri: str | None = None
    login_timeout: float = DEFAULT_LOGIN_TIMEOUT
    use_token_cache: bool = True

    @classmethod
    def resolve(cls, creds: Mapping[str, Any]) -> OAuthConfig:
        """Build config from the options collected on the command line.

        Environment variables are already folded in by the option declarations in
        `pctl.options`, which is what makes a flag win over its variable. Unlike Azure, a
        client secret is accepted as a flag: a deliberate exception in `security.md`.
        """
        client_id, client_secret = _oauth_credentials(creds)
        _require_oauth_settings(client_id, creds)
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            issuer=creds.get("issuer"),
            token_url=creds.get("token_url"),
            authorize_url=creds.get("authorize_url"),
            audience=creds.get("audience"),
            scope=creds.get("scope"),
            redirect_uri=creds.get("redirect_uri"),
            login_timeout=creds.get("login_timeout") or DEFAULT_LOGIN_TIMEOUT,
            use_token_cache=not creds.get("no_token_cache"),
        )

    def require_client_secret(self) -> str:
        """The secret the client credentials flow cannot run without."""
        if not self.client_secret:
            raise ConfigError(
                "Missing client secret. Set OAUTH_CLIENT_SECRET, pass --client-secret, "
                "or name a Secrets Manager secret with --secret-id."
            )
        return self.client_secret


def _oauth_credentials(creds: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The client id and secret, reading `--secret-id` only when no secret was given."""
    client_id, client_secret = creds.get("client_id"), creds.get("client_secret")
    secret_id = creds.get("secret_id")
    if secret_id and not client_secret:
        from .secrets import load_client_secret

        loaded = load_client_secret(secret_id, region=creds.get("secret_region"), profile=None)
        return client_id or loaded.get("client_id"), loaded.get("client_secret")
    return client_id, client_secret


def _require_oauth_settings(client_id: str | None, creds: Mapping[str, Any]) -> None:
    """Fail before any request when the client or the provider is not identified."""
    if not client_id:
        raise ConfigError("Missing client id. Set OAUTH_CLIENT_ID or pass --client-id.")
    if not (creds.get("token_url") or creds.get("issuer")):
        raise ConfigError(
            "Missing provider. Set OAUTH_ISSUER or pass --issuer, or give the token "
            "endpoint with OAUTH_TOKEN_URL or --token-url."
        )


@dataclass(slots=True)
class AwsConfig:
    """Session settings for the AWS SDK."""

    profile: str | None = None
    region: str | None = None
    endpoint_url: str | None = None

    @classmethod
    def resolve(
        cls,
        *,
        profile: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
    ) -> AwsConfig:
        return cls(
            profile=profile or _env("AWS_PROFILE"),
            region=region or _env("AWS_REGION", "AWS_DEFAULT_REGION"),
            endpoint_url=endpoint_url or _env("PCTL_DYNAMODB_ENDPOINT_URL"),
        )
