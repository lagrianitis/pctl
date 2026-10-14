# Finding a command

Thirty commands across four levels. Three ways to find the one you want, in the order you
should reach for them.

## 1. Completion — set it up once

```bash
pctl completion --shell zsh >> ~/.zshrc     # or --shell bash / fish
```

Then, in a new shell, completion covers command names at every level, their aliases, option
names, and the values of any option with fixed choices such as `--match` or `-o`:

```
pctl azure e<TAB>          -> eam, enterprise-apps
pctl azure eam <TAB>       -> all nine actions
pctl azure eam add-a<TAB> --<TAB>
pctl azure groups get --match <TAB>   -> exact, prefix, search
```

This is the highest-value minute here, and it makes most of the rest of this page
unnecessary.

## 2. `pctl commands` — search the surface

One row per command with its summary. It goes through the same renderer as every other
output, which makes it data rather than a display:

```bash
pctl commands                        # the whole surface
pctl commands | grep -i assign       # find the path from a word you remember
pctl commands | grep '^pctl azure eam'
pctl commands -o ndjson | jq -r .command
pctl commands -o csv > surface.csv
```

Example:

```
$ pctl commands | grep -i assign
pctl azure eam add-assignment       Assign people to an access package, by email.
pctl azure eam list-assignments     List who is assigned to an access package.
pctl azure eam remove-assignment    Remove people's assignment to an access package.
pctl azure sp assignments           List app role assignments for an Enterprise Application.
```

| Flag             | Effect                                                     |
| ---------------- | ---------------------------------------------------------- |
| `--groups`       | Include the group levels, which cannot be run on their own |
| `--no-groups`    | Default: leaves only                                       |
| `-o`, `-c`, `-q` | As everywhere else                                         |

Groups are omitted by default because a listing is for finding something to _run_, and you
cannot run `pctl azure eam`. Pass `--groups` when you want the interior, including the
`aliases` column.

**It needs no credentials and touches no provider.** The summaries come from the command
tables, so nothing heavy is even imported.

## 3. `pctl tree` — see the shape

```bash
pctl tree
pctl tree --depth 2      # just the cases and their services
```

```
pctl
├── aws (ddb)
│   └── ddb (dynamodb)
│       ├── describe
│       ├── get
│       ├── query
│       ├── scan
│       └── tables
├── azure (az, graph)
│   ├── apps (app-registrations, applications)
│   ...
```

Always text: the nesting is the point, and `-o json` of a drawing would mean nothing. Use
`pctl commands` when you want to grep, pipe or filter — a tree line like `├── scan` does not
tell you it lives under `ddb`.

## 4. `--help` — the detail

Neither of the above can tell you what `--match` accepts or what a command actually does.
That is what `--help` is for, at every level:

```bash
pctl --help
pctl azure --help
pctl azure eam --help
pctl azure eam add-assignment --help     # flags, examples, permission, caveats
```

`-h` works everywhere `--help` does. Leaf command help carries the examples and the
gotchas — it is the same prose as these wiki pages, kept next to the code.

## Shortcuts

### Prefixes

Any unambiguous prefix resolves, at every level:

```bash
pctl az gr li            # pctl azure groups list
pctl azure eam list-p    # pctl azure eam list-packages
```

Ambiguous ones fail and tell you the candidates:

```
$ pctl a --help
Error: 'a' is ambiguous: aws, azure
```

### Aliases

The portal and Graph disagree on nearly every name, so both spellings resolve:

| Alias                                       | Real command |
| ------------------------------------------- | ------------ |
| `az`, `graph`                               | `azure`      |
| `ddb`                                       | `aws`        |
| `enterprise-apps`, `service-principals`     | `azure sp`   |
| `app-registrations`, `applications`         | `azure apps` |
| `entitlement-management`, `access-packages` | `azure eam`  |
| `dynamodb`                                  | `aws ddb`    |

Aliases are **exact matches only** — `pctl azure enterprise-apps` works, `pctl azure enter`
does not, because prefix matching runs against the real names. Completion offers the full
alias, which is the practical answer.

> **`ddb` at the root is a trap.** It aliases the _case_, not the service, so `pctl ddb` is
> `pctl aws`. `pctl ddb scan` fails; you want `pctl aws ddb scan`.

`pctl --help` shows aliases attached to the real name — `azure (az, graph)` — rather than as
separate entries, and `pctl commands --groups` puts them in their own column.

## Related

- [Common options](Common-Options) — the flags you will meet everywhere
- [Home](Home) — the full command reference by service
