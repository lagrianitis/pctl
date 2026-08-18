# Tech stack

## Runtime

- **Python >= 3.14.** Use modern syntax freely: `X | None`, `StrEnum`,
  `match`, `dataclass(slots=True)`. Every module starts with
  `from __future__ import annotations`.
- **hatchling** is the build backend; the wheel packages `src/pctl`.

## Package management: uv only

**uv is the only Python package manager used here.** Every dependency is installed,
synchronised and locked through uv, with no exceptions and no second tool alongside it.

- `pyproject.toml` + `uv.lock` are the single source of truth. Both are committed, and
  `uv.lock` is never hand-edited.
- **Never run `pip`, `pip-tools`, `poetry`, `pipenv`, `conda`, `virtualenv` or
  `python -m venv`.** uv manages the environment and the interpreter.
- **Always install into a project-local `.venv`.** `uv sync` creates and uses
  `./.venv` at the workspace root by default, so let it. Never install into the system
  or user site-packages, never `pip install --user`, and never share one environment
  across projects. `.venv` is gitignored and disposable: if it drifts, delete it and
  re-run `uv sync` rather than patching it by hand.
- Do not activate the venv manually to run things; `uv run` resolves it for you. If a
  tool genuinely needs an interpreter path, use `.venv/bin/python`.
- Run project code with `uv run ...`, never a bare `python`/`pytest` that depends on
  whatever happens to be on `PATH`.
- There is deliberately **no `requirements.txt`**. Do not add one, and do not
  hand-maintain a pinned flat file. If a pip-only environment truly needs one, generate
  it: `uv export --no-dev --format requirements-txt > requirements.txt`.
- Add and remove dependencies with `uv add` / `uv remove` (`--group dev`,
  `--group test`, `--optional fast`) so `pyproject.toml` and the lock stay in step.
  Editing `pyproject.toml` by hand means following it with `uv lock`.
- Commit the updated `uv.lock` alongside any dependency change.
- CI and containers install with `uv sync --frozen` (or `--no-dev` for app-only images)
  so builds match the lock exactly rather than re-resolving.

| Task | Command |
| --- | --- |
| install dev env | `uv sync --extra fast --extra azure` |
| install app-only | `uv sync --no-dev` |
| reproducible install | `uv sync --frozen` |
| add a runtime dep | `uv add <pkg>` |
| add a test/dev dep | `uv add --group test <pkg>` |
| refresh the lock | `uv lock` (or `uv lock --upgrade-package <pkg>`) |
| run anything | `uv run <cmd>` |

## Dependencies

| Where | What | Ships to an app install? |
| --- | --- | --- |
| `[project] dependencies` | `click`, `httpx`, `orjson`, `boto3` | yes |
| extra `fast` | `uvloop`, `h2` | only with `pctl[fast]` |
| extra `azure` | `azure-identity` (fallback credential chain) | only with `pctl[azure]` |
| group `test` | `pytest`, `pytest-xdist`, `pytest-asyncio`, `respx`, `moto[dynamodb]` | no |
| group `dev` | the `test` group plus `ruff` | no |

Keep runtime dependencies to those four. Test tooling belongs in **PEP 735
`[dependency-groups]`**, not in `[project.optional-dependencies]`, so it never lands
in wheel metadata. Optional packages (`uvloop`, `h2`, `azure-identity`) must be
detected at runtime and degrade gracefully when absent.

## Commands

```bash
# setup
uv sync --extra fast --extra azure     # dev env, includes the dev dependency group
uv sync --no-dev                       # app-only env, no pytest/moto/respx/ruff

# run
uv run pctl --help
uv run pctl azure groups list -o ndjson

# lint / format
uv run ruff check .
uv run ruff format .

# tests
uv run pytest                          # live output, easier to debug
uv run pytest -n auto                  # full run across CPUs
uv run python src/test/smoke/run_all.py         # end-to-end smoke suite
uv run python src/test/smoke/azure_graph.py     # Graph only
uv run python src/test/smoke/aws_dynamodb.py    # DynamoDB only
```

## Containers

**Use `podman`, never `docker`.** Podman is the container runtime on this project, so
any command, script, Makefile target or documentation snippet must call `podman`
directly rather than relying on a `docker` alias.

```bash
podman build -t pctl .
podman run --rm pctl --help
podman compose up          # not `docker compose`
```

If you find an existing `docker ...` invocation, replace it with the `podman`
equivalent. The CLI is argument-compatible for the common cases, so the swap is
usually a straight rename; `docker-compose` becomes `podman compose`.

## Lint and style rules

- `ruff`, line length **100**, `target-version = "py314"`.
- Lint select: `E, F, I, UP, B, SIM, C4, RUF`; ignore `B008` (click decorators
  legitimately call functions in defaults). `IGNORE-*` paths are excluded.
- Every module gets a docstring that explains *why* it exists, not just what it
  contains. Existing modules explain performance and design tradeoffs inline —
  match that habit.
- Type-annotate all public functions, including click callbacks.

## Testing

### Mocking AWS

Fake AWS at the wire, never at the object level.

1. **Default: `moto`.** Wrap the test or fixture in `mock_aws` and drive real `boto3`
   clients against it, as `ddb_table` in `src/test/conftest.py` does. Tests then
   exercise the same serialisation, pagination and error shapes as production.
2. **Fallback: `botocore.stub.Stubber`**, and only when moto does not support the
   service or operation. Stub the client, queue responses with
   `add_response` / `add_client_error`, and call `assert_no_pending_responses()`.
3. **Never `unittest.mock.MagicMock` (or `patch`) for AWS clients or their
   responses.** A MagicMock accepts any call and returns anything, so it verifies the
   test's assumptions instead of the code's behaviour and stays green when an API
   contract changes.

`monkeypatch` remains fine for environment variables, clocks and other non-AWS
seams. Always set dummy credentials and a fixed region before a moto-backed test (see
the `aws_env` fixture) so a developer's real profile can never be reached.

Microsoft Graph is the same principle at its own boundary: stub HTTP with `respx`,
not with mocked `httpx` objects.

### Shared test code lives in fixtures

Anything reused by more than one test becomes a **`pytest.fixture` in `conftest.py`**.
Do not copy setup between test modules, and do not hand-roll setup/teardown helper
functions that tests call themselves.

- Put the fixture in the nearest `conftest.py` that covers every consumer: shared
  across tiers goes in `src/test/conftest.py`, used by one tier only goes in that
  tier's `conftest.py`.
- Build on existing fixtures by requesting them as parameters rather than repeating
  their setup — that is how `ddb_table` depends on `aws_env`, and `graph` on
  `graph_env`.
- Resources that need teardown use `yield`, so cleanup runs even when a test fails.
- Keep fixtures **per-test scoped** unless there is a measured reason not to.
  `pytest-xdist` runs tests across processes in an unspecified order, and several
  checks assert on request counts and token-cache state, so shared state makes results
  order-dependent.
- Import heavy modules **inside** the fixture body, not at module scope, so collection
  stays cheap (see the `cli` and `ddb_table` fixtures).
- Plain constants and static sample data belong in the `helpers` module, not in a
  fixture. Reserve fixtures for things that need construction, wiring or cleanup.
- Give each fixture a docstring saying what it yields and any gotcha for its
  consumers.

- `testpaths = ["src/test"]`, `asyncio_mode = "auto"`,
  `addopts = "-ra --strict-markers --strict-config"`.
- `src/test/smoke/*` are **standalone scripts run directly**, not collected by
  pytest. They drive the real CLI through `click.testing.CliRunner` and fake only the
  provider boundary: Graph via `respx`, DynamoDB via `moto`. No credentials, no
  network, no tenant, no AWS account.
- Smoke checks are *counted*, not asserted, so one failure does not mask the rest.
- Two gotchas when writing smoke checks: read data from `result.stdout` (click 8.2+
  merges stderr into `result.output`, and this CLI writes summaries to stderr), and
  decode request URLs with `unquote_plus` before matching (httpx percent-encodes
  OData names like `%24filter` and encodes spaces as `+`).

### Always take the fastest path

Default to the fastest way to develop and run tests. A slow suite gets run less often,
so speed is correctness in practice.

- **Full runs use `uv run pytest -n auto`**, spreading work across CPUs via
  pytest-xdist.
- **Narrow the selection while iterating.** Target the file or test rather than the
  suite: `uv run pytest src/test/unit/test_config.py -k resolve`, plus `--lf`/`--ff`
  and `-x` to stop at the first failure. Do not re-run everything to check one change;
  run the full suite once at the end to verify.
- **Keep collection cheap.** Import heavy modules inside the fixture or test body, not
  at module scope, exactly as `conftest.py` does.
- **Never wait on real time or a real network.** Collapse retry backoff with the
  `no_sleep` fixture, and fake the provider boundary with moto and respx. No `sleep`
  calls, no polling loops, no live endpoints outside the `live` tier.
- **Reuse work, but not state.** Fixtures stay per-test for xdist safety; make setup
  cheap rather than widening scope. If a fixture is genuinely expensive and provably
  read-only, propose a wider scope and explain the tradeoff first.
- Use `uv run` / `uv sync` rather than ad-hoc `pip install`, and `--extra fast` locally
  so `uvloop` and `h2` are in play.

One deliberate exception: `-n auto` is **not** in `addopts`, because parallel workers
hide live output and complicate debugging. When diagnosing a specific failure, run
serially on purpose. That is the fast path for that task.

**If you explicitly ask for a slower approach, warn and confirm before proceeding.**
Say which option is slower and why, give the faster alternative, then wait for your
go-ahead. Do not silently comply, and do not silently substitute the faster option
either.

### Warnings are failures

A test run must finish with **zero warnings**. Treat any warning in the pytest summary
as a defect to fix, in the same pass as the change that surfaced it — not as noise to
scroll past.

- **Fix the cause, do not silence it.** No `filterwarnings = ignore`, no blanket
  `-W ignore`, no `warnings.simplefilter("ignore")`, no `# noqa` on the offending line.
- `DeprecationWarning` from a library means the call site needs updating now, while it
  is a warning, rather than after the next release turns it into a breakage.
- `PytestUnraisableExceptionWarning` or `ResourceWarning` usually means an unclosed
  `httpx` client, boto3 session or file handle. Close it, normally by moving the
  resource into a fixture that yields and tears down.
- `PytestUnknownMarkWarning` means the marker is missing from `markers`. Register it;
  `--strict-markers` is already enabled, so this should surface as an error.
- `pytest-asyncio` warnings about event loops or fixture scope mean the async test is
  wired wrongly. Fix the wiring rather than pinning around it.
- The only acceptable suppression is a **warning you assert on deliberately**, scoped
  to that test with `pytest.warns(...)` or a narrowly targeted `filterwarnings` marker
  naming the exact category and message. Add a comment saying why.
- The same applies to the smoke scripts: a check that passes while emitting warnings
  is not a passing check.

If a warning comes from a dependency and genuinely cannot be fixed at the call site,
say so explicitly and propose the narrowest scoped filter rather than adding a global
ignore.

## CI

GitLab CI (`.gitlab-ci.yml`) with stages `mr-review`, `test`, `deploy`. Releases are
tag-triggered and build release notes from the changelog API. Runner images and the
PyPI mirror come from Artifactory.
