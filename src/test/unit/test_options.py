"""Unit tests for `pctl.options`.

`read_names` is the input path for curated group lists kept in version control, so
comments, blank lines and duplicates all have defined behaviour. `split_columns`
feeds both table and csv headers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import pytest

from pctl.options import read_names, split_columns

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# split_columns
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("a", ["a"]),
        ("a,b", ["a", "b"]),
        ("  a ,  b  ", ["a", "b"]),
        ("a,,b", ["a", "b"]),
        # Only a missing value means "no opinion"; separators alone mean "nothing
        # selected", which callers treat the same as unset because [] is falsy.
        (",", []),
    ],
)
def test_split_columns(raw: str | None, expected: list[str] | None) -> None:
    assert split_columns(raw) == expected


# ---------------------------------------------------------------------------
# read_names
# ---------------------------------------------------------------------------
def test_positional_names_are_kept_in_order() -> None:
    assert read_names(("b", "a"), None) == ["b", "a"]


def test_blank_positional_names_are_dropped() -> None:
    assert read_names(("a", "  ", ""), None) == ["a"]


def test_duplicates_are_removed_but_order_is_preserved() -> None:
    assert read_names(("a", "b", "a"), None) == ["a", "b"]


def test_names_come_from_a_file(tmp_path: Path) -> None:
    listing = tmp_path / "groups.txt"
    listing.write_text("Team A\nTeam B\n", encoding="utf-8")
    assert read_names((), str(listing)) == ["Team A", "Team B"]


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    """A curated list should be able to explain itself."""
    listing = tmp_path / "groups.txt"
    listing.write_text(
        "# platform groups\n\nTeam A\n\n    # indented comment too\nTeam B\n",
        encoding="utf-8",
    )
    # Lines are stripped before the comment check, so an indented `#` still comments.
    assert read_names((), str(listing)) == ["Team A", "Team B"]


def test_names_are_stripped(tmp_path: Path) -> None:
    listing = tmp_path / "groups.txt"
    listing.write_text("  Team A  \n\tTeam B\t\n", encoding="utf-8")
    assert read_names((), str(listing)) == ["Team A", "Team B"]


def test_positional_and_file_names_are_combined(tmp_path: Path) -> None:
    listing = tmp_path / "groups.txt"
    listing.write_text("Team B\n", encoding="utf-8")
    assert read_names(("Team A",), str(listing)) == ["Team A", "Team B"]


def test_duplicates_across_sources_are_removed(tmp_path: Path) -> None:
    listing = tmp_path / "groups.txt"
    listing.write_text("Team A\n", encoding="utf-8")
    assert read_names(("Team A",), str(listing)) == ["Team A"]


def test_an_unreadable_file_is_a_parameter_error(tmp_path: Path) -> None:
    with pytest.raises(click.BadParameter, match="cannot read"):
        read_names((), str(tmp_path / "missing.txt"))


def test_a_dash_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("Team A\n# skip\nTeam B\n"))
    assert read_names((), "-") == ["Team A", "Team B"]


def test_an_empty_file_yields_nothing(tmp_path: Path) -> None:
    listing = tmp_path / "groups.txt"
    listing.write_text("\n# only a comment\n", encoding="utf-8")
    assert read_names((), str(listing)) == []
