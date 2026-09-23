"""Unit tests for `pctl.lazy`.

`PctlGroup` is what keeps `pctl --help` fast, so the load-bearing assertion here is
that rendering help does not import any action module. Aliases and unambiguous
prefix matching are the ergonomics half of the same class.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import click
import pytest
from click.testing import CliRunner

from pctl.lazy import LazyGroup, PctlGroup

pytestmark = pytest.mark.unit

MODULE_NAME = "pctl_test_lazy_target"
OTHER_MODULE = "pctl_test_lazy_other"


@pytest.fixture
def target_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Register a throwaway module holding a click command.

    Using a synthetic module rather than a real action keeps this test independent of
    the command tree, and lets it assert on import timing precisely.
    """

    @click.command(name="doit")
    def command() -> None:
        """Do the thing."""
        click.echo("did it")

    module = types.ModuleType(MODULE_NAME)
    module.command = command  # type: ignore[attr-defined]
    module.not_a_command = object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, MODULE_NAME, module)
    return module


@pytest.fixture
def group(target_module: types.ModuleType) -> PctlGroup:
    @click.group(
        cls=PctlGroup,
        lazy_subcommands={
            "doit": (f"{MODULE_NAME}:command", "Do the thing, lazily."),
            "describe": (f"{MODULE_NAME}:command", "Describe something."),
        },
        aliases={"d": "doit", "desc": "describe"},
    )
    def root() -> None:
        """Root group."""

    return root  # type: ignore[return-value]


def invoke(group: Any, args: list[str]) -> Any:
    return CliRunner().invoke(group, args)


# ---------------------------------------------------------------------------
# lazy resolution
# ---------------------------------------------------------------------------
def test_a_lazy_subcommand_runs(group: PctlGroup) -> None:
    result = invoke(group, ["doit"])
    assert result.exit_code == 0
    assert "did it" in result.stdout


def test_help_does_not_import_the_action_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the group: `--help` must not pay for the command's imports."""
    monkeypatch.delitem(sys.modules, OTHER_MODULE, raising=False)

    @click.group(
        cls=PctlGroup,
        lazy_subcommands={"later": (f"{OTHER_MODULE}:command", "Not imported yet.")},
    )
    def root() -> None:
        """Root."""

    result = invoke(root, ["--help"])
    assert result.exit_code == 0
    assert "Not imported yet." in result.stdout
    assert OTHER_MODULE not in sys.modules


def test_short_help_comes_from_the_table(group: PctlGroup) -> None:
    result = invoke(group, ["--help"])
    assert "Do the thing, lazily." in result.stdout


def test_a_bad_target_is_reported_as_a_type_error(target_module: types.ModuleType) -> None:
    """A typo in the LAZY_SUBCOMMANDS table should fail loudly, not silently."""

    @click.group(
        cls=PctlGroup,
        lazy_subcommands={"broken": (f"{MODULE_NAME}:not_a_command", "Broken target.")},
    )
    def root() -> None:
        """Root."""

    with pytest.raises(TypeError, match="did not resolve to a click command"):
        root.get_command(click.Context(root), "broken")


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------
def test_list_commands_is_sorted_and_includes_lazy_entries(group: PctlGroup) -> None:
    assert group.list_commands(click.Context(group)) == ["describe", "doit"]


def test_aliases_are_shown_next_to_their_target(group: PctlGroup) -> None:
    result = invoke(group, ["--help"])
    assert "doit (d)" in result.stdout


# ---------------------------------------------------------------------------
# aliases and prefixes
# ---------------------------------------------------------------------------
def test_an_alias_resolves(group: PctlGroup) -> None:
    assert invoke(group, ["d"]).exit_code == 0


def test_an_unambiguous_prefix_resolves(group: PctlGroup) -> None:
    """`doi` can only mean `doit`."""
    assert invoke(group, ["doi"]).exit_code == 0


def test_ambiguity_lists_both_options() -> None:
    @click.group(
        cls=PctlGroup,
        lazy_subcommands={
            "delete": (f"{MODULE_NAME}:command", "Delete."),
            "describe": (f"{MODULE_NAME}:command", "Describe."),
        },
    )
    def root() -> None:
        """Root."""

    result = invoke(root, ["de"])
    assert result.exit_code == 2
    assert "ambiguous" in result.output
    assert "delete" in result.output and "describe" in result.output


def test_an_unknown_command_is_a_usage_error(group: PctlGroup) -> None:
    result = invoke(group, ["nope"])
    assert result.exit_code == 2


def test_an_alias_is_resolved_before_prefix_matching(group: PctlGroup) -> None:
    """`d` is an alias, even though it is also an ambiguous prefix."""
    assert invoke(group, ["d"]).exit_code == 0


# ---------------------------------------------------------------------------
# compatibility
# ---------------------------------------------------------------------------
def test_lazygroup_is_an_alias_of_pctlgroup() -> None:
    assert LazyGroup is PctlGroup
