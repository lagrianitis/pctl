"""Smoke tier: the `pctl azure apps` surface.

Help text and argument validation only. Nothing here acquires a token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


@pytest.fixture
def apps(azure: Callable[..., Any]) -> Callable[..., Any]:
    """Invoke `pctl azure apps ...`."""

    def invoke(*args: str) -> Any:
        return azure("apps", *args)

    return invoke


def test_the_service_help_lists_its_actions(apps: Callable[..., Any]) -> None:
    stdout = ok(apps("--help")).stdout
    assert "list" in stdout
    assert "get" in stdout


def test_the_case_help_lists_the_service(azure: Callable[..., Any]) -> None:
    assert "apps" in ok(azure("--help")).stdout


def test_the_portal_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "get" in ok(azure("app-registrations", "--help")).stdout


def test_the_graph_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "get" in ok(azure("applications", "--help")).stdout


def test_the_help_distinguishes_apps_from_service_principals(apps: Callable[..., Any]) -> None:
    """These two are the easiest pair in the tool to confuse, so say which is which."""
    assert "service principal" in ok(apps("--help")).stdout.lower()


def test_get_help_explains_the_two_guids(apps: Callable[..., Any]) -> None:
    stdout = ok(apps("get", "--help")).stdout
    assert "appId" in stdout
    assert "object ID" in stdout


def test_get_help_documents_the_service_principal_join(apps: Callable[..., Any]) -> None:
    assert "--with-sp" in ok(apps("get", "--help")).stdout


def test_list_help_keeps_its_examples(apps: Callable[..., Any]) -> None:
    assert "pctl azure apps list" in ok(apps("list", "--help")).stdout


def test_get_without_an_identifier_is_a_usage_error(apps: Callable[..., Any]) -> None:
    failed(apps("get"), 2)


def test_an_unknown_match_mode_is_rejected(apps: Callable[..., Any]) -> None:
    failed(apps("get", "--app", "whatever", "--match", "fuzzy"), 2)


def test_an_invalid_page_size_is_rejected(apps: Callable[..., Any]) -> None:
    failed(apps("list", "--page-size", "0"), 2)


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------
def test_the_service_help_lists_credentials(apps: Callable[..., Any]) -> None:
    assert "get-client-secrets" in ok(apps("--help")).stdout


def test_credentials_requires_an_app(apps: Callable[..., Any]) -> None:
    failed(apps("get-client-secrets"), 2)


def test_credentials_takes_no_positional_arguments(apps: Callable[..., Any]) -> None:
    failed(apps("get-client-secrets", "--app-name", "x", "unexpected"), 2)


def test_credentials_help_says_no_secret_value_is_shown(apps: Callable[..., Any]) -> None:
    stdout = " ".join(ok(apps("get-client-secrets", "--help")).stdout.split())

    assert "never returns the value of an existing secret" in stdout


def test_credentials_help_documents_how_the_app_is_found(apps: Callable[..., Any]) -> None:
    stdout = ok(apps("get-client-secrets", "--help")).stdout

    assert "--app-name" in stdout
    assert "--app-id" in stdout
    assert "--match" in stdout


def test_credentials_help_documents_the_expiry_window(apps: Callable[..., Any]) -> None:
    stdout = " ".join(ok(apps("get-client-secrets", "--help")).stdout.split())

    assert "--expiring-within" in stdout
    assert "[default: 30" in stdout


def test_credentials_help_documents_the_failing_flag_and_its_code(
    apps: Callable[..., Any],
) -> None:
    stdout = " ".join(ok(apps("get-client-secrets", "--help")).stdout.split())

    assert "--fail-on-expiry" in stdout
    assert "Exit 6" in stdout


def test_a_window_of_zero_days_is_rejected(apps: Callable[..., Any]) -> None:
    failed(apps("get-client-secrets", "--app-name", "x", "--expiring-within", "0"), 2)


def test_a_window_that_is_not_a_number_is_rejected(apps: Callable[..., Any]) -> None:
    failed(apps("get-client-secrets", "--app-name", "x", "--expiring-within", "soon"), 2)


# ---------------------------------------------------------------------------
# add-client-secret
# ---------------------------------------------------------------------------
APP_ID = "8f468c48-e9ac-4dd7-973d-9704b9cdd56d"


def test_the_service_help_lists_add_client_secret(apps: Callable[..., Any]) -> None:
    assert "add-client-secret" in ok(apps("--help")).stdout


def test_add_client_secret_help_documents_the_flags(apps: Callable[..., Any]) -> None:
    stdout = " ".join(ok(apps("add-client-secret", "--help")).stdout.split())

    for flag in ("--app-name", "--app-id", "--valid-for-days", "--store-in", "--show-secret"):
        assert flag in stdout
    assert "--overwrite" in stdout
    assert "[default: 180" in stdout


def test_add_client_secret_help_says_the_value_is_shown_once(apps: Callable[..., Any]) -> None:
    stdout = " ".join(ok(apps("add-client-secret", "--help")).stdout.split())

    assert "shows a new secret's value once" in stdout


def test_add_client_secret_requires_a_secret_name(apps: Callable[..., Any]) -> None:
    failed(apps("add-client-secret", "--app-id", APP_ID, "--show-secret"), 2)


def test_add_client_secret_requires_an_app(apps: Callable[..., Any]) -> None:
    failed(apps("add-client-secret", "--name", "t1", "--show-secret"), 2)


def test_add_client_secret_refuses_both_ways_of_naming_the_app(apps: Callable[..., Any]) -> None:
    failed(
        apps(
            "add-client-secret",
            "--app-name",
            "x",
            "--app-id",
            APP_ID,
            "--name",
            "t1",
            "--show-secret",
        ),
        2,
    )


def test_add_client_secret_refuses_a_secret_that_would_be_lost(apps: Callable[..., Any]) -> None:
    result = failed(apps("add-client-secret", "--app-id", APP_ID, "--name", "t1"), 2)

    assert "--store-in" in result.output
    assert "--show-secret" in result.output


@pytest.mark.parametrize("days", ["0", "366", "soon"])
def test_add_client_secret_rejects_a_lifetime_out_of_range(
    apps: Callable[..., Any], days: str
) -> None:
    failed(
        apps(
            "add-client-secret",
            "--app-id",
            APP_ID,
            "--name",
            "t1",
            "--show-secret",
            "--valid-for-days",
            days,
        ),
        2,
    )


# ---------------------------------------------------------------------------
# remove-client-secret
# ---------------------------------------------------------------------------
def test_the_service_help_lists_remove_client_secret(apps: Callable[..., Any]) -> None:
    assert "remove-client-secret" in ok(apps("--help")).stdout


def test_remove_client_secret_help_documents_the_flags(apps: Callable[..., Any]) -> None:
    stdout = " ".join(ok(apps("remove-client-secret", "--help")).stdout.split())

    for flag in ("--app-name", "--app-id", "--key-id", "--force"):
        assert flag in stdout


def test_remove_client_secret_has_no_name_flag(apps: Callable[..., Any]) -> None:
    """Only a key ID names the secret, so a name cannot pick the wrong one of two."""
    assert "--name" not in ok(apps("remove-client-secret", "--help")).stdout


def test_remove_client_secret_help_says_what_needs_force(apps: Callable[..., Any]) -> None:
    stdout = " ".join(ok(apps("remove-client-secret", "--help")).stdout.split())

    assert "more than 30 days left" in stdout
    assert "unless --force is given" in stdout


def test_remove_client_secret_requires_an_app(apps: Callable[..., Any]) -> None:
    failed(apps("remove-client-secret", "--key-id", "k"), 2)


def test_remove_client_secret_requires_a_key_id(apps: Callable[..., Any]) -> None:
    failed(apps("remove-client-secret", "--app-id", APP_ID), 2)


def test_remove_client_secret_rejects_a_name(apps: Callable[..., Any]) -> None:
    failed(apps("remove-client-secret", "--app-id", APP_ID, "--key-id", "k", "--name", "t1"), 2)


def test_remove_client_secret_takes_no_positional_arguments(apps: Callable[..., Any]) -> None:
    failed(apps("remove-client-secret", "--app-id", APP_ID, "--key-id", "k", "unexpected"), 2)
