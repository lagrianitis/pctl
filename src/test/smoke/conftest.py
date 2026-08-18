"""Isolation for the smoke tier.

Smoke tests only exercise CLI surface: help rendering and argument parsing. None of
them should reach a provider. This autouse fixture makes that a guarantee rather than
an intention by stripping the credentials a developer's shell is likely to hold, so a
test that accidentally runs a real command fails on configuration instead of quietly
authenticating against a live account.

The failure that motivated it: an ambiguous-prefix test resolved to `aws ddb tables`
and started an SSO token refresh against the real platform account.
"""

from __future__ import annotations

import pytest

PROVIDER_ENV = (
    # AWS
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    # Azure
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    # pctl overrides
    "PCTL_TENANT_ID",
    "PCTL_CLIENT_ID",
    "PCTL_CLIENT_SECRET",
    "PCTL_AZURE_SECRET_ID",
    "PCTL_DYNAMODB_ENDPOINT_URL",
)


@pytest.fixture(autouse=True)
def no_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    # Also keep botocore away from ~/.aws, so a shared config file cannot supply a
    # profile or SSO session.
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
