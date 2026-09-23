"""Command discovery: `pctl commands` and `pctl tree`.

Thirty commands across four levels means the honest answer to "where is the thing I
want" used to be four separate `--help` calls with no way to search. These two share one
walk of the command tree and present it differently: `commands` emits one row per command
so it can be grepped and piped, `tree` draws the hierarchy for reading.

Neither imports an action module. Every subcommand's summary already lives in its group's
`LAZY_SUBCOMMANDS` table — that is what lets `--help` render without importing httpx or
boto3 — so the walk reads the table instead of the module. Only groups are imported, and
a group module costs click and the stdlib.

`--help` is deliberately untouched. It answers a different question: what are the flags
here, and what does this command do. A tree cannot carry that, and a flag reference
cannot tell you where to look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import click

from .config import AppContext
from .lazy import PctlGroup
from .options import output_options
from .output import Renderer, summarise

# An action module exposes exactly one object named `command`, per structure.md, so a
# target ending in `:command` is a leaf and anything else is a group. Relying on the
# convention keeps the walk from importing leaves just to ask whether they have children.
LEAF_TARGET_SUFFIX = ":command"

TREE_BRANCH = "├── "
TREE_LAST = "└── "
TREE_PIPE = "│   "
TREE_BLANK = "    "


@dataclass(frozen=True, slots=True)
class Node:
    """One command in the tree, with its full path and its children.

    `path` excludes the program name, so it is exactly what a caller types after `pctl`.
    `summary` is the short help from the parent's lazy table, or the command's own when it
    was registered directly.
    """

    name: str
    path: tuple[str, ...]
    summary: str
    aliases: tuple[str, ...] = ()
    children: tuple[Node, ...] = field(default_factory=tuple)

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    @property
    def command(self) -> str:
        return " ".join(("pctl", *self.path))


def build(group: click.Group, ctx: click.Context, path: tuple[str, ...] = ()) -> tuple[Node, ...]:
    """The children of `group`, recursively, sorted as `--help` sorts them.

    Recurses only into groups. A leaf is described entirely from its parent's table, so
    walking the whole tree imports no action module and stays fast enough to run on every
    invocation of `pctl commands`.
    """
    lazy = group.lazy_subcommands if isinstance(group, PctlGroup) else {}
    reverse = _reverse_aliases(group)
    nodes: list[Node] = []

    for name in group.list_commands(ctx):
        child_path = (*path, name)
        target, summary = lazy.get(name, ("", ""))
        aliases = tuple(sorted(reverse.get(name, ())))

        if target.endswith(LEAF_TARGET_SUFFIX):
            nodes.append(Node(name, child_path, summary, aliases))
            continue

        child = group.get_command(ctx, name)
        if child is None or child.hidden:
            continue
        children = (
            build(child, click.Context(child, info_name=name, parent=ctx), child_path)
            if isinstance(child, click.Group)
            else ()
        )
        summary = summary or child.get_short_help_str(limit=64)
        nodes.append(Node(name, child_path, summary, aliases, children))

    return tuple(nodes)


def _reverse_aliases(group: click.Group) -> dict[str, list[str]]:
    """Map a real command name to the aliases pointing at it."""
    if not isinstance(group, PctlGroup):
        return {}
    reverse: dict[str, list[str]] = {}
    for alias, real in group.aliases.items():
        reverse.setdefault(real, []).append(alias)
    return reverse


def flatten(nodes: tuple[Node, ...], *, groups: bool = False) -> list[Node]:
    """Every node in depth-first order, leaves only unless `groups` is set.

    Groups are excluded by default because a listing is for finding something to run, and
    a group cannot be run.
    """
    out: list[Node] = []
    for node in nodes:
        if node.is_group:
            if groups:
                out.append(node)
            out.extend(flatten(node.children, groups=groups))
        else:
            out.append(node)
    return out


def rows(nodes: list[Node]) -> list[dict[str, Any]]:
    """Render nodes as records for `Renderer`.

    `command` is the full invocation so a row can be copied straight to a prompt, and
    `aliases` is a space-joined string rather than a list so the table and CSV forms stay
    one line per command.
    """
    return [
        {
            "command": node.command,
            "summary": node.summary,
            "aliases": " ".join(node.aliases),
        }
        for node in nodes
    ]


def draw(nodes: tuple[Node, ...], *, depth: int | None, prefix: str = "") -> list[str]:
    """The tree as lines, with box-drawing connectors.

    `depth` counts levels below the root; None means all of them.
    """
    if depth is not None and depth <= 0:
        return []

    lines: list[str] = []
    for index, node in enumerate(nodes):
        last = index == len(nodes) - 1
        label = node.name
        if node.aliases:
            label = f"{label} ({', '.join(node.aliases)})"
        lines.append(f"{prefix}{TREE_LAST if last else TREE_BRANCH}{label}")
        if node.children:
            child_prefix = prefix + (TREE_BLANK if last else TREE_PIPE)
            lines.extend(
                draw(
                    node.children,
                    depth=None if depth is None else depth - 1,
                    prefix=child_prefix,
                )
            )
    return lines


def _walk_root(ctx: click.Context) -> tuple[Node, ...]:
    """Walk from the root group, whichever command invoked us."""
    root = ctx.find_root()
    group = root.command
    if not isinstance(group, click.Group):  # pragma: no cover - the root is always a group
        return ()
    return build(group, root)


@click.command(name="commands")
@click.option(
    "--groups/--no-groups",
    default=False,
    show_default=True,
    help="Include the group levels, which cannot be run on their own.",
)
@output_options
@click.pass_context
def commands(ctx: click.Context, groups: bool) -> None:
    """List every command in one flat, greppable table.

    One row per command, so finding something is a search rather than four rounds of
    --help. Goes through the same renderer as everything else, which is what makes it
    pipeable:

    \b
      pctl commands
      pctl commands | grep -i assign
      pctl commands -o ndjson | jq -r .command
      pctl commands -o csv > surface.csv

    Groups are left out by default because you cannot run one. Pass --groups to see the
    tree's interior as well, or use `pctl tree` to see the shape.
    """
    app = ctx.ensure_object(AppContext)
    listing = rows(flatten(_walk_root(ctx), groups=groups))

    with Renderer(app.output, columns=["command", "summary", "aliases"]) as renderer:
        renderer.write_all(listing)
    summarise(len(listing), "command", quiet=app.quiet)


@click.command(name="tree")
@click.option(
    "--depth",
    type=click.IntRange(min=1),
    default=None,
    metavar="N",
    help="Only show N levels. Default: all of them.",
)
@click.pass_context
def tree(ctx: click.Context, depth: int | None) -> None:
    """Draw the command tree, to see how the CLI is shaped.

    A reading view, not a data one: it is always text, because the nesting is the point
    and `-o json` of a drawing would be meaningless. Use `pctl commands` when you want to
    grep, pipe or filter.

    \b
      pctl tree
      pctl tree --depth 2
    """
    app = ctx.ensure_object(AppContext)
    nodes = _walk_root(ctx)

    click.echo("pctl")
    for line in draw(nodes, depth=depth):
        click.echo(line)
    summarise(len(flatten(nodes)), "command", quiet=app.quiet)
