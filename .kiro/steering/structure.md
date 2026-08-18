# Project structure

The tree mirrors the command line: **case → service → action**. `pctl aws ddb scan`
lives in `aws/dynamodb/scan.py`; `pctl azure groups get` in `azure/groups/get.py`.

```
src/pctl/
├── __main__.py            entry point (`pctl = "pctl.__main__:main"`)
├── cli.py                 root group, global flags, LAZY_COMMANDS case table
├── lazy.py                PctlGroup: lazy imports, aliases, prefix matching
├── config.py              AppContext, AzureConfig, AwsConfig, OutputFormat
├── options.py             shared click options (output, azure, aws, columns)
├── output.py              Renderer: table / json / ndjson / csv
├── errors.py              PctlError subclasses mapped to exit codes
├── tokencache.py          on-disk token cache (0600 in a 0700 dir)
├── secrets.py             Azure credentials from AWS Secrets Manager
├── azure/                 case
│   ├── __init__.py          `azure` group + graph_client() shared by its actions
│   ├── graph.py             Graph transport: token, retries, pagination
│   ├── token.py             case-level action (no service)
│   ├── raw.py               case-level action (no service)
│   └── groups/            service
│       ├── __init__.py      `groups` group + LAZY_SUBCOMMANDS, re-exports
│       ├── common.py        shared options/helpers (match_option, resolve_one, ...)
│       ├── list.py          action
│       ├── get.py           action
│       └── members.py       action
└── aws/                   case
    ├── __init__.py          `aws` group
    └── dynamodb/          service (exposed as `ddb`)
        ├── __init__.py      `ddb` group + LAZY_SUBCOMMANDS, re-exports
        ├── common.py        shared options/helpers (read_options, parse_json_option)
        ├── client.py        DynamoDB transport: parallel scan, query, get
        ├── tables.py · describe.py · scan.py · query.py · get.py    actions

src/test/
├── conftest.py            fixtures shared by every tier, plus `live` tier gating
├── helpers.py             constants and static sample data (TENANT, TABLE, FAKE_JWT)
├── unit/                  one module per shared component, then one package per case
│   ├── test_config.py · test_errors.py · test_lazy.py
│   ├── test_options.py · test_output.py · test_tokencache.py
│   ├── azure/           case
│   │   ├── conftest.py      fixtures shared by this case's tests
│   │   └── test_graph.py    one module per service or transport
│   └── aws/             case
│       ├── conftest.py
│       └── test_dynamodb.py
└── smoke/                 end-to-end through CliRunner, provider boundary faked
    ├── conftest.py          fixtures shared by every smoke test
    ├── test_cli_surface.py  cross-case surface: aliases, prefixes, global flags
    ├── azure/           case
    │   ├── conftest.py
    │   ├── test_token.py    one module per service or case-level action
    │   └── test_groups.py
    ├── aws/             case
    │   ├── conftest.py
    │   └── test_dynamodb.py
    ├── harness.py           legacy standalone runner: check counting, env scoping
    ├── azure_graph.py       legacy standalone script, run directly
    ├── aws_dynamodb.py      legacy standalone script, run directly
    └── run_all.py           runs the standalone scripts, combines exit codes
```

## Tests mirror the package

The test tree follows the same **case → service** namespacing as `src/pctl`, so the
tests for a service sit at the path you would guess from the command.

- **One package per case** inside each tier (`unit/azure/`, `unit/aws/`,
  `smoke/azure/`, `smoke/aws/`). A new provider gets its own package; never scatter its
  tests across existing ones.
- **One module per service** inside the case package, named `test_<service>.py`:
  `pctl aws ddb ...` is covered by `aws/test_dynamodb.py`, `pctl azure groups ...` by
  `azure/test_groups.py`. Case-level actions with no service get their own module too
  (`azure/test_token.py` for `pctl azure token`).
- **Shared components** that sit above any case (`config`, `output`, `errors`, `lazy`,
  `options`, `tokencache`) get a flat `test_<module>.py` in `unit/`, matching the flat
  modules at the root of `src/pctl`.
- **Cross-case behaviour** belongs in `smoke/test_cli_surface.py` — aliases, prefix
  matching, global flags — not duplicated into each case.
- **`conftest.py` at each level plays the role `common.py` plays in the package:** it
  holds exactly the fixtures its children share. Tier-wide fixtures go in
  `src/test/conftest.py`, case-specific ones in that case's `conftest.py`. Constants and
  static sample data go in `helpers.py`, not a fixture.
- Adding a service means adding one `test_<service>.py` in each relevant tier, and a
  case `conftest.py` only if that case does not already have one.

## Layering rules

Each level owns only what its children share:

- **Case packages** (`azure/`, `aws/`) hold client wiring and the case-level group.
- **Service packages** (`groups/`, `dynamodb/`) declare the group plus
  `LAZY_SUBCOMMANDS`, and keep shared options/helpers in **`common.py`** — not in
  `__init__.py`, because a package namespace also receives its submodules as
  attributes (`groups.list`) and would shadow builtins. `__init__.py` re-exports from
  `common.py` and declares `__all__`.
- **Transport modules** (`azure/graph.py`, `aws/dynamodb/client.py`) own HTTP/SDK
  concerns: auth, retries, pagination, parallelism. Actions never talk to providers
  directly.
- **Action modules** expose exactly one object named `command`.

## Adding things

- **New action:** add one module with a `command`, then one line in the service's
  `LAZY_SUBCOMMANDS` mapping `name -> ("pctl.case.service.module:command", short_help)`.
  The short help lives in the table so `--help` renders without importing the module.
- **New service:** new subpackage with `__init__.py` (group + `LAZY_SUBCOMMANDS`) and
  `common.py`, registered in the case package's `LAZY_SUBCOMMANDS`.
- **New case:** new package, one entry in `cli.py`'s `LAZY_COMMANDS`, optional alias in
  `ALIASES`.

## Conventions to preserve

- **Lazy everything heavy.** `cli.py` imports only click and the stdlib. Import
  `httpx`, `boto3` and orjson *inside* the command function body, as `scan.py` does.
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
