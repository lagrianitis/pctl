"""Error types that map cleanly onto CLI exit codes."""

from __future__ import annotations

import click

EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_UPSTREAM = 5
EXIT_CHECK_FAILED = 6


class PctlError(click.ClickException):
    """Base error: prints `Error: <message>` and exits with `exit_code`."""

    exit_code = 1


class ConfigError(PctlError):
    exit_code = EXIT_USAGE


class AuthError(PctlError):
    exit_code = EXIT_AUTH


class NotFoundError(PctlError):
    exit_code = EXIT_NOT_FOUND


class CheckFailedError(PctlError):
    """A check the caller asked for did not pass, such as a credential about to expire.

    Not a fault in pctl or in the provider, so it has a code of its own: a pipeline can tell
    "the check says no" from "the check could not run".
    """

    exit_code = EXIT_CHECK_FAILED


class UpstreamError(PctlError):
    """Non-recoverable failure returned by Graph or AWS."""

    exit_code = EXIT_UPSTREAM
