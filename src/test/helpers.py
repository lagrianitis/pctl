"""Assertion helpers shared by the pytest tiers.

Exit codes are a published contract for this CLI, so asserting on them is common
enough to deserve helpers that explain a mismatch properly. A bare
`assert result.exit_code == 0` tells you nothing about why; these print stderr and
the underlying traceback instead.
"""

from __future__ import annotations

from typing import Any


def lines(text: str) -> list[str]:
    """Non-empty lines of a command's stdout."""
    return [line for line in text.strip().splitlines() if line]


def help_for(runner: Any, cli: Any, path: list[str], flag: str = "--help") -> Any:
    """Render help the way the installed entry point does.

    `prog_name` matters: `CliRunner` would otherwise label usage lines `cli`, while
    real users see `pctl`, and the usage line is what these tests assert on.
    """
    return ok(runner.invoke(cli, [*path, flag], prog_name="pctl"))


def ok(result: Any) -> Any:
    """Assert a command succeeded, reporting stderr and any traceback when it did not."""
    if result.exit_code != 0:
        raise AssertionError(_explain(result, 0))
    return result


def failed(result: Any, exit_code: int) -> Any:
    """Assert a command exited with a specific code."""
    if result.exit_code != exit_code:
        raise AssertionError(_explain(result, exit_code))
    return result


def _explain(result: Any, want: int) -> str:
    parts = [f"expected exit code {want}, got {result.exit_code}"]
    if stderr := (result.stderr or "").strip():
        parts.append(f"stderr: {stderr}")
    if stdout := (result.stdout or "").strip():
        parts.append(f"stdout: {stdout[:500]}")
    if result.exception and not isinstance(result.exception, SystemExit):
        import traceback

        parts.append(
            "".join(
                traceback.format_exception(
                    type(result.exception), result.exception, result.exception.__traceback__
                )
            )
        )
    return "\n".join(parts)
