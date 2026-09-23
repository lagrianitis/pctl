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

import json
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
    ["azure", "users"],
    ["azure", "users", "get"],
    ["azure", "apps"],
    ["azure", "apps", "list"],
    ["azure", "apps", "get"],
    ["azure", "eam"],
    ["azure", "eam", "list-packages"],
    ["azure", "eam", "get-package"],
    ["azure", "eam", "delete-package"],
    ["azure", "eam", "list-catalogs"],
    ["azure", "eam", "get-catalog"],
    ["azure", "eam", "list-assignments"],
    ["azure", "eam", "add-assignment"],
    ["azure", "eam", "remove-assignment"],
    ["azure", "eam", "get-request"],
    ["azure", "sp"],
    ["azure", "sp", "list"],
    ["azure", "sp", "get"],
    ["azure", "sp", "assignments"],
    ["azure", "sp", "owners"],
    ["azure", "sp", "add-owner"],
    ["azure", "sp", "remove-owner"],
    ["azure", "sp", "provision"],
    ["aws"],
    ["aws", "ddb"],
    ["aws", "ddb", "tables"],
    ["aws", "ddb", "describe"],
    ["aws", "ddb", "scan"],
    ["aws", "ddb", "query"],
    ["aws", "ddb", "get"],
    ["commands"],
    ["tree"],
    ["completion"],
]

# Paths that must not drag a provider SDK into the interpreter when only asking for
# help. `aws ddb scan` is included deliberately: it imports the transport module for
# MAX_SEGMENTS, which must itself keep boto3 out of module scope.
LAZY_PATHS = [
    [],
    ["azure"],
    ["azure", "groups", "list"],
    ["azure", "sp", "assignments"],
    ["aws", "ddb"],
    ["aws", "ddb", "scan"],
]
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
    result = ok(runner.invoke(cli, ["completion", "--shell", shell]))
    assert "_PCTL_COMPLETE" in result.stdout
    assert shell in result.stdout


def test_completion_rejects_an_unknown_shell(runner: Any, cli: Any) -> None:
    failed(runner.invoke(cli, ["completion", "--shell", "csh"]), 2)


def test_no_command_declares_a_positional_argument(cli: Any) -> None:
    """Every value is a named flag, so a stray word can never be silently absorbed.

    Walks the whole tree eagerly, which is the point: a new action that reintroduces a
    positional should fail here rather than in review.
    """
    import click

    def walk(command: click.Command, ctx: click.Context) -> None:
        offenders = [param.name for param in command.params if isinstance(param, click.Argument)]
        assert offenders == [], f"{command.name} declares positional {offenders}"
        if isinstance(command, click.Group):
            for name in command.list_commands(ctx):
                child = command.get_command(ctx, name)
                assert child is not None
                walk(child, click.Context(child, parent=ctx))

    walk(cli, click.Context(cli))


# ---------------------------------------------------------------------------
# discovery: commands, tree and completion
# ---------------------------------------------------------------------------
def test_commands_lists_every_leaf_in_the_tree(runner: Any, cli: Any) -> None:
    """The listing and the enumerated paths above must not drift apart.

    COMMAND_PATHS is maintained by hand so a vanishing command fails a test; this asserts
    the walk finds exactly the same leaves, which makes either one a check on the other.
    """
    result = ok(runner.invoke(cli, ["-o", "ndjson", "commands"]))

    def is_leaf(path: list[str]) -> bool:
        deeper = (other for other in COMMAND_PATHS if len(other) > len(path))
        return bool(path) and not any(other[: len(path)] == path for other in deeper)

    listed = {json.loads(line)["command"] for line in result.stdout.splitlines() if line}
    expected = {" ".join(["pctl", *path]) for path in COMMAND_PATHS if is_leaf(path)}
    assert listed == expected


def test_commands_omits_the_groups_by_default(runner: Any, cli: Any) -> None:
    """A group cannot be run, so it is noise in a list of things to run."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "commands"]))

    assert "pctl azure" not in {
        json.loads(line)["command"] for line in result.stdout.splitlines() if line
    }


def test_commands_can_include_the_groups(runner: Any, cli: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "ndjson", "commands", "--groups"]))

    listed = {json.loads(line)["command"] for line in result.stdout.splitlines() if line}
    assert {"pctl azure", "pctl azure eam", "pctl aws ddb"} <= listed


def test_commands_carries_a_summary_for_every_command(runner: Any, cli: Any) -> None:
    """An entry with no summary is useless for finding anything."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "commands"]))

    records = [json.loads(line) for line in result.stdout.splitlines() if line]
    assert records
    assert all(record["summary"].strip() for record in records)


def test_commands_is_greppable_for_a_task(runner: Any, cli: Any) -> None:
    """The point of the command: find the path from a word you remember."""
    result = ok(runner.invoke(cli, ["commands"]))

    matched = [line for line in result.stdout.splitlines() if "assign" in line.lower()]
    assert any("eam add-assignment" in line for line in matched)
    assert any("sp assignments" in line for line in matched)


def test_commands_reports_aliases(runner: Any, cli: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "ndjson", "commands", "--groups"]))

    records = {
        json.loads(line)["command"]: json.loads(line)["aliases"]
        for line in result.stdout.splitlines()
        if line
    }
    assert "az" in records["pctl azure"]
    assert "enterprise-apps" in records["pctl azure sp"]


def test_tree_draws_the_hierarchy(runner: Any, cli: Any) -> None:
    result = ok(runner.invoke(cli, ["tree"]))

    assert result.stdout.startswith("pctl\n")
    assert "└── " in result.stdout or "├── " in result.stdout
    assert "eam" in result.stdout


def test_tree_depth_limits_the_descent(runner: Any, cli: Any) -> None:
    shallow = ok(runner.invoke(cli, ["tree", "--depth", "1"])).stdout

    assert "azure" in shallow
    assert "add-assignment" not in shallow


def test_a_zero_depth_is_rejected(runner: Any, cli: Any) -> None:
    failed(runner.invoke(cli, ["tree", "--depth", "0"]), 2)


def test_completion_offers_lazy_subcommands(cli: Any) -> None:
    """Completion has to see through the lazy table, or it offers nothing at all."""
    import click

    ctx = click.Context(cli)
    offered = {item.value for item in cli.shell_complete(ctx, "")}

    assert {"azure", "aws", "commands", "tree", "completion"} <= offered


def test_completion_offers_aliases_too(cli: Any) -> None:
    """`pctl azure enter<TAB>` resolved but completed nothing until aliases were added."""
    import click

    azure = cli.get_command(click.Context(cli), "azure")
    ctx = click.Context(azure, parent=click.Context(cli))
    offered = {item.value for item in azure.shell_complete(ctx, "enter")}

    assert offered == {"enterprise-apps"}


def test_completion_prefers_the_canonical_name(cli: Any) -> None:
    """Both spellings are offered for `s`, with the real command first."""
    import click

    azure = cli.get_command(click.Context(cli), "azure")
    ctx = click.Context(azure, parent=click.Context(cli))
    offered = [item.value for item in azure.shell_complete(ctx, "s")]

    assert offered.index("sp") < offered.index("service-principals")


def test_walking_the_tree_imports_no_provider_sdk() -> None:
    """`pctl commands` actually runs the walk, unlike the --help checks above.

    The walk reads each subcommand's summary from its parent's lazy table and recurses
    only into groups, so no action module is imported and nothing pulls httpx or boto3.
    That is the whole reason the listing is cheap enough to run on every invocation, and
    it is only true by construction, so it is asserted rather than assumed.

    A subprocess for the same reason as the help check: this test process has already
    imported those modules for other tiers and would mask the regression.
    """
    script = (
        "import sys\n"
        "from click.testing import CliRunner\n"
        "from pctl.cli import cli\n"
        "result = CliRunner().invoke(cli, ['-o', 'ndjson', 'commands'])\n"
        "assert result.exit_code == 0, result.output\n"
        "assert result.stdout.count(chr(10)) > 20, result.stdout\n"
        f"loaded = [m for m in {PROVIDER_MODULES!r} if m in sys.modules]\n"
        "print(','.join(loaded))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert completed.stdout.strip() == "", (
        f"`pctl commands` imported {completed.stdout.strip()}; the walk should read the "
        "lazy tables rather than importing action modules"
    )


def test_walking_the_tree_imports_no_action_module() -> None:
    """Stronger than the SDK check: no leaf module should be in sys.modules at all."""
    script = (
        "import sys\n"
        "from click.testing import CliRunner\n"
        "from pctl.cli import cli\n"
        "result = CliRunner().invoke(cli, ['commands'])\n"
        "assert result.exit_code == 0, result.output\n"
        "leaves = [\n"
        "    'pctl.azure.entitlements.add_assignment',\n"
        "    'pctl.azure.service_principals.provision',\n"
        "    'pctl.azure.groups.list',\n"
        "    'pctl.aws.dynamodb.scan',\n"
        "]\n"
        "print(','.join(m for m in leaves if m in sys.modules))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert completed.stdout.strip() == "", (
        f"the walk imported {completed.stdout.strip()}; a leaf's summary comes from its "
        "parent's LAZY_SUBCOMMANDS table, so it must not need importing"
    )
