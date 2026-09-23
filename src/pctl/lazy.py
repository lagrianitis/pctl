"""Command group helpers: lazy imports, aliases and prefix matching.

Importing `boto3` costs several hundred milliseconds and `httpx` tens more, so
`pctl --help` should not pay for either. `PctlGroup` resolves `"module:attribute"`
targets only when a subcommand actually runs, and keeps help text inline so that
rendering `--help` imports nothing at all.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

import click


class PctlGroup(click.Group):
    """A `click.Group` with lazily imported subcommands, aliases and prefix matching.

    `lazy_subcommands` maps a command name to a `(import_target, short_help)` pair,
    where `import_target` is `"package.module:command_object"`.
    """

    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, tuple[str, str]] | None = None,
        aliases: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lazy: dict[str, tuple[str, str]] = dict(lazy_subcommands or {})
        self._aliases: dict[str, str] = dict(aliases or {})

    # -- introspection ----------------------------------------------------
    @property
    def lazy_subcommands(self) -> dict[str, tuple[str, str]]:
        """The lazy table: name -> (import target, short help).

        Exposed so that something walking the command tree can read a subcommand's
        summary, and tell a group from an action by its target, without importing the
        module behind it. That is the whole point of keeping the help text in the table,
        and `surface.py` is the caller that depends on it.

        A copy, so a caller cannot mutate the table it is reading.
        """
        return dict(self._lazy)

    @property
    def aliases(self) -> dict[str, str]:
        """Alternative spellings: alias -> real command name."""
        return dict(self._aliases)

    # -- resolution -------------------------------------------------------
    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted({*super().list_commands(ctx), *self._lazy})

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd_name = self._aliases.get(cmd_name, cmd_name)
        if cmd_name in self._lazy:
            return self._import(cmd_name)
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        return self._match_prefix(ctx, cmd_name)

    def _import(self, cmd_name: str) -> click.Command:
        target = self._lazy[cmd_name][0]
        module_name, _, attr = target.partition(":")
        command = getattr(import_module(module_name), attr)
        if not isinstance(command, click.Command):
            raise TypeError(f"{target} did not resolve to a click command")
        return command

    def shell_complete(self, ctx: click.Context, incomplete: str) -> list[Any]:
        """Complete subcommand names, their aliases, and this group's own options.

        click completes only what `list_commands` returns, which excludes aliases, so
        `pctl azure enter<TAB>` offered nothing even though `enterprise-apps` resolves.
        They are added here, labelled, and sorted after the real names so the canonical
        spelling is what you get first.
        """
        from click.shell_completion import CompletionItem

        items = list(super().shell_complete(ctx, incomplete))
        items.extend(
            CompletionItem(alias, help=f"alias for {real}")
            for alias, real in sorted(self._aliases.items())
            if alias.startswith(incomplete)
        )
        return items

    def _match_prefix(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Allow unambiguous prefixes, so `pctl az gr li` works."""
        candidates = [name for name in self.list_commands(ctx) if name.startswith(cmd_name)]
        if len(candidates) == 1:
            return self.get_command(ctx, candidates[0])
        if len(candidates) > 1:
            ctx.fail(f"'{cmd_name}' is ambiguous: {', '.join(sorted(candidates))}")
        return None

    # -- help -------------------------------------------------------------
    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: list[tuple[str, str]] = []
        reverse_aliases: dict[str, list[str]] = {}
        for alias, target in self._aliases.items():
            reverse_aliases.setdefault(target, []).append(alias)

        for name in self.list_commands(ctx):
            if name in self._lazy:
                help_text = self._lazy[name][1]
            else:
                command = super().get_command(ctx, name)
                if command is None or command.hidden:
                    continue
                help_text = command.get_short_help_str(limit=64)
            label = name
            if aliases := reverse_aliases.get(name):
                label = f"{name} ({', '.join(sorted(aliases))})"
            rows.append((label, help_text))

        if rows:
            with formatter.section("Commands"):
                formatter.write_dl(rows)


# Backwards-friendly alias: the group is primarily about lazy loading.
LazyGroup = PctlGroup
