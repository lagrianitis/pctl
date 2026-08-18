"""Root CLI definition.

Only click and the stdlib are imported at module load. `httpx`, `boto3` and orjson
arrive with the subcommand that needs them, which keeps `pctl --help` and shell
completion in the low tens of milliseconds.
"""

from __future__ import annotations

import click

from . import __version__
from .config import AppContext, OutputFormat
from .lazy import PctlGroup

# One entry per case. Each case package owns its services, and each service owns
# its actions, all resolved lazily so `--help` imports nothing heavy.
LAZY_COMMANDS: dict[str, tuple[str, str]] = {
    "azure": ("pctl.azure:azure", "Microsoft Graph: tokens, groups and group members."),
    "aws": ("pctl.aws:aws", "AWS: read items and metadata from DynamoDB."),
}

ALIASES = {"az": "azure", "graph": "azure", "ddb": "aws"}

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 100,
}


@click.group(
    cls=PctlGroup,
    lazy_subcommands=LAZY_COMMANDS,
    aliases=ALIASES,
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=False,
)
@click.version_option(__version__, "-V", "--version", prog_name="pctl")
@click.option(
    "-o",
    "--output",
    type=click.Choice([fmt.value for fmt in OutputFormat]),
    default=OutputFormat.TABLE.value,
    show_default=True,
    metavar="FORMAT",
    help="Output format for every command.",
)
@click.option("-q", "--quiet", is_flag=True, help="Suppress result summaries on stderr.")
@click.option("-v", "--verbose", is_flag=True, help="Log progress to stderr.")
@click.option(
    "--timeout",
    type=click.FloatRange(min=0.1),
    default=30.0,
    show_default=True,
    metavar="SECONDS",
    help="Per-request timeout.",
)
@click.option(
    "--concurrency",
    type=click.IntRange(1, 64),
    default=16,
    show_default=True,
    metavar="N",
    help="Maximum in-flight Graph requests.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    output: str,
    quiet: bool,
    verbose: bool,
    timeout: float,
    concurrency: int,
) -> None:
    """pctl - a fast CLI for Entra ID groups and DynamoDB items.

    \b
    Common tasks:
      pctl azure token                          acquire a Graph token (cached)
      pctl azure groups list                    every group, paginated
      pctl azure groups list --starts-with aws- filter server-side
      pctl azure groups get "Team A" "Team B"   details by display name
      pctl aws ddb scan my-table -n 20          items from a table
      pctl aws ddb query my-table --key "pk = :pk" --values '{":pk":"a"}'

    \b
    Output:
      -o table   aligned columns for humans (default)
      -o json    a single JSON document
      -o ndjson  one JSON object per line, streamed
      -o csv     spreadsheet friendly

    Data goes to stdout and diagnostics to stderr, so pipes stay clean.
    """
    ctx.obj = AppContext(
        output=OutputFormat(output),
        quiet=quiet,
        verbose=verbose,
        timeout=timeout,
        concurrency=concurrency,
    )


@cli.command("completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Print shell completion setup instructions.

    Example: pctl completion zsh
    """
    variable = "_PCTL_COMPLETE"
    snippets = {
        "bash": f'eval "$({variable}=bash_source pctl)"  # add to ~/.bashrc',
        "zsh": f'eval "$({variable}=zsh_source pctl)"    # add to ~/.zshrc',
        "fish": f"{variable}=fish_source pctl | source     # add to "
        "~/.config/fish/completions/pctl.fish",
    }
    click.echo(snippets[shell])
