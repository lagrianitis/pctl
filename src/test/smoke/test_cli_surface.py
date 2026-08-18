"""Smoke tier: is the build alive?

Tree-level checks that belong to no single service - the command table loads, help
renders everywhere, the version reports, and the root rejects nonsense. Service
specifics live in `aws/` and `azure/` beside this file.

The load-bearing test is `test_help_does_not_import_a_provider_sdk`. Lazy imports are
what keep `pctl --help` in the low tens of milliseconds, and a single module-level
`import boto3` anywhere on the help path silently costs half a second. That property
is invisible in normal use, so it gets asserted in a subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from helpers import failed, help_for, ok

pytestmark = pytest.mark.smoke

# Every command path in the tree. Kept explicit rather than discovered, so that a
# command disappearing from the tree fails a test instead of shrinking the run.
COMMAND_PATHS: list[list[str]] = [
    [],
    ["azure"],
    ["azure", "token"],
    ["azure", "raw"],
    ["azure", "groups"],
    ["azure", "groups", "list"],
    ["azure", "groups", "get"],
    ["azure", "groups", "members"],
    ["aws"],
    ["aws", "ddb"],
    ["aws", "ddb", "tables"],
    ["aws", "ddb", "describe"],
    ["aws", "ddb", "scan"],
    ["aws", "ddb", "query"],
    ["aws", "ddb", "get"],
    ["completion"],
]

# Paths that must not drag a provider SDK into the interpreter when only asking for
# help. `aws ddb scan` is included deliberately: it imports the transport module for
# MAX_SEGMENTS, which must itself keep boto3 out of module scope.
LAZY_PATHS = [[], ["azure"], ["azure", "groups", "list"], ["aws", "ddb"], ["aws", "ddb", "scan"]]
PROVIDER_MODULES = ("boto3", "botocore", "httpx", "uvloop", "h2")


# ---------------------------------------------------------------------------
# the tree loads and renders
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", COMMAND_PATHS, ids=lambda p: " ".join(p) or "root")
def test_every_command_renders_help(runner: Any, cli: Any, path: list[str]) -> None:
    result = help_for(runner, cli, path)
    assert result.stdout.startswith(" ".join(["Usage: pctl", *path]))


@pytest.mark.parametrize("path", COMMAND_PATHS, ids=lambda p: " ".join(p) or "root")
def test_short_help_flag_works_everywhere(runner: Any, cli: Any, path: list[str]) -> None:
    """`-h` is wired through context_settings on every group."""
    assert help_for(runner, cli, path, "-h").stdout.startswith("Usage: pctl")


def test_version_reports_the_package_version(runner: Any, cli: Any) -> None:
    from pctl import __version__

    result = ok(runner.invoke(cli, ["--version"]))
    assert __version__ in result.stdout
    assert "pctl" in result.stdout


def test_root_help_lists_both_cases(runner: Any, cli: Any) -> None:
    stdout = help_for(runner, cli, []).stdout
    assert "azure" in stdout and "aws" in stdout


def test_root_help_shows_aliases(runner: Any, cli: Any) -> None:
    """Aliases are discoverable, otherwise nobody knows `az` exists."""
    assert "azure (az" in help_for(runner, cli, []).stdout


# ---------------------------------------------------------------------------
# the property that pays for the architecture
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", LAZY_PATHS, ids=lambda p: " ".join(p) or "root")
def test_help_does_not_import_a_provider_sdk(path: list[str]) -> None:
    """Rendering help must not import boto3, httpx or the optional accelerators.

    Runs in a subprocess because this test process has already imported them for
    other tiers, which would mask a regression.
    """
    script = (
        "import sys\n"
        "from click.testing import CliRunner\n"
        "from pctl.cli import cli\n"
        f"result = CliRunner().invoke(cli, {path!r} + ['--help'])\n"
        "assert result.exit_code == 0, result.output\n"
        f"loaded = [m for m in {PROVIDER_MODULES!r} if m in sys.modules]\n"
        "print(','.join(loaded))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "", (
        f"`pctl {' '.join(path)} --help` imported {completed.stdout.strip()}; "
        "move the import inside the command function"
    )


def test_the_root_module_only_needs_click() -> None:
    """`pctl.cli` itself must stay free of heavy imports at module scope."""
    script = (
        "import sys\n"
        "import pctl.cli\n"
        f"print(','.join(m for m in {PROVIDER_MODULES!r} if m in sys.modules))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == ""


# ---------------------------------------------------------------------------
# root-level input rejection
# ---------------------------------------------------------------------------
def test_an_unknown_command_is_a_usage_error(runner: Any, cli: Any) -> None:
    failed(runner.invoke(cli, ["nope"]), 2)


def test_an_invalid_output_format_is_rejected(runner: Any, cli: Any) -> None:
    result = failed(runner.invoke(cli, ["-o", "yaml", "azure", "groups", "list"]), 2)
    assert "yaml" in result.output


def test_an_ambiguous_prefix_names_the_candidates(runner: Any, cli: Any) -> None:
    """At the root, `a` could be `aws` or `azure`, so it must not guess."""
    result = failed(runner.invoke(cli, ["a", "--help"]), 2)
    assert "ambiguous" in result.output
    assert "aws" in result.output and "azure" in result.output


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_prints_setup_for_each_shell(runner: Any, cli: Any, shell: str) -> None:
    result = ok(runner.invoke(cli, ["completion", shell]))
    assert "_PCTL_COMPLETE" in result.stdout
    assert shell in result.stdout


def test_completion_rejects_an_unknown_shell(runner: Any, cli: Any) -> None:
    failed(runner.invoke(cli, ["completion", "csh"]), 2)
