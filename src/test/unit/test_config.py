"""Unit tests for `pctl.config`.

Credential resolution has a documented precedence (flag, then environment, then AWS
Secrets Manager) and a security property: a client secret must never be accepted from
argv. Both are asserted here, along with the Secrets Manager path being skipped
entirely when it is not needed, since consulting it costs a network round trip.
"""

from __future__ import annotations

from typing import Any

import pytest

from pctl.config import (
    DEFAULT_AUTHORITY,
    DEFAULT_GRAPH_BASE_URL,
    DEFAULT_GRAPH_SCOPE,
    AppContext,
    AwsConfig,
    AzureConfig,
    OutputFormat,
)
from pctl.errors import ConfigError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from an environment with nothing pctl or provider related set."""
    for name in (
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "PCTL_TENANT_ID",
        "PCTL_CLIENT_ID",
        "PCTL_CLIENT_SECRET",
        "PCTL_AZURE_SECRET_ID",
        "PCTL_SECRET_REGION",
        "PCTL_NO_TOKEN_CACHE",
        "PCTL_GRAPH_SCOPE",
        "PCTL_GRAPH_BASE_URL",
        "PCTL_AUTHORITY",
        "PCTL_DYNAMODB_ENDPOINT_URL",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# output format
# ---------------------------------------------------------------------------
def test_output_format_values_are_the_cli_choices() -> None:
    assert [fmt.value for fmt in OutputFormat] == ["table", "json", "ndjson", "csv"]


def test_output_format_accepts_its_own_string() -> None:
    assert OutputFormat("ndjson") is OutputFormat.NDJSON


# ---------------------------------------------------------------------------
# azure: tenant
# ---------------------------------------------------------------------------
def test_missing_tenant_is_a_config_error_with_actionable_text() -> None:
    with pytest.raises(ConfigError) as excinfo:
        AzureConfig.resolve()
    message = str(excinfo.value)
    assert "AZURE_TENANT_ID" in message and "--tenant-id" in message


def test_config_error_exits_2() -> None:
    assert ConfigError("x").exit_code == 2


def test_tenant_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "contoso.onmicrosoft.com")
    assert AzureConfig.resolve().tenant_id == "contoso.onmicrosoft.com"


def test_flag_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "from-env")
    monkeypatch.setenv("AZURE_CLIENT_ID", "env-client")
    config = AzureConfig.resolve(tenant_id="from-flag", client_id="flag-client")
    assert (config.tenant_id, config.client_id) == ("from-flag", "flag-client")


def test_pctl_prefixed_env_is_accepted_as_a_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCTL_TENANT_ID", "from-pctl-env")
    assert AzureConfig.resolve().tenant_id == "from-pctl-env"


def test_env_values_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "  padded  ")
    assert AzureConfig.resolve().tenant_id == "padded"


# ---------------------------------------------------------------------------
# azure: endpoints and defaults
# ---------------------------------------------------------------------------
def test_token_endpoint_is_built_from_authority_and_tenant() -> None:
    config = AzureConfig.resolve(tenant_id="tid")
    assert config.token_endpoint == f"{DEFAULT_AUTHORITY}/tid/oauth2/v2.0/token"


def test_defaults_are_graph_v1_and_the_default_scope() -> None:
    config = AzureConfig.resolve(tenant_id="tid")
    assert config.base_url == DEFAULT_GRAPH_BASE_URL
    assert config.scope == DEFAULT_GRAPH_SCOPE


def test_base_url_override_loses_its_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCTL_GRAPH_BASE_URL", "https://graph.microsoft.com/beta/")
    assert AzureConfig.resolve(tenant_id="tid").base_url == "https://graph.microsoft.com/beta"


def test_authority_override_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCTL_AUTHORITY", "https://login.microsoftonline.us")
    config = AzureConfig.resolve(tenant_id="tid")
    assert config.token_endpoint.startswith("https://login.microsoftonline.us/tid/")


def test_has_client_secret_requires_both_id_and_secret() -> None:
    assert not AzureConfig.resolve(tenant_id="t", client_id="c").has_client_secret
    assert not AzureConfig.resolve(tenant_id="t", client_secret="s").has_client_secret
    assert AzureConfig.resolve(tenant_id="t", client_id="c", client_secret="s").has_client_secret


def test_secret_is_kept_out_of_the_repr() -> None:
    """A config object may be logged; the secret must not ride along."""
    config = AzureConfig.resolve(tenant_id="t", client_id="c", client_secret="super-secret")
    assert "super-secret" not in repr(config)


# ---------------------------------------------------------------------------
# azure: token cache toggle
# ---------------------------------------------------------------------------
def test_token_cache_is_on_by_default() -> None:
    assert AzureConfig.resolve(tenant_id="t").use_token_cache is True


def test_no_cache_flag_disables_it() -> None:
    assert AzureConfig.resolve(tenant_id="t", no_cache=True).use_token_cache is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_env_flag_disables_the_cache(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("PCTL_NO_TOKEN_CACHE", raw)
    assert AzureConfig.resolve(tenant_id="t").use_token_cache is False


@pytest.mark.parametrize("raw", ["0", "false", "no", "", "off"])
def test_other_env_values_leave_the_cache_on(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("PCTL_NO_TOKEN_CACHE", raw)
    assert AzureConfig.resolve(tenant_id="t").use_token_cache is True


# ---------------------------------------------------------------------------
# azure: AWS Secrets Manager fallback
# ---------------------------------------------------------------------------
@pytest.fixture
def secret_loader(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record calls to the Secrets Manager loader instead of hitting AWS."""
    calls: list[dict[str, Any]] = []

    def fake_load(secret_id: str, *, region: str | None, profile: str | None) -> dict[str, str]:
        calls.append({"secret_id": secret_id, "region": region, "profile": profile})
        return {
            "client_id": "secret-client",
            "client_secret": "secret-value",
            "tenant_id": "secret-tenant",
        }

    monkeypatch.setattr("pctl.secrets.load_azure_secret", fake_load)
    return calls


def test_secret_id_supplies_credentials(secret_loader: list[dict[str, Any]]) -> None:
    config = AzureConfig.resolve(secret_id="azuread-client")
    assert config.client_id == "secret-client"
    assert config.client_secret == "secret-value"
    assert config.tenant_id == "secret-tenant"
    assert secret_loader[0]["secret_id"] == "azuread-client"


def test_secret_id_is_read_from_env(
    monkeypatch: pytest.MonkeyPatch, secret_loader: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("PCTL_AZURE_SECRET_ID", "from-env-secret")
    AzureConfig.resolve()
    assert secret_loader[0]["secret_id"] == "from-env-secret"


def test_secret_region_and_profile_are_passed_through(
    secret_loader: list[dict[str, Any]],
) -> None:
    AzureConfig.resolve(secret_id="s", secret_region="us-east-1", aws_profile="tg-dev")
    assert secret_loader[0]["region"] == "us-east-1"
    assert secret_loader[0]["profile"] == "tg-dev"


def test_env_secret_wins_and_skips_the_network_call(
    monkeypatch: pytest.MonkeyPatch, secret_loader: list[dict[str, Any]]
) -> None:
    """An env secret must short-circuit Secrets Manager, which costs a round trip."""
    monkeypatch.setenv("AZURE_TENANT_ID", "env-tenant")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "env-secret")
    config = AzureConfig.resolve(secret_id="azuread-client")
    assert config.client_secret == "env-secret"
    assert secret_loader == []


def test_explicit_tenant_survives_the_secret_lookup(secret_loader: list[dict[str, Any]]) -> None:
    config = AzureConfig.resolve(tenant_id="explicit", secret_id="s")
    assert config.tenant_id == "explicit"
    assert config.client_secret == "secret-value"


# ---------------------------------------------------------------------------
# aws
# ---------------------------------------------------------------------------
def test_aws_config_is_empty_without_configuration() -> None:
    config = AwsConfig.resolve()
    assert (config.profile, config.region, config.endpoint_url) == (None, None, None)


def test_aws_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "tg-dev")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("PCTL_DYNAMODB_ENDPOINT_URL", "http://localhost:8000")
    config = AwsConfig.resolve()
    assert config.profile == "tg-dev"
    assert config.region == "eu-central-1"
    assert config.endpoint_url == "http://localhost:8000"


def test_aws_region_falls_back_to_aws_default_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    assert AwsConfig.resolve().region == "us-west-2"


def test_aws_flags_beat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "from-env")
    assert AwsConfig.resolve(profile="from-flag").profile == "from-flag"


# ---------------------------------------------------------------------------
# AppContext
# ---------------------------------------------------------------------------
def test_app_context_defaults() -> None:
    app = AppContext()
    assert app.output is OutputFormat.TABLE
    assert (app.verbose, app.quiet, app.columns) == (False, False, None)
    assert app.creds == {}


def test_app_context_derives_provider_configs() -> None:
    app = AppContext()
    app.creds.update({"tenant_id": "t", "client_id": "c", "profile": "p", "region": "r"})
    assert app.azure().tenant_id == "t"
    assert app.aws().profile == "p"
    assert app.aws().region == "r"


def test_app_context_passes_the_aws_profile_to_secrets_manager(
    secret_loader: list[dict[str, Any]],
) -> None:
    """`--profile` must also select the account the secret is read from."""
    app = AppContext()
    app.creds.update({"secret_id": "s", "profile": "tg-dev"})
    app.azure()
    assert secret_loader[0]["profile"] == "tg-dev"


def test_log_is_silent_unless_verbose(capsys: pytest.CaptureFixture[str]) -> None:
    AppContext().log("nothing")
    assert capsys.readouterr().err == ""


def test_log_writes_to_stderr_when_verbose(capsys: pytest.CaptureFixture[str]) -> None:
    AppContext(verbose=True).log("fetching page 2")
    captured = capsys.readouterr()
    assert "fetching page 2" in captured.err
    assert captured.out == ""


def test_quiet_silences_verbose_logging(capsys: pytest.CaptureFixture[str]) -> None:
    AppContext(verbose=True, quiet=True).log("suppressed")
    assert capsys.readouterr().err == ""
