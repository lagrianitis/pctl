# pctl

One fast CLI for the platform's providers. Today it covers two:

- **Microsoft Graph** (`pctl azure`) - get a token, list every Entra ID group across
  paginated results, and pull details for a single group or a user-defined list of
  groups by display name.
- **AWS DynamoDB** (`pctl aws`) - read items from a table via scan, query or get-item.

The command line is **case → service → action** (`pctl aws ddb scan`), and the source
tree mirrors it, so adding a provider such as Confluent means adding a case package
rather than reshaping anything that already works.

Built on [Click](https://click.palletsprojects.com/) with Python 3.14.

## Install

```bash
uv sync --extra fast          # dev install with the optional speed-ups
uv run pctl --help
```

Or as a tool:

```bash
uv tool install --editable '.[fast]'
pctl --help
```

The `fast` extra adds `uvloop` (faster event loop) and `h2` (HTTP/2 to Graph).
Both are optional and detected at runtime.

## Configure

Copy `.env.example` and fill in your Entra ID app registration:

```bash
export AZURE_TENANT_ID=...
export AZURE_CLIENT_ID=...
export AZURE_CLIENT_SECRET=...      # prefer injecting this from a secret manager
```

Graph application permissions needed: `Group.Read.All`, plus `User.Read.All` if
you resolve members. Without a client secret, pctl falls back to
`azure-identity`'s `DefaultAzureCredential` when installed (`--extra azure`),
which picks up `az login`, managed identity and workload identity.

AWS uses the standard SDK chain, so `AWS_PROFILE`, SSO, assumed roles and
instance credentials all behave as they do with the AWS CLI.

## Usage

```
pctl [global options] <azure|aws> ...
```

Global options work before or after the subcommand: `-o/--output`, `-q/--quiet`,
`-v/--verbose`, `--timeout`, `--concurrency`. Command names accept unambiguous
prefixes and aliases, so `pctl az gr li` is `pctl azure groups list`.

### Tokens

```bash
pctl azure token                    # masked token plus expiry
pctl azure token --decode           # inspect the JWT claims (no signature check)
curl -H "Authorization: Bearer $(pctl azure token --raw)" \
     https://graph.microsoft.com/v1.0/me
pctl azure token --clear-cache      # drop cached tokens
```

### Groups

```bash
# 1. every group in the tenant, following @odata.nextLink
pctl azure groups list
pctl azure groups list -o ndjson > groups.ndjson
pctl azure groups list --starts-with "aws-" --limit 50
pctl azure groups list --count-only

# 2. details for one group, or a list you define, by display name
pctl azure groups get "AWS Platform Admins"
pctl azure groups get "Team A" "Team B" --members --owners -o json
pctl azure groups get -f my-groups.txt --counts -o csv
pctl azure groups get "platform" --match search      # substring match
pctl azure groups members "AWS Platform Admins" --transitive
```

`--from-file` reads one display name per line and ignores blanks and `#`
comments, so a curated list can live in version control. Every name is resolved
concurrently.

Match modes: `exact` (default, `displayName eq`), `prefix` (`startswith`),
`search` (Graph full-text, matches substrings).

### Escape hatch

```bash
pctl azure raw users --param '$select=id,displayName' -n 10
```

Any Graph path, with auth, retries and pagination handled.

### DynamoDB

```bash
pctl aws ddb tables
pctl aws ddb describe my-table
pctl aws ddb scan my-table -n 20
pctl aws ddb scan my-table --segments 8 -o ndjson > items.ndjson
pctl aws ddb scan my-table --filter "#s = :s" \
    --names '{"#s":"status"}' --values '{":s":"ACTIVE"}'
pctl aws ddb query my-table --key "pk = :pk" --values '{":pk":"tenant#42"}'
pctl aws ddb get my-table '{"pk":"tenant#42","sk":"profile"}'
pctl aws ddb scan my-table --endpoint-url http://localhost:8000   # local DynamoDB
```

Expression values are plain JSON; pctl converts them to DynamoDB's typed format.
DynamoDB-typed JSON is also accepted as-is.

## Output

| Format   | Streams | Use for                                  |
| -------- | ------- | ---------------------------------------- |
| `table`  | no      | reading in a terminal (default)          |
| `json`   | yes     | one document, pretty when stdout is a tty |
| `ndjson` | yes     | large result sets, piping to `jq`         |
| `csv`    | yes     | spreadsheets                              |

Data goes to stdout, diagnostics and summaries to stderr, so pipes stay clean:

```bash
pctl azure groups list -o ndjson | jq -r '.displayName' | sort
pctl aws ddb scan my-table -o ndjson | head -5     # exits cleanly on SIGPIPE
```

Restrict columns with `-c/--columns`:

```bash
pctl azure groups list -c displayName,mail
```

## Layout

The tree mirrors the command line: **case → service → action**. `pctl aws ddb scan`
lives in `aws/dynamodb/scan.py`, `pctl azure groups get` in `azure/groups/get.py`.

```
src/pctl/
├── cli.py                 root group, global flags, case table
├── lazy.py                PctlGroup: lazy imports, aliases, prefix matching
├── config.py              AppContext + credential/session resolution
├── options.py             shared click options (output, azure, aws)
├── output.py              Renderer: table / json / ndjson / csv
├── errors.py              error types mapped to exit codes
├── tokencache.py          on-disk token cache
├── secrets.py             Azure credentials from AWS Secrets Manager
├── azure/                 case
│   ├── __init__.py          `azure` group + graph_client() shared by all actions
│   ├── graph.py             Graph transport: token, retries, pagination
│   ├── token.py             action (case-level, no service)
│   ├── raw.py               action (case-level, no service)
│   └── groups/            service
│       ├── __init__.py      `groups` group + match_option, resolve_one, add_relations
│       ├── list.py          action
│       ├── get.py           action
│       └── members.py       action
└── aws/                   case
    ├── __init__.py          `aws` group
    └── dynamodb/          service (exposed as `ddb`)
        ├── __init__.py      `ddb` group + read_options, parse_json_option
        ├── client.py        DynamoDB transport: parallel scan, query, get
        ├── tables.py        action
        ├── describe.py      action
        ├── scan.py          action
        ├── query.py         action
        └── get.py           action
```

Each level owns what its children share: case packages hold client wiring, service
packages hold the options and helpers their actions reuse, and every action module
exposes a single `command`. Adding an action means adding one file and one line to
the service's `LAZY_SUBCOMMANDS`.

The test tree mirrors the same shape, so the tests for a service sit at the path you
would guess from the command. Each level's `conftest.py` holds the fixtures its
children share, exactly as `common.py` does in the package.

```
src/test/
├── conftest.py            runner and cli fixtures, shared by every tier
├── helpers.py             ok() / failed() / help_for(), used by both tiers
├── unit/                  pure functions, no I/O and no mocks
│   ├── test_output.py       Renderer: table / json / ndjson / csv
│   ├── test_config.py       credential precedence and defaults
│   ├── test_options.py      shared click option helpers
│   ├── test_errors.py       exit code contract
│   ├── test_lazy.py         aliases, prefixes, lazy resolution
│   ├── test_tokencache.py   expiry, permissions, corrupt files
│   ├── azure/             case
│   │   ├── conftest.py      graph_client fixture
│   │   └── test_graph.py    OData escaping, advanced-query headers
│   └── aws/               case
│       ├── conftest.py      client_error fixture (botocore-shaped)
│       └── test_dynamodb.py key typing, request kwargs, error mapping
└── smoke/                 CLI surface only, no provider is reached
    ├── conftest.py          strips provider credentials from the environment
    ├── test_cli_surface.py  tree-level: help, version, lazy-import guard
    ├── azure/             case
    │   ├── conftest.py      azure() and groups() invoke helpers
    │   ├── test_groups.py   groups service surface
    │   └── test_token.py    token and raw actions
    ├── aws/               case
    │   ├── conftest.py      ddb() invoke helper
    │   └── test_dynamodb.py ddb service surface
    ├── harness.py         ─┐
    ├── azure_graph.py      │ standalone end-to-end scripts, not pytest-collected
    ├── aws_dynamodb.py     │ (Graph faked with respx, DynamoDB with moto)
    └── run_all.py         ─┘
```

## What makes it fast

- **Lazy imports.** `boto3` costs several hundred milliseconds to import, so
  command modules load only when their subcommand runs. `pctl --help` imports
  click and nothing else.
- **Token caching.** Client-credentials tokens are cached on disk, so repeated
  calls skip a 150-400ms round trip to Entra ID.
- **Page prefetching.** Graph's `@odata.nextLink` is sequential, so page N+1 is
  requested while page N is still being written. That hides a full round trip per
  page.
- **Narrow payloads.** `$top=999` and `$select` cut both the number of pages and
  the bytes per page. DynamoDB gets the same treatment via `--projection`.
- **Concurrency where it helps.** Group lookups and their member/owner fetches run
  concurrently on one keep-alive connection pool; DynamoDB scans split across
  parallel segments.
- **Streaming output.** orjson writes bytes straight to stdout, so memory stays
  flat regardless of result size.

## Exit codes

| Code | Meaning                              |
| ---- | ------------------------------------ |
| 0    | success                              |
| 1    | generic failure                      |
| 2    | usage or configuration error         |
| 3    | authentication failure               |
| 4    | not found (group, table or item)     |
| 5    | upstream error from Graph or AWS     |
| 130  | interrupted                          |
| 141  | downstream pipe closed               |

## Security notes

- Access tokens are cached under `${XDG_CACHE_HOME:-~/.cache}/pctl/tokens` with
  `0600` permissions inside a `0700` directory. Disable with `--no-token-cache` or
  `PCTL_NO_TOKEN_CACHE=1`.
- `pctl azure token --raw` prints a bearer token to stdout. Treat it as a secret
  and avoid it in shell history or CI logs.
- Client secrets are read from the environment only, never from a CLI flag, so
  they do not land in `ps` output or shell history.
- `--decode` shows JWT claims without verifying the signature. It is for
  inspection, not for authorization decisions.

## Development

```bash
uv sync --extra fast --extra azure        # includes the dev dependency group
uv run ruff check .
uv run pytest                             # unit + smoke tiers
uv run python src/test/smoke/run_all.py   # end-to-end scripts
```

### Tests

| what | where | how it runs |
| --- | --- | --- |
| `unit` | `src/test/unit/`, with `azure/` and `aws/` per case | pytest, marker `unit`. Pure functions, no I/O, no mocks. |
| `smoke` | `src/test/smoke/`, with `azure/` and `aws/` per case | pytest, marker `smoke`. CLI surface: help, aliases, exit codes. |
| end-to-end | `src/test/smoke/{run_all,azure_graph,aws_dynamodb}.py` | standalone scripts, not pytest-collected. Graph faked with respx, DynamoDB with moto. |

```bash
uv run pytest -m unit                  # 185 tests, ~0.3s
uv run pytest -m smoke                 # 88 tests, ~0.5s
uv run pytest src/test/unit/aws        # one case
uv run pytest -k tokencache            # one area
uv run pytest -n auto                  # across CPUs; pays off as the suite grows
```

Nothing here needs credentials, a tenant or an AWS account. The pytest tiers never
reach a provider, and the end-to-end scripts fake the HTTP and SDK boundary. See
`src/test/smoke/README.md` for the conventions, including the two easy mistakes:
read `result.stdout` rather than `result.output`, and decode request URLs before
matching them.

### Dependencies

| where | what | reaches an app install? |
| --- | --- | --- |
| `[project] dependencies` | click, httpx, orjson, boto3 | yes |
| `[project.optional-dependencies] fast` | uvloop, h2 | only with `pctl[fast]` |
| `[project.optional-dependencies] azure` | azure-identity | only with `pctl[azure]` |
| `[dependency-groups] test` | pytest, pytest-xdist, pytest-asyncio, respx, moto | no |
| `[dependency-groups] dev` | the `test` group plus ruff | no |

Test tooling lives in PEP 735 dependency groups rather than extras, so it is
installed by `uv sync` but never written into the wheel metadata. Anyone
installing pctl as an app gets four runtime dependencies and nothing else. To
confirm, or to build a production image:

```bash
uv sync --no-dev        # app-only environment, no pytest/moto/respx/ruff
```

There is no `requirements.txt` on purpose: `pyproject.toml` plus `uv.lock` is the
single source of truth. If you ever need a pinned flat file for a pip-only
environment, generate it rather than hand-maintaining it:

```bash
uv export --no-dev --format requirements-txt > requirements.txt
```
