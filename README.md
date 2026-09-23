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

Graph application permissions needed, all admin-consented:

| permission | needed for |
| --- | --- |
| `EntitlementManagement.Read.All` | the `eam` read actions |
| `EntitlementManagement.ReadWrite.All` | `eam add-assignment`, `remove-assignment` |
| `Group.Read.All` | `groups list`, `get`, `members` |
| `User.Read.All` | `users get`, group members, and owners by name or address |
| `Application.Read.All` **or** `Directory.Read.All` | `apps list`, `get`; `sp list`, `get`, `assignments`, `owners` |
| `Application.ReadWrite.All` **or** `Directory.ReadWrite.All` | `sp add-owner`, `sp remove-owner` only |

Everything except the last two commands is read-only, so grant a write permission only
where owner management is actually needed. `Directory.Read.All` covers all the reads on its
own if your app already has it.

A missing permission surfaces as **exit 5** with `Insufficient privileges to complete the
operation`. Check what the token actually carries rather than what the portal lists, since
a token issued before consent was granted will not have the new role:

```bash
pctl azure token --decode -o json | jq -r '.claims.roles[]'
pctl azure token --clear-cache      # after granting consent, or the old token is reused
```

Without a client secret, pctl falls back to
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

**The thing a command acts on is a named flag, not a positional.** `--app` for an
Enterprise Application, `--access-package` for an access package, `--catalog` for a
catalog. Only the *subjects* of a command stay positional — the people or objects being
looked up or changed:

```bash
pctl azure sp add-owner       --app "$APP" ann@company.com bob@company.com
pctl azure eam add-assignment --access-package "$PKG" ann@company.com
```

Without this, `add-assignment "$PKG" ann@company.com` and
`add-assignment ann@company.com "$PKG"` are both valid syntax and only one is right,
which on a write is a bad way to find out. `groups`, `ddb`, `token` and `raw` keep their
original positionals, since those shipped in v0.1.0.

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

### Users

`get` resolves a person to their directory object from whatever you happen to know:
an email address, a display name, or an object ID. Which form you passed is inferred,
so there is no flag to set.

```bash
pctl azure users get ann@company.com
pctl azure users get "Ann Example" -o json
pctl azure users get e6901838-637f-4bc7-b843-a8a7725a4872
pctl azure users get ann@company.com bob@company.com -o ndjson
pctl azure users get -f people.txt --ignore-missing
```

An address is matched against both `userPrincipalName` and `mail`, since those routinely
differ. An object ID addresses `/users/{id}` directly, with no query. A display name uses
`--match`, and an ambiguous name is **refused** rather than guessed — two people can share
one, and you are about to act on the answer. Several identifiers resolve concurrently, and
one that matches nothing does not block the others.

### Entitlement management

Read-only. Access packages are bundles of resources governed by policies, held in
containers called catalogs. `pctl azure entitlement-management` and
`pctl azure access-packages` both reach `eam`.

```bash
pctl azure eam list-catalogs                      # usually the first call
pctl azure eam list-packages --starts-with "AWS "
pctl azure eam list-packages --contains incident -o json
pctl azure eam get-package --access-package "AWS Platform Access" --with-policies
pctl azure eam get-catalog --catalog d4f2d1b6-0a08-4987-9efd-fd8baae9e842
```

**These collections have a narrower OData surface than the rest of Graph.** `$select`,
`$filter` and `$expand` work; `$search` and `$count` are
[not supported](https://learn.microsoft.com/en-us/graph/api/entitlementmanagement-list-accesspackages).
So there is no `--search` here and no `--count-only`, and the match modes differ:

| option | where it runs |
| --- | --- |
| `--name`, `--starts-with`, `--filter` | server-side `$filter` |
| `--contains`, `--match contains` | **locally**, after fetching the collection |

`--contains` exists because Graph has no substring operator on these collections. Every
page is fetched regardless, so it narrows what is rendered rather than what is
transferred, and `-n/--limit` is applied after the filter so a cap cannot drop real
matches.

`--with-policies` expands `assignmentPolicies`, which is where approval and expiry rules
live.

### Entitlement management

Read-only. Access packages are bundles of resources governed by policies, held in
containers called catalogs. `pctl azure entitlement-management` and
`pctl azure access-packages` both reach `eam`.

```bash
pctl azure eam list-catalogs                          # usually the first call
pctl azure eam get-catalog --catalog "AWS Platform"             # by name or by ID
pctl azure eam list-packages --catalog "AWS Platform" # scope by catalog name
pctl azure eam list-packages --contains incident -o json
pctl azure eam get-package --access-package "AWS Platform Access" --with-policies

# who has this access, and is it live?
pctl azure eam list-assignments --access-package "AWS Platform Access" --state Delivered
```

`list-assignments` answers "who is assigned to this package". `--access-package` takes a
display name and resolves it to the ID the filter needs; `--state` narrows to one of
`Delivering`, `PartiallyDelivered`, `Delivered`, `Expired`, `DeliveryFailed`, capitalised
exactly as Graph expects. Together they produce
`$filter=accessPackage/id eq '…' and state eq 'Delivered'`.

`target` and `accessPackage` are expanded by default, and their names lifted to
`targetDisplayName`, `targetEmail` and `accessPackageName` so a table or CSV can address
them — a column cannot reach `target.displayName`. The nested objects stay intact for
`json` and `ndjson`. `--no-expand` leaves the raw relationship IDs.

```bash
pctl -o ndjson azure eam list-assignments --access-package "$PKG" --state Delivered \
  | jq -r '[.targetDisplayName, .targetEmail] | @tsv'
```

#### Granting and revoking access

```bash
pctl azure eam add-assignment    --access-package "AWS Platform Access" ann@company.com
pctl azure eam add-assignment    --access-package "$PKG" --emails ann@company.com,bob@company.com
pctl azure eam remove-assignment --access-package "$PKG" --emails ann@company.com,bob@company.com
```

Each target is an email address, a display name or a user object ID; an address is matched
against `userPrincipalName` and `mail`. These two commands need
`EntitlementManagement.ReadWrite.All`.

**Assignments are not written directly.** Both commands create an
[accessPackageAssignmentRequest](https://learn.microsoft.com/en-us/graph/api/entitlementmanagement-post-assignmentrequests)
which Graph then processes, so they are **asynchronous**. Without `--wait` the command
returns a `requestId` and the state at submission — which is *not* access yet, and exit 0
does not mean the change is live.

##### Knowing whether it actually applied

`--wait` polls each request until it settles and exits 5 if any did not reach `delivered`:

```bash
pctl azure eam add-assignment    --access-package "$PKG" ann@company.com --wait
pctl azure eam remove-assignment --access-package "$PKG" ann@company.com --wait --wait-timeout 300
```

Or check a request submitted earlier, which is what the `requestId` is for:

```bash
pctl azure eam get-request --request-id 4c2a1f7e-… --wait
```

The raw state is classified into an `outcome`, and the mapping is deliberately cautious:

| outcome | states | exit |
| --- | --- | --- |
| `done` | `delivered` — the only state that means access exists | 0 |
| `failed` | `denied`, `canceled`, `deliveryFailed` | 5 |
| `partial` | `partiallyDelivered` — [reprocess rather than resubmit](https://learn.microsoft.com/en-us/graph/api/accessPackageAssignmentRequest-reprocess) | 5 |
| `pending` | `submitted`, `pendingApproval`, `delivering`, **and anything unrecognised** | 5 on `--wait`, 0 on `get-request` |

An unknown state counts as pending rather than done, so a future state value can never be
mistaken for success. A request can sit in `delivering` indefinitely when provisioning is
stuck, which is why `--wait` is bounded by `--wait-timeout` (120s default) and reports a
still-pending request rather than hanging or claiming success.

`get-request` exits 0 for a pending request, since "not yet" is a legitimate answer to a
status query; `--fail-on-pending` makes it exit 5 instead.

Note that a policy requiring approval means `pendingApproval` is the *expected* resting
state, and no amount of waiting will change it until someone approves. In that case
`--wait` will time out correctly rather than incorrectly.

**`add-assignment` needs a policy**, because an `adminAdd` must say which rules govern the
assignment. If the package has exactly one policy it is used without asking; if it has
several the command refuses and lists them, since picking arbitrarily would grant access
under the wrong approval and expiry rules. `--policy` names one. `remove-assignment` needs
none — an `adminRemove` references the existing assignment instead.

Both are **idempotent**: current assignments are read first, so re-running reports
`already-assigned` or `not-assigned` on exit 0 rather than sending a duplicate request.
An `Expired` assignment does not block a fresh add, because an expired assignment is not
access. Each person gets a result row with a `status` of `requested`, `already-assigned`,
`removal-requested` or `not-assigned`, and one unresolvable address does not stop the rest
— the command exits 4 at the end unless `--ignore-missing`.

`get-catalog` and `get-package` take a display name or an object ID, and `--catalog`
accepts a catalog name and resolves it to the ID the filter needs. That costs one extra
request, which is the point of the option.

**These collections have a narrower OData surface than the rest of Graph.** `$select`,
`$filter` and `$expand` work; `$search` and `$count` are
[not supported](https://learn.microsoft.com/en-us/graph/api/entitlementmanagement-list-accesspackages).
So there is no `--search` and no `--count-only` here, and the match options split by where
they run:

| option | where it runs |
| --- | --- |
| `--name`, `--starts-with`, `--filter`, `--catalog`, `--access-package`, `--state` | server-side `$filter` |
| `--contains`, `--match contains`, `--target` | **locally**, after fetching the collection |

`--contains` exists because Graph has no substring operator on these collections. Every
page is fetched regardless, so it narrows what is rendered rather than what is
transferred, and `-n/--limit` applies after the filter so a cap cannot drop real matches.

**`get-package` and `get-catalog` take patterns, not just exact names.** `--match prefix`
and `--match contains` return *every* match rather than refusing an ambiguous one, because
"show me the AWS packages" is a question with several answers:

```bash
pctl azure eam get-package --access-package AWS --match prefix -o ndjson    # every AWS package
pctl azure eam get-package --access-package incident --match contains        # substring, local
```

One match renders as an object and several as an array, the same shape `groups get` uses,
so `jq` needs no index for the common case. An object ID is not a pattern and always
returns exactly one.

A raw `--filter` takes precedence over `--catalog`, `--name` and `--starts-with`: someone
who wrote OData by hand means it.

`--with-policies` expands `assignmentPolicies`, where approval and expiry rules live.

### App registrations

Read-only. The portal calls these **App registrations**; their tenant-local instances are
**Enterprise applications**, which live under `sp` below. `pctl azure app-registrations`
and `pctl azure applications` both reach `apps`.

```bash
pctl azure apps list --search "incident.io"
pctl azure apps get "Company Incident.io SCIM"
pctl azure apps get 8f468c48-e9ac-4dd7-973d-9704b9cdd56d
pctl azure apps get "Company Incident.io SCIM" --with-sp -o json
```

**An application has two GUIDs and they are not interchangeable.** `appId` is the
Application (client) ID, shared with its service principal. `id` is its own directory
object, and differs from the service principal's `id`. Using one where the other belongs is
the usual cause of a confident "no such object". A bare GUID is tried as an `appId` first,
since that is what the portal shows prominently, then as an object ID.

`--with-sp` follows the `appId` join and attaches the service principal, which is how you
get from a registration to the Enterprise Application it appears as:

```bash
pctl -o json azure apps get "$APP" --with-sp | jq '{appId, id, spId: .servicePrincipalId}'
```

A registration with no service principal is reported on stderr — that means registered here
but not instantiated here, which is a real state and a confusing one. Conversely a
third-party app you use but did not register has a service principal and no local
application, so it appears under `sp list` and not here.

### Service principals (Enterprise Applications)

Graph calls them service principals, the portal calls them Enterprise Applications.
`pctl azure enterprise-apps` and `pctl azure service-principals` both reach `sp`.

```bash
pctl azure sp list --search "incident.io"
pctl azure sp list --app-id 00000003-0000-0000-c000-000000000000
pctl azure sp get "Company Incident.io SCIM"
pctl azure sp get "incident.io" --assignments -o json
```

`assignments` answers "who has access to this app", reading `appRoleAssignedTo`. Each
row gains an `appRoleName`, because `appRoleId` on its own is an opaque GUID. With no
`--principal` every assignment is returned; `--principal` narrows it and
`--principal-match` decides how.

```bash
APP="Company Incident.io SCIM"

pctl azure sp assignments --app "$APP"                                   # everyone
pctl azure sp assignments --app "$APP" --outbound                        # the reverse question
pctl azure sp assignments --app "$APP" --principal "AWS Platform Admins" # exact, the default
pctl azure sp assignments --app "$APP" --principal aws-     --principal-match prefix
pctl azure sp assignments --app "$APP" --principal platform --principal-match contains
```

`exact` is the default because the usual job is an access check, where a coincidental
substring would report access that a specific group may not have. Widen it when
exploring. All three ignore case, and the command exits 4 when nothing matches, so a
check can be scripted on the exit code:

```bash
pctl -q azure sp assignments --app "$APP" --principal "$GROUP" >/dev/null 2>&1
case $? in 0) echo assigned ;; 4) echo "not assigned" ;; *) echo "check failed" ;; esac
```

#### Owners

`owners` lists them; `add-owner` and `remove-owner` change them. These are the only
commands in `pctl` that write anything, and they need `Application.ReadWrite.All` rather
than the read permission everything else uses.

```bash
pctl azure sp owners --app "$APP"

# one owner, or several, positionally or comma-separated
pctl azure sp add-owner    --app "$APP" ann@company.com
pctl azure sp add-owner    --app "$APP" ann@company.com bob@company.com
pctl azure sp add-owner    --app "$APP" --emails ann@company.com,bob@company.com
pctl azure sp remove-owner --app "$APP" --emails ann@company.com,bob@company.com

# a display name, an object ID, or a service principal
pctl azure sp add-owner    --app "$APP" "Ann Example"
pctl azure sp add-owner    --app "$APP" e6901838-637f-4bc7-b843-a8a7725a4872
pctl azure sp add-owner    --app "$APP" platform-automation --owner-type sp
```

Each owner can be an **email address**, a **display name**, or a **directory object ID**,
distinguished without a flag. An address is matched against both `userPrincipalName` and
`mail`, since those routinely differ — a tenant may have `lef@company.onmicrosoft.com` as
the UPN and `lef@company.com` as the mail, and you should be able to use either. A GUID is
used as-is. A display name is resolved against users and then service principals, the only
object types that
[can own a service principal](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-post-owners)
— groups cannot, so they are not searched.

Both writes are **idempotent**: the current owners are read once, and adding an existing
owner or removing an absent one is reported as information rather than an error. Re-running
from a pipeline is safe and will not create a duplicate. Each owner gets its own result row
with a `status` of `added`, `already-owner`, `removed` or `not-an-owner`, so a batch tells
you exactly what happened:

```bash
pctl -o ndjson azure sp add-owner --app "$APP" --emails ann@company.com,bob@company.com \
  | jq -r '[.owner, .status] | @tsv'
```

Resolution is `exact` by default and an ambiguous name is refused rather than guessed,
because a wrong match here grants or revokes real access. An owner that cannot be resolved
does not block the others: the rest are still applied, and the command exits 4 unless
`--ignore-missing` is passed. Use `--owner-type` to disambiguate a name that exists in both
collections.

`remove-owner` warns when the removal leaves fewer than two owners, which is Microsoft's
recommended minimum, but does not refuse.

Two things worth knowing before relying on this. The `--principal` filter runs
client-side, because Graph does not support `$filter` on `principalDisplayName` for this
relation, so every page is fetched regardless and `--principal` narrows what is rendered
rather than what is transferred. And `sp get` and `sp assignments` default to
`--match search` for resolving the *application* name, rather than the `exact` that
`groups` uses, because Enterprise Application names are long and rarely typed exactly.

Note the two are independent: `--match` finds the app, `--principal-match` filters its
assignments.

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

| Format   | Streams | Use for                                   |
| -------- | ------- | ----------------------------------------- |
| `table`  | no      | reading in a terminal (default)           |
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
│   ├── common.py            directory lookups shared by `users` and `sp`
│   ├── graph.py             Graph transport: token, retries, pagination
│   ├── token.py             action (case-level, no service)
│   ├── raw.py               action (case-level, no service)
│   ├── users/             service
│   │   ├── __init__.py      `users` group
│   │   ├── common.py        default columns, match_option
│   │   └── get.py           action
│   ├── entitlements/      service (exposed as `eam`)
│   │   ├── __init__.py      `eam` group
│   │   ├── common.py        match modes, local contains filter, filter builder
│   │   ├── runner.py        list/get bodies shared by both collections
│   │   ├── list_packages.py · get_package.py     actions
│   │   └── list_catalogs.py · get_catalog.py     actions
│   ├── entitlements/      service (exposed as `eam`)
│   │   ├── __init__.py      `eam` group
│   │   ├── common.py        match modes, local contains filter, catalog resolution
│   │   ├── runner.py        list/get bodies shared by both collections
│   │   ├── list_packages.py · get_package.py    actions
│   │   ├── list_catalogs.py · get_catalog.py    actions
│   │   ├── list_assignments.py                  action
│   │   └── add_assignment.py · remove_assignment.py   actions (write)
│   ├── applications/      service (exposed as `apps`)
│   │   ├── __init__.py      `apps` group
│   │   ├── common.py        resolve_application: appId before object ID
│   │   ├── list.py          action
│   │   └── get.py           action
│   ├── groups/            service
│   │   ├── __init__.py      `groups` group + match_option, resolve_one, add_relations
│   │   ├── list.py          action
│   │   ├── get.py           action
│   │   └── members.py       action
│   └── service_principals/ service (exposed as `sp`)
│       ├── __init__.py      `sp` group + match_option, resolve_one, resolve_owner
│       ├── list.py          action
│       ├── get.py           action
│       ├── assignments.py   action
│       ├── owners.py        action
│       ├── add_owner.py     action (write)
│       └── remove_owner.py  action (write)
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
│   │   ├── test_common.py   identifier form detection
│   │   ├── test_graph.py    OData escaping, advanced-query headers
│   │   └── test_service_principals.py  principal filtering, role labelling
│   └── aws/               case
│       ├── conftest.py      client_error fixture (botocore-shaped)
│       └── test_dynamodb.py key typing, request kwargs, error mapping
├── smoke/                 CLI surface only, no provider is reached
│   ├── conftest.py          strips provider credentials from the environment
│   ├── test_cli_surface.py  tree-level: help, version, lazy-import guard
│   ├── azure/             case
│   │   ├── conftest.py      azure() and groups() invoke helpers
│   │   ├── test_groups.py   groups service surface
│   │   ├── test_service_principals.py  sp service surface
│   │   ├── test_users.py    users service surface
│   │   ├── test_applications.py  apps service surface
│   │   ├── test_entitlements.py  eam service surface
│   │   └── test_token.py    token and raw actions
│   └── aws/               case
│       ├── conftest.py      ddb() invoke helper
│       └── test_dynamodb.py ddb service surface
└── e2e/                   the real command path, provider boundary faked
    ├── conftest.py          no_sleep and seen fixtures
    ├── azure/             case
    │   ├── conftest.py      azure_env and the respx router
    │   ├── test_groups.py   pagination, filters, rendering, resolution
    │   ├── test_service_principals.py  assignment direction, role labelling
    │   ├── test_sp_owners.py  the writes: idempotency, $ref bodies
    │   ├── test_users.py    identifier forms, ambiguity refusal
    │   ├── test_applications.py  appId vs object ID, the sp join
    │   ├── test_entitlements.py  the narrower OData surface, local filtering
    │   ├── test_token.py    masking, decoding, the disk cache
    │   ├── test_failures.py retries and the exit code contract
    │   └── test_raw.py      the escape hatch
    └── aws/               case
        ├── conftest.py      moto-backed table fixture
        └── test_dynamodb.py parallel scan, query, get, typing
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

| Code | Meaning                          |
| ---- | -------------------------------- |
| 0    | success                          |
| 1    | generic failure                  |
| 2    | usage or configuration error     |
| 3    | authentication failure           |
| 4    | not found (group, table or item) |
| 5    | upstream error from Graph or AWS |
| 130  | interrupted                      |
| 141  | downstream pipe closed           |

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
uv run pytest                             # every tier
```

### Tests

Three tiers, all collected by pytest, so `uv run pytest` really is the whole suite.

| what    | where                                                | how it runs                                                                            |
| ------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `unit`  | `src/test/unit/`, with `azure/` and `aws/` per case  | pytest, marker `unit`. Pure functions, no I/O, no mocks.                                |
| `smoke` | `src/test/smoke/`, with `azure/` and `aws/` per case | pytest, marker `smoke`. CLI surface: help, aliases, exit codes. No provider is reached. |
| `e2e`   | `src/test/e2e/`, with `azure/` and `aws/` per case   | pytest, marker `e2e`. The real command path, with Graph faked by respx and DynamoDB by moto. |

```bash
uv run pytest -m unit                  # pure functions
uv run pytest -m smoke                 # CLI surface
uv run pytest -m e2e                   # the real command path
uv run pytest src/test/e2e/azure       # one case in one tier
uv run pytest -k tokencache            # one area
uv run pytest -n auto                  # across CPUs; pays off as the suite grows
```

Nothing here needs credentials, a tenant or an AWS account. The `unit` and `smoke` tiers
never reach a provider at all, and `e2e` fakes the HTTP and SDK boundary.

Two conventions worth knowing before adding a test. Read data from `result.stdout` rather
than `result.output`, because click 8.2+ merges stderr into `output` and this CLI writes
summaries to stderr. And decode request URLs with `unquote_plus` before matching, because
httpx percent-encodes OData names like `%24filter` and encodes spaces as `+`.

### Dependencies

| where                                   | what                                              | reaches an app install? |
| --------------------------------------- | ------------------------------------------------- | ----------------------- |
| `[project] dependencies`                | click, httpx, orjson, boto3                       | yes                     |
| `[project.optional-dependencies] fast`  | uvloop, h2                                        | only with `pctl[fast]`  |
| `[project.optional-dependencies] azure` | azure-identity                                    | only with `pctl[azure]` |
| `[dependency-groups] test`              | pytest, pytest-xdist, pytest-asyncio, respx, moto | no                      |
| `[dependency-groups] dev`               | the `test` group plus ruff                        | no                      |

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
