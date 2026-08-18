"""Runtime configuration resolved from CLI flags, then environment, then defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import ConfigError

DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
DEFAULT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_GRAPH_SCOPE = "https://graph.microsoft.com/.default"

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
            from .secrets import load_azure_secret

            from_secret = load_azure_secret(
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
