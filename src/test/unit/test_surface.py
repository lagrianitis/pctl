"""Unit tier: the command-tree walk behind `pctl commands` and `pctl tree`.

Built against a small fake tree rather than the real one, so the assertions are about the
walk and not about whichever commands happen to exist today. The one property that is
worth pinning against the real tree — that walking it imports no provider SDK — belongs to
the smoke tier, which already runs that check in a subprocess.
"""

from __future__ import annotations

from typing import Any

import click
import pytest

from pctl.lazy import PctlGroup
from pctl.surface import Node, build, draw, flatten, rows

pytestmark = pytest.mark.unit

# A leaf target ends in `:command`; anything else is treated as a group. The module the
# path points at is never imported for a leaf, which is what these fixtures rely on:
# `pctl.does.not.exist` would fail on import.
LEAF = "pctl.does.not.exist:command"


@pytest.fixture
def service() -> PctlGroup:
    """A service group with two lazy actions, neither of which can be imported."""

    @click.group(
        name="svc",
        cls=PctlGroup,
        lazy_subcommands={
            "get": (LEAF, "Get one."),
            "list": (LEAF, "List them."),
        },
    )
    def svc() -> None:
        """A service."""

    return svc


@pytest.fixture
def root(service: PctlGroup) -> PctlGroup:
    """A root with one eager group, one lazy leaf, and an alias."""

    @click.group(
        cls=PctlGroup,
        lazy_subcommands={"token": (LEAF, "Get a token.")},
        aliases={"s": "svc"},
    )
    def cli() -> None:
        """Root."""

    cli.add_command(service)
    return cli


@pytest.fixture
def walked(root: PctlGroup) -> tuple[Node, ...]:
    return build(root, click.Context(root))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def test_a_leaf_is_described_without_importing_it(walked: tuple[Node, ...]) -> None:
    """The summary comes from the parent's table, which is why an unimportable path works.

    This is the property the whole design rests on: `pctl commands` must not pay for
    importing thirty action modules to print their one-line summaries.
    """
    token = next(node for node in walked if node.name == "token")

    assert token.summary == "Get a token."
    assert token.children == ()


def test_a_group_is_recursed_into(walked: tuple[Node, ...]) -> None:
    svc = next(node for node in walked if node.name == "svc")

    assert [child.name for child in svc.children] == ["get", "list"]


def test_a_path_is_what_you_would_type(walked: tuple[Node, ...]) -> None:
    svc = next(node for node in walked if node.name == "svc")

    assert svc.children[0].path == ("svc", "get")
    assert svc.children[0].command == "pctl svc get"


def test_children_are_sorted_like_help_sorts_them(walked: tuple[Node, ...]) -> None:
    assert [node.name for node in walked] == ["svc", "token"]


def test_an_alias_is_attached_to_the_command_it_points_at(walked: tuple[Node, ...]) -> None:
    svc = next(node for node in walked if node.name == "svc")

    assert svc.aliases == ("s",)


def test_an_eager_group_gets_its_summary_from_its_docstring(walked: tuple[Node, ...]) -> None:
    """`svc` is registered directly, so there is no table entry to read it from."""
    svc = next(node for node in walked if node.name == "svc")

    assert svc.summary == "A service."


def test_a_hidden_command_is_left_out(root: PctlGroup) -> None:
    @click.command(name="secret", hidden=True)
    def secret() -> None:
        """Hidden."""

    root.add_command(secret)

    assert "secret" not in [node.name for node in build(root, click.Context(root))]


def test_a_plain_group_without_the_lazy_table_still_walks() -> None:
    """`build` must tolerate a stock click.Group, since nothing guarantees PctlGroup."""

    @click.group()
    def plain() -> None:
        """Plain."""

    @plain.command()
    def doit() -> None:
        """Do it."""

    nodes = build(plain, click.Context(plain))

    assert [node.name for node in nodes] == ["doit"]
    assert nodes[0].summary == "Do it."


# ---------------------------------------------------------------------------
# flatten
# ---------------------------------------------------------------------------
def test_flatten_returns_leaves_only_by_default(walked: tuple[Node, ...]) -> None:
    """A listing is for finding something to run, and a group cannot be run."""
    assert [node.command for node in flatten(walked)] == [
        "pctl svc get",
        "pctl svc list",
        "pctl token",
    ]


def test_flatten_can_include_the_groups(walked: tuple[Node, ...]) -> None:
    assert [node.command for node in flatten(walked, groups=True)] == [
        "pctl svc",
        "pctl svc get",
        "pctl svc list",
        "pctl token",
    ]


def test_rows_carry_the_command_summary_and_aliases(walked: tuple[Node, ...]) -> None:
    listing = rows(flatten(walked, groups=True))

    assert listing[0] == {"command": "pctl svc", "summary": "A service.", "aliases": "s"}


def test_rows_join_aliases_into_one_cell(root: PctlGroup) -> None:
    """A list would break the one-line-per-command shape of the table and CSV forms."""

    @click.group(cls=PctlGroup, aliases={"a": "svc", "b": "svc"})
    def many() -> None:
        """Root."""

    many.add_command(root.get_command(click.Context(root), "svc"))
    listing = rows(flatten(build(many, click.Context(many)), groups=True))

    assert listing[0]["aliases"] == "a b"


# ---------------------------------------------------------------------------
# draw
# ---------------------------------------------------------------------------
def test_the_last_child_closes_the_branch(walked: tuple[Node, ...]) -> None:
    assert draw(walked, depth=None) == [
        "├── svc (s)",
        "│   ├── get",
        "│   └── list",
        "└── token",
    ]


def test_depth_stops_the_descent(walked: tuple[Node, ...]) -> None:
    assert draw(walked, depth=1) == ["├── svc (s)", "└── token"]


def test_a_depth_of_zero_draws_nothing(walked: tuple[Node, ...]) -> None:
    assert draw(walked, depth=0) == []


def test_nested_prefixes_continue_the_parent_line() -> None:
    """A group that is not last must keep its pipe running down past its children."""

    @click.group(cls=PctlGroup, lazy_subcommands={"zzz": (LEAF, "Last.")})
    def outer() -> None:
        """Outer."""

    @click.group(name="inner", cls=PctlGroup, lazy_subcommands={"leaf": (LEAF, "Leaf.")})
    def inner() -> None:
        """Inner."""

    outer.add_command(inner)
    lines: list[Any] = draw(build(outer, click.Context(outer)), depth=None)

    assert lines == ["├── inner", "│   └── leaf", "└── zzz"]
