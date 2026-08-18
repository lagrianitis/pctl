# Code Style

Canonical style rules for this project. Supersedes the separate Python and comment
guides, which were merged in here.

## Formatting

Enforced by ruff, configured in `pyproject.toml`. The config is the source of truth:

- **Line length 100.** This is what `[tool.ruff] line-length` enforces and what the
  existing code follows. Earlier drafts of these rules said 79 and 88; both are wrong for
  this repo. Change `pyproject.toml` first if you want a different number.
- Indent 4 spaces. `target-version = "py314"`.
- Lint select: `E, F, I, UP, B, SIM, C4, RUF`. Ignore `B008`, since click legitimately
  calls functions in option defaults.
- Formatting is ruff's job, not a hand exercise. Do not introduce Black as a second
  formatter; `ruff format` is Black-compatible.

## Naming

- `snake_case` for functions, variables, modules.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.
- Name things for what they **do**, not what they are: `calculate_risk_score()`, not
  `processor()`.
- No magic numbers or strings. Use a named constant, as `GRAPH_MAX_PAGE_SIZE` and
  `MAX_SEGMENTS` do.

## Type hints

Python 3.14, so use modern syntax. Ruff's `UP` rules will flag the alternatives.

- Annotate every function parameter and return value, including click callbacks.
- `X | None`, never `Optional[X]`. `X | Y`, never `Union[X, Y]`. Built-in generics
  (`list[str]`, `dict[str, int]`), never `typing.List`.
- Every module starts with `from __future__ import annotations`.
- **Avoid `Any`.** Define the type. Where a third-party boundary genuinely has no useful
  type (click's context object, a boto3 client, a respx router), `Any` is acceptable in
  the signature — that is why it appears in `options.py`, `output.py` and `conftest.py`.
  Do not use it to skip thinking about an internal type.

## Imports

Ordered stdlib → third-party → local, enforced by ruff's `I` rules. Heavy imports
(`boto3`, `httpx`, `orjson`) go **inside** the function or fixture body, never at module
scope on a path that `--help` touches. See `structure.md`.

## Functions

- **Maximum 25 lines.** If longer, decompose. (An earlier draft said 50; 25 wins.)
- **Maximum 3 parameters**, using a dataclass for more — as `ScanRequest` does.
  **Exception:** click command callbacks receive one parameter per option and are exempt;
  that shape is dictated by the decorators, and the options themselves are grouped into
  reusable decorators such as `read_options` and `aws_options`.
- Maximum nesting depth 3.
- One responsibility per function. Clear return types.

## Error handling

- Raise the specific error types from `errors.py` — `ConfigError`, `AuthError`,
  `NotFoundError`, `UpstreamError` — so exit codes stay consistent. Never `sys.exit()`
  from command code.
- Never swallow an exception silently.
- Use context managers for anything holding a resource: `Renderer`, httpx clients, file
  handles.
- Diagnostics go to stderr through `app.log()`, never to stdout.

## Comments — keep to a minimum

Write code that explains itself. Add a comment only when it carries information the code
cannot. Most comments are noise: they restate the code, drift out of sync, and cost
maintenance.

**Default: no comment.** In particular, avoid:

- Comments that restate the code (`i += 1  # increment i`).
- Section banners and decorative dividers in new code.
- Docstrings that just echo the function name and signature.
- Commented-out code. Delete it; git keeps the history.
- Change-log comments (author, date, "modified by"). That belongs in git.
- TODO/FIXME left in place of doing or tracking the work.

**A comment is warranted when it adds what the code cannot:**

- **Why, not what** — intent, a non-obvious tradeoff, the reason for a surprising
  approach. The `$top=999` and segment-count notes in this codebase are the model.
- **Warnings** — gotchas, side effects, ordering or concurrency assumptions not visible
  locally, such as why fixtures are per-test under xdist.
- **External context** — a spec, standard, ticket, or a workaround for a known library
  quirk, with a link or ID.
- **Non-obvious math or algorithms** — cite the formula, source or invariant.

**Prefer better code over comments:** rename for intent, extract a named function instead
of a comment introducing a block, name a constant instead of explaining a number.

## Docstrings

- Every module gets a docstring saying why it exists, not just what it contains.
- Public functions get a docstring where it adds meaning beyond the signature.
- **Command docstrings are user-facing output.** Click renders them as `--help`, so they
  are mandatory on every `command`, use `\b` blocks for examples, and must stay accurate.
  Do not reformat them into `Args:`/`Returns:` sections; that changes what `pctl --help`
  prints.
- Fixtures get a docstring saying what they yield and any gotcha for consumers.
- Otherwise keep comments and docstrings short, current, and consistent with the
  surrounding file.
