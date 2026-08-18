# Smoke tests

**Is the build alive?** Help renders, the command table loads, the version reports, bad
input is rejected with the documented exit code. That is the whole remit.

No provider is faked here, because none is reached. A test in this tier that needs a
token or an AWS call belongs in `../e2e/` instead.

```
smoke/
├── conftest.py            strips provider credentials for every test in the tier
├── test_cli_surface.py    tree-level: all help screens, version, lazy-import guard
├── azure/
│   ├── conftest.py        azure() and groups() invoke helpers
│   ├── test_groups.py     pctl azure groups ...
│   └── test_token.py      pctl azure token / raw
└── aws/
    ├── conftest.py        ddb() invoke helper
    └── test_dynamodb.py   pctl aws ddb ...
```

Run it with `uv run pytest -m smoke`. It must stay under a second: this is the tier you
run while editing.

## The one test that matters most

`test_help_does_not_import_a_provider_sdk` in `test_cli_surface.py`. It asserts that no
help path pulls `boto3`, `botocore`, `httpx`, `uvloop` or `h2` into the interpreter.

Lazy imports are what keep `pctl --help` in the low tens of milliseconds, and a single
module-level `import boto3` anywhere on the help path costs half a second while breaking
nothing. The property is invisible in normal use, so it is asserted in a **subprocess** —
this test process has already imported those modules for the `e2e` tier, which would mask
the regression entirely.

`aws ddb scan` is in `LAZY_PATHS` deliberately: it imports the transport module at module
scope to read `MAX_SEGMENTS`, so the transport itself has to keep `boto3` inside function
bodies.

`COMMAND_PATHS` is written out rather than discovered from the command tree. A command
disappearing should fail a test, not silently shrink the run.

## Two mistakes that cost time

**Read `result.stdout`, not `result.output`.** click 8.2+ merges stderr into `output`, and
this CLI writes summaries and diagnostics to stderr on purpose. Asserting on `output`
means a summary line can satisfy an assertion about data.

**Decode request URLs before matching.** httpx percent-encodes OData parameter names, so
`$filter` arrives as `%24filter`, and spaces in the expression become `+`. Use
`unquote_plus` first. This applies in `../e2e/`, where requests are actually made.

## Where the other tiers sit

| tier | what it proves | provider |
| --- | --- | --- |
| `../unit/` | pure functions in isolation | none, no I/O |
| `smoke/` | the CLI surface is intact | none reached |
| `../e2e/` | the real command path, argv to the wire | Graph via respx, DynamoDB via moto |

Nothing in any tier needs credentials, a tenant or an AWS account.
