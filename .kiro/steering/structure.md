# Project structure

The tree mirrors the command line: **case → service → action**. `pctl aws ddb scan`
lives in `aws/dynamodb/scan.py`; `pctl azure groups get` in `azure/groups/get.py`.

```
src/pctl/
├── __main__.py            entry point (`pctl = "pctl.__main__:main"`)
├── cli.py                 root group, global flags, completion, LAZY_COMMANDS case table
├── lazy.py                PctlGroup: lazy imports, aliases, prefix matching
├── surface.py             `pctl commands` and `pctl tree`: walks the lazy tables
├── jwt.py                 masking a token and reading its claims, shared by azure and oauth
├── config.py              AppContext, AzureConfig, AwsConfig, OutputFormat
├── options.py             shared click options (output, azure, aws, columns)
├── output.py              Renderer: table / json / ndjson / csv
├── errors.py              PctlError subclasses mapped to exit codes
├── tokencache.py          on-disk token cache (0600 in a 0700 dir)
├── secrets.py             client credentials from AWS Secrets Manager
├── azure/                 case
│   ├── __init__.py          `azure` group + graph_client() shared by its actions
│   ├── graph.py             Graph transport: token, retries, pagination
│   ├── common.py            helpers shared by several services (find_user, ...)
│   ├── token.py             case-level action (no service)
│   ├── raw.py               case-level action (no service)
│   ├── groups/            service
│   │   ├── __init__.py      `groups` group + LAZY_SUBCOMMANDS, re-exports
│   │   ├── common.py        shared options/helpers (match_option, resolve_one, ...)
│   │   ├── list.py          action
│   │   ├── get.py           action
│   │   └── members.py       action
│   ├── users/             service: get
│   ├── applications/      service (exposed as `apps`): list, get
│   ├── service_principals/ service (exposed as `sp`): list, get, assignments, owners,
│   │                        add-owner, remove-owner, provision
│   └── entitlements/      service (exposed as `eam`): packages, catalogs, assignments,
│       │                    requests
│       └── runner.py        list/get bodies shared by packages and catalogs
├── oauth/                 case (case-level actions only, like azure token)
│   ├── __init__.py          `oauth` group (aliases `auth`, `auth0`)
│   ├── client.py            token endpoint transport: discovery, grants, machine-token cache
│   ├── common.py            token record, --raw/--decode, how a token is shown
│   ├── token.py             action: client credentials
│   ├── login.py             action: browser login
│   ├── browser.py           PKCE, authorize URL, redirect checks (pure)
│   └── loopback.py          one-shot listener for a loopback redirect, imported lazily
└── aws/                   case
    ├── __init__.py          `aws` group
    └── dynamodb/          service (exposed as `ddb`)
        ├── __init__.py      `ddb` group + LAZY_SUBCOMMANDS, re-exports
        ├── common.py        shared options/helpers (read_options, parse_json_option)
        ├── client.py        DynamoDB transport: parallel scan, query, get
        ├── tables.py · describe.py · scan.py · query.py · get.py    actions

src/test/
├── conftest.py            fixtures shared by every tier: `runner`, `cli`
├── helpers.py             constants and static sample data (TENANT, TABLE, FAKE_JWT)
├── unit/                  pure functions, no I/O. One module per shared component,
│   │                        then one package per case
│   ├── test_config.py · test_errors.py · test_lazy.py · test_surface.py · test_jwt.py
│   ├── test_options.py · test_output.py · test_tokencache.py
│   ├── azure/           case
│   │   ├── conftest.py      fixtures shared by this case's tests
│   │   └── test_graph.py · test_common.py · test_entitlements.py · ...
│   ├── oauth/           case
│   │   └── test_browser.py  PKCE, authorize URL, redirect checks
│   └── aws/             case
│       ├── conftest.py
│       └── test_dynamodb.py
├── smoke/                 the CLI surface is alive: help, version, exit 2 on bad input.
│   │                        No provider is faked because none is reached. README.md here
│   ├── conftest.py          strips provider credentials for every smoke test
│   ├── test_cli_surface.py  cross-case surface: aliases, prefixes, lazy-import guard
│   ├── azure/           case
│   │   ├── conftest.py
│   │   └── test_groups.py · test_users.py · test_token.py · ...   one per service
│   ├── oauth/           case
│   │   ├── conftest.py
│   │   └── test_token.py · test_login.py    one per case-level action
│   └── aws/             case
│       ├── conftest.py
│       └── test_dynamodb.py
└── e2e/                   argv to the wire through CliRunner, provider boundary faked
    ├── conftest.py          `no_sleep` and `seen`, shared by both cases
    ├── azure/           case
    │   ├── conftest.py      Graph via respx: the `graph` router and its env scoping
    │   ├── test_groups.py · test_users.py · test_token.py · test_raw.py · ...
    │   └── test_failures.py error paths for the case
    ├── oauth/           case
    │   ├── conftest.py      provider via respx, plus `user` (plays the browser) and `free_port`
    │   └── test_token.py · test_login.py
    └── aws/             case
        ├── conftest.py      DynamoDB via moto: `aws_env`, `ddb_table`, `ddb`
        ├── test_dynamodb.py
        └── test_failures.py
```

Three tiers, selected by marker: `uv run pytest -m unit`, `-m smoke`, `-m e2e`. Smoke must
stay under a second; it is the tier to run while editing.

## Tests mirror the package

The test tree follows the same **case → service** namespacing as `src/pctl`, so the
tests for a service sit at the path you would guess from the command.

- **One package per case** inside each tier (`unit/azure/`, `smoke/azure/`,
  `e2e/azure/` and the `aws` equivalents). A new provider gets its own package; never
  scatter its tests across existing ones.
- **Every module declares its tier** with `pytestmark = pytest.mark.unit` (or `smoke`,
  `e2e`). Markers are registered in `pyproject.toml` and `--strict-markers` is on, so an
  unmarked module will not be selected by `-m`.
- **One module per service** inside the case package, named `test_<service>.py`:
  `pctl aws ddb ...` is covered by `aws/test_dynamodb.py`, `pctl azure groups ...` by
  `azure/test_groups.py`. Case-level actions with no service get their own module too
  (`azure/test_token.py` for `pctl azure token`). A large service may split by concern
  where it keeps modules readable, as `e2e/azure/` does for `sp` (`test_sp_owners.py`,
  `test_sp_provision.py`), and each case keeps its error paths in `test_failures.py`.
- **Shared components** that sit above any case (`config`, `output`, `errors`, `lazy`,
  `options`, `tokencache`) get a flat `test_<module>.py` in `unit/`, matching the flat
  modules at the root of `src/pctl`.
- **Cross-case behaviour** belongs in `smoke/test_cli_surface.py` — aliases, prefix
  matching, global flags — not duplicated into each case. Its `COMMAND_PATHS` list is
  written out by hand, so a PR that adds a command adds its line there.
- **`conftest.py` at each level plays the role `common.py` plays in the package:** it
  holds exactly the fixtures its children share. Fixtures shared by every tier go in
  `src/test/conftest.py`, those shared by one tier in that tier's `conftest.py`
  (`e2e/conftest.py` for `no_sleep`), and case-specific ones in the case's `conftest.py`.
  Provider fakes (respx, moto) live only in `e2e/`. Constants and static sample data go
  in `helpers.py`, not a fixture.
- Adding a service means adding one `test_<service>.py` in each of the three tiers it
  applies to, and a case `conftest.py` only if that case does not already have one.

## Layering rules

Each level owns only what its children share:

- **Case packages** (`azure/`, `aws/`) hold client wiring and the case-level group. A
  case may also have a `common.py` for helpers that more than one of its services needs
  (`azure/common.py` resolves users for both `sp` and `users`), for the same reason a
  service keeps its helpers out of `__init__.py`.
- **Service packages** (`groups/`, `dynamodb/`) declare the group plus
  `LAZY_SUBCOMMANDS`, and keep shared options/helpers in **`common.py`** — not in
  `__init__.py`, because a package namespace also receives its submodules as
  attributes (`groups.list`) and would shadow builtins. `__init__.py` re-exports from
  `common.py` and declares `__all__`.
- **Transport modules** (`azure/graph.py`, `aws/dynamodb/client.py`) own HTTP/SDK
  concerns: auth, retries, pagination, parallelism. Actions never talk to providers
  directly.
- **Action modules** expose exactly one object named `command`. The `LAZY_SUBCOMMANDS`
  target must end in `:command`: `surface.py` uses that suffix to tell a leaf from a group
  without importing it, which is what lets `pctl commands` and `pctl tree` stay fast.
- **Shared action bodies** may live in a `runner.py` beside the actions when two or more
  of them differ only in path and wording (`azure/entitlements/runner.py`).

## Adding things

- **New action:** add one module with a `command`, then one line in the service's
  `LAZY_SUBCOMMANDS` mapping `name -> ("pctl.case.service.module:command", short_help)`.
  The short help lives in the table so `--help` renders without importing the module.
  The new action then appears in `pctl commands` and `pctl tree` with no further change.
- **New service:** new subpackage with `__init__.py` (group + `LAZY_SUBCOMMANDS`) and
  `common.py`, registered in the case package's `LAZY_SUBCOMMANDS`.
- **New case:** new package, one entry in `cli.py`'s `LAZY_COMMANDS`, optional alias in
  `ALIASES`.

## Conventions to preserve

- **Lazy everything heavy.** `cli.py` imports only click and the stdlib. Import
  `httpx`, `boto3` and orjson _inside_ the command function body, as `scan.py` does.
  Never add a module-level import of a provider SDK to a path that `--help` touches.
- **Global state on `AppContext`**, carried on `click.Context.obj`. Option callbacks in
  `options.py` write into it; leaf commands read `app.output`, `app.quiet`,
  `app.verbose`, `app.columns`, `app.creds` instead of threading parameters through
  signatures. Derive provider config via `app.azure()` / `app.aws()`.
- **Errors:** raise `ConfigError`, `AuthError`, `NotFoundError` or `UpstreamError` from
  `errors.py` so exit codes stay consistent. Do not `sys.exit` from command code.
- **Output:** write records through `Renderer` (used as a context manager), then report
  totals with `summarise(count, noun, quiet=app.quiet)`. Progress goes through
  `app.log()`, which writes to stderr only when verbose.
- **Docstrings are user-facing help.** Command docstrings become `--help` text; use
  `\b` blocks for examples and keep them accurate.
- **`IGNORE-` prefixed paths are out of bounds**, `IGNORE-helpers/` included. Treat them
  as absent: not read, not searched, not imported from, not used as a pattern to copy.
  See the hard limit in `workflow.md`. They are gitignored via `IGNORE*` and excluded from
  ruff, and are not part of the package.
