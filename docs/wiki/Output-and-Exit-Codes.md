# Output and exit codes

## The stdout/stderr split

**Data goes to stdout. Everything else goes to stderr.** Summaries, warnings, progress and
prompts are all diagnostics, so a pipe is always clean:

```bash
pctl azure groups list -o ndjson | jq -r .displayName    # only data reaches jq
```

This is why `2 groups` at the end of a run does not corrupt your JSON, and why
`-q/--quiet` is rarely needed for scripting — it suppresses the summary line, but the
summary was never in your data anyway.

## Formats

| Format   | Streams | Use for                                           |
| -------- | ------- | ------------------------------------------------- |
| `table`  | no      | reading in a terminal — the default               |
| `json`   | yes     | one document, pretty-printed when stdout is a tty |
| `ndjson` | yes     | large result sets, and piping to `jq`             |
| `csv`    | yes     | spreadsheets, diffs, review artefacts             |

```bash
pctl -o ndjson azure groups list > groups.ndjson
pctl azure groups list -o csv -c displayName,mail
```

The three streaming formats keep memory flat regardless of result size: records are written
as they arrive rather than collected. `table` cannot stream, because column widths are not
known until the last row.

### Where the flag goes

Global options work **before the case** or **on the leaf command**, but not in between:

```bash
pctl -o json azure groups list      # works
pctl azure groups list -o json      # works
pctl azure -o json groups list      # usage error
```

The intermediate group levels do not declare them. If you get
`No such option: -o`, that is why.

### One result or many

Commands that fetch by name return **an object when there is exactly one match and an array
when there are several**, so `jq` needs no index in the common case:

```bash
pctl -o json azure groups get --name "Team A" | jq -r .id          # one match
pctl -o json azure eam get-package --access-package AWS --match prefix | jq -r '.[].id'
```

`list` commands always return an array, even with one row.

### Columns

`-c/--columns` restricts `table` and `csv` output. It does not affect `json` or `ndjson`,
which always carry the full record — use `--select` to narrow what is _fetched_, and `jq` to
narrow what is shown.

```bash
pctl azure groups list -c displayName,mail        # two columns
pctl azure groups list --select id,displayName    # fewer bytes over the wire
```

Nested values in `table` and `csv` are JSON-encoded so the cell stays machine-readable, and
empty values render as `-`.

## Exit codes

| Code | Meaning                | Typical cause                                                             |
| ---- | ---------------------- | ------------------------------------------------------------------------- |
| 0    | Success                |                                                                           |
| 1    | Generic failure        | An unexpected error, or a declined confirmation prompt                    |
| 2    | Usage or configuration | Bad flag, missing required option, ambiguous name, missing tenant         |
| 3    | Authentication         | The credential itself could not be used                                   |
| 4    | Not found              | A name or ID matched nothing                                              |
| 5    | Upstream               | The provider refused or failed: 403, 400, 5xx, a write that did not apply |
| 130  | Interrupted            | Ctrl-C                                                                    |
| 141  | Broken pipe            | The reader closed first, e.g. `\| head`                                   |

They are a published contract, which makes them the cheapest thing to script against.

### The distinctions that matter

**2 vs 4 — ambiguity vs absence.** A name that matches nothing exits 4. A name that matches
_several_ things where exactly one is required exits 2, because it is your input that needs
fixing, not the directory:

```bash
pctl azure users get --user "Example" --match prefix   # 2 users match -> exit 2
pctl azure users get --user nobody@example.com         # matched nothing -> exit 4
```

`--ignore-missing` downgrades 4 to 0 where it is offered. It deliberately does **not**
downgrade 2: skipping a name that matched two people would silently drop one of them.

**3 vs 5 — authentication vs authorisation.** Exit 3 means the credential is bad. Exit 5
with `Authorization_RequestDenied` means the credential is fine and the permission is
missing. See [Permissions](Permissions#401-vs-403).

**5 for a write that did not apply.** `sp provision` and the `eam` assignment writes with
`--wait` exit 5 when the change was accepted but did not take effect. A 200 from the provider
is not success — see
[Entitlement management](Azure-Entitlement-Management#knowing-whether-it-applied) and
[Service principals](Azure-Service-Principals#provision).

### Scripting against them

```bash
if pctl azure sp assignments --app "$APP" --principal "$GROUP" -q > /dev/null; then
  echo "assigned"
else
  case $? in
    4) echo "not assigned" ;;
    5) echo "graph refused - check permissions" ;;
    *) echo "something else went wrong" ;;
  esac
fi
```

An access check is exit-code-only on purpose: exit 0 when the principal is assigned, exit 4
when it is not.

## Broken pipes

`| head`, `| grep -q` and friends close the pipe early. `pctl` exits **141** rather than
dumping a traceback:

```bash
pctl azure groups list -o ndjson | head -5     # clean exit
```

## Related

- [Common options](Common-Options) — `--select`, `--limit`, `--match` and the rest
- [Troubleshooting](Troubleshooting)
