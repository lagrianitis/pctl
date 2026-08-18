"""Error types that map cleanly onto CLI exit codes."""

from __future__ import annotations

import click

EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_UPSTREAM = 5


class PctlError(click.ClickException):
    """Base error: prints `Error: <message>` and exits with `exit_code`."""

    exit_code = 1


class ConfigError(PctlError):
    exit_code = EXIT_USAGE


class AuthError(PctlError):
    exit_code = EXIT_AUTH


class NotFoundError(PctlError):
    exit_code = EXIT_NOT_FOUND


class UpstreamError(PctlError):
    """Non-recoverable failure returned by Graph or AWS."""

    exit_code = EXIT_UPSTREAM
