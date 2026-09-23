"""Unit tests for `pctl.output`.

The renderer is the one place every command's result passes through, and its
contract is what scripts depend on: ndjson stays one record per line, json collapses
a single result to an object, csv and table echo the requested columns verbatim, and
a closed downstream pipe is swallowed rather than raised. Each of those is asserted
on exact bytes.
"""

from __future__ import annotations

import io
import sys
from decimal import Decimal

import pytest

from pctl.config import OutputFormat
from pctl.output import Renderer, dumps, render, summarise

pytestmark = pytest.mark.unit


Out = pytest.CaptureFixture[bytes]


@pytest.fixture
def out(capfdbinary: Out) -> Out:
    """Capture stdout at file-descriptor level, as bytes.

    The renderer writes bytes straight to `sys.stdout.buffer`, so capture has to
    happen below the text layer. Monkeypatching `sys.stdout` does not work here:
    pytest reassigns it when it resumes capturing for the call phase, which would
    discard the replacement. A captured fd is also not a tty, which is exactly the
    pipe case the renderer optimises for.
    """
    return capfdbinary


def value(out: Out) -> str:
    """Drain and decode what has been written so far. Call once per assertion."""
    return out.readouterr().out.decode()


# ---------------------------------------------------------------------------
# ndjson
# ---------------------------------------------------------------------------
def test_ndjson_writes_one_compact_line_per_record(out: Out) -> None:
    count = render([{"a": 1}, {"a": 2}], OutputFormat.NDJSON)
    assert count == 2
    assert value(out) == '{"a":1}\n{"a":2}\n'


def test_ndjson_of_nothing_writes_nothing(out: Out) -> None:
    assert render([], OutputFormat.NDJSON) == 0
    assert value(out) == ""


# ---------------------------------------------------------------------------
# json
# ---------------------------------------------------------------------------
def test_json_emits_an_array(out: Out) -> None:
    render([{"a": 1}, {"a": 2}], OutputFormat.JSON)
    assert value(out) == '[{"a":1},{"a":2}]\n'


def test_json_single_collapses_one_record_to_an_object(out: Out) -> None:
    render([{"a": 1}], OutputFormat.JSON, single=True)
    assert value(out) == '{"a":1}\n'


def test_json_single_still_arrays_when_there_are_two(out: Out) -> None:
    render([{"a": 1}, {"a": 2}], OutputFormat.JSON, single=True)
    assert value(out) == '[{"a":1},{"a":2}]\n'


def test_json_empty_is_null_for_single_and_array_otherwise(out: Out) -> None:
    render([], OutputFormat.JSON, single=True)
    assert value(out) == "null\n"


def test_json_empty_array(out: Out) -> None:
    render([], OutputFormat.JSON)
    assert value(out) == "[]\n"


# ---------------------------------------------------------------------------
# csv
# ---------------------------------------------------------------------------
def test_csv_header_comes_from_columns(out: Out) -> None:
    render([{"b": 2, "a": 1}], OutputFormat.CSV, columns=["a", "b"])
    assert value(out).splitlines() == ["a,b", "1,2"]


def test_csv_header_falls_back_to_first_record(out: Out) -> None:
    render([{"a": 1, "b": 2}], OutputFormat.CSV)
    assert value(out).splitlines()[0] == "a,b"


def test_csv_ignores_odata_keys_when_inferring(out: Out) -> None:
    render([{"@odata.etag": "x", "a": 1}], OutputFormat.CSV)
    assert value(out).splitlines()[0] == "a"


def test_csv_flattens_containers_and_blanks_none(out: Out) -> None:
    render(
        [{"a": None, "b": ["x", "y"], "c": {"k": 1}, "d": True}],
        OutputFormat.CSV,
        columns=["a", "b", "c", "d"],
    )
    # Containers are JSON-encoded so the cell stays machine-readable, which means
    # csv has to quote them and double the embedded quotes.
    assert value(out).splitlines()[1] == ',"[""x"",""y""]","{""k"":1}",true'


def test_csv_missing_column_is_empty(out: Out) -> None:
    render([{"a": 1}], OutputFormat.CSV, columns=["a", "missing"])
    assert value(out).splitlines() == ["a,missing", "1,"]


# ---------------------------------------------------------------------------
# table
# ---------------------------------------------------------------------------
def test_table_header_is_verbatim_and_ruled(out: Out) -> None:
    render([{"pk": "a", "id": "b"}], OutputFormat.TABLE, columns=["pk", "id"])
    header, rule, row = value(out).splitlines()
    assert header.split() == ["pk", "id"]
    assert set(rule) == {"-", " "}
    assert row.split() == ["a", "b"]


def test_table_columns_are_padded_to_the_widest_cell(out: Out) -> None:
    render([{"a": "short"}, {"a": "a much longer value"}], OutputFormat.TABLE, columns=["a"])
    lines = value(out).splitlines()
    assert lines[1] == "-" * len("a much longer value")


def test_table_renders_placeholders_for_empty_values(out: Out) -> None:
    render([{"a": None, "b": [], "c": False}], OutputFormat.TABLE, columns=["a", "b", "c"])
    assert value(out).splitlines()[2].split() == ["-", "-", "false"]


def test_table_truncates_long_cells(out: Out) -> None:
    render([{"a": "x" * 200}], OutputFormat.TABLE, columns=["a"])
    cell = value(out).splitlines()[2]
    assert len(cell) == 60
    assert cell.endswith("…")


def test_table_says_so_when_there_is_nothing(out: Out) -> None:
    assert render([], OutputFormat.TABLE) == 0
    assert value(out) == "No results.\n"


# ---------------------------------------------------------------------------
# type coercion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("7"), b'{"a":7}'),
        (Decimal("1234.50"), b'{"a":1234.5}'),
        (b"\xff\x00", b'{"a":"ff00"}'),
        ({"x", "y"}, b'{"a":["x","y"]}'),
    ],
)
def test_dumps_coerces_types_json_cannot_represent(raw: object, expected: bytes) -> None:
    assert dumps({"a": raw}) == expected


def test_dumps_keeps_integral_decimals_integral() -> None:
    """A numeric id must not come back as 1.0."""
    assert dumps({"id": Decimal("1")}) == b'{"id":1}'


# ---------------------------------------------------------------------------
# pipes and counting
# ---------------------------------------------------------------------------
def test_broken_pipe_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pctl ... | head -1` must exit cleanly rather than raising."""

    class ClosedPipe(io.BytesIO):
        """Fails every write and flush while `live`, like a pipe whose reader exited."""

        live = True

        def write(self, data: object) -> int:
            if self.live:
                raise BrokenPipeError
            return len(data)  # type: ignore[arg-type]

        def flush(self) -> None:
            if self.live:
                raise BrokenPipeError

    pipe = ClosedPipe()
    stream = io.TextIOWrapper(pipe, encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", stream)
    try:
        renderer = Renderer(OutputFormat.NDJSON)
        for index in range(5):
            renderer.write({"a": index})
        assert renderer.close() >= 0
    finally:
        # Stop failing before teardown, so the wrapper's finaliser cannot raise
        # during garbage collection.
        pipe.live = False
        stream.detach()


def test_renderer_counts_written_records(out: Out) -> None:
    with Renderer(OutputFormat.NDJSON) as renderer:
        renderer.write_all([{"a": 1}, {"a": 2}, {"a": 3}])
        assert renderer.count == 3


def test_summarise_pluralises_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    summarise(1, "group")
    summarise(2, "group")
    err = capsys.readouterr().err
    assert err.splitlines() == ["1 group", "2 groups"]


def test_summarise_is_silent_when_quiet(capsys: pytest.CaptureFixture[str]) -> None:
    summarise(3, "item", quiet=True)
    assert capsys.readouterr().err == ""
