# `pctl azure apps`

Application registrations — what the Entra ID portal calls **App registrations**. Read-only,
except `add-client-secret` and `remove-client-secret`, which create and remove a client
secret.

**Permission:** `Application.Read.All` or `Directory.Read.All` for `list`, `get` and
`get-client-secrets`, which reads the credential metadata off the application object.
`add-client-secret` and `remove-client-secret` write, and need `Application.ReadWrite.All` or
`Directory.ReadWrite.All`. See [Permissions](Permissions).

**Aliases:** `pctl azure app-registrations`, `pctl azure applications`.

> **`apps` is not `sp`.** An app registration is the _definition_; a
> [service principal](Azure-Service-Principals) is its instance in a tenant, which the portal
> calls an Enterprise application. One registration can have a service principal in many
> tenants. If you are looking for who has access to something, you want `sp`.

---

## The two GUIDs

This is the thing to understand before using either command, and the usual source of
"no such object" errors:

| Field   | Portal label                  | Shared with the service principal? |
| ------- | ----------------------------- | ---------------------------------- |
| `appId` | Application (client) ID       | **Yes** — it is the join key       |
| `id`    | Object ID of the registration | No — the SP has its own `id`       |

So an application and its service principal share an `appId` and have _different_ `id`s.
Passing one where the other is expected returns nothing, with no hint as to why.

---

## `list`

| Flag                   | Default | Effect                                                |
| ---------------------- | ------- | ----------------------------------------------------- |
| `--select FIELDS`      |         | Comma-separated Graph fields                          |
| `--filter ODATA`       |         | Raw OData `$filter`                                   |
| `--search TEXT`        |         | Full-text search on `displayName`, matches substrings |
| `--starts-with PREFIX` |         | Shortcut for `startswith(displayName)`                |
| `--order-by FIELD`     |         | Server-side ordering                                  |
| `-n, --limit N`        |         | Stop after N registrations                            |
| `--page-size N`        | 999     | Graph `$top` page size                                |
| `--count-only`         |         | Print just the total                                  |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure apps list --search "incident.io"
pctl azure apps list --starts-with "Company " -o ndjson
pctl azure apps list --count-only
```

Default columns lead with `appId`, because that is the field you pivot on.

---

## `get`

| Flag                   | Default | Effect                                                     |
| ---------------------- | ------- | ---------------------------------------------------------- |
| `--app VALUE`          |         | Display name, `appId` or object ID. **Repeat for several** |
| `-f, --from-file PATH` |         | One identifier per line, `-` for stdin                     |
| `--match MODE`         | `exact` | How to match a display name                                |
| `--with-sp`            |         | Also fetch the service principal for the same `appId`      |
| `--select FIELDS`      |         | Comma-separated Graph fields                               |
| `--ignore-missing`     |         | Exit 0 when an identifier matches nothing                  |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure apps get --app "Company Incident.io SCIM"
pctl azure apps get --app 8f468c48-e9ac-4dd7-973d-9704b9cdd56d
pctl azure apps get --app "Company Incident.io SCIM" --with-sp -o json
pctl azure apps get --app incident --match search
pctl azure apps get -f apps.txt --ignore-missing
```

### How a bare GUID is resolved

Tried as an **`appId` first**, because that is the one the portal shows prominently and
therefore the one you are most likely holding. If nothing matches, it is retried as an object
ID against `/applications/{id}`. Both attempts are cheap and the order is not configurable.

### An ambiguous name is refused

```
$ pctl azure apps get --app "Company" --match prefix
Error: 2 application registrations match 'Company'. Pass the appId instead, so the wrong one
cannot be chosen.
```

Exit 2 — see [Output and exit codes](Output-and-Exit-Codes#the-distinctions-that-matter).

### `--with-sp`: crossing to the Enterprise application

Adds the service principal under `servicePrincipal`, and its object ID as
`servicePrincipalId`. The lookup is **by `appId`**, never by object ID, because the two
differ:

```bash
pctl -o json azure apps get --app "$APP" --with-sp \
  | jq '{appId, registrationId: .id, spId: .servicePrincipalId}'
```

```json
{
  "appId": "8f468c48-e9ac-4dd7-973d-9704b9cdd56d",
  "registrationId": "aaaaaaaa-1111-2222-3333-444444444444",
  "spId": "240c4d97-0d28-41f9-9047-2d028e6645e5"
}
```

Three different GUIDs for one logical application. This is why `--with-sp` exists.

### Registered but not instantiated

An application can exist as a registration with **no service principal in this tenant** — a
real and confusing state, usually a multi-tenant app nobody has consented to here. `--with-sp`
reports it on stderr rather than silently returning null:

```
Company Registered Only has no service principal in this tenant, so it is registered but not
instantiated here.
```

`servicePrincipalId` is `null` in the record, and the command still exits 0.

---

## `get-client-secrets`

The client secrets and certificates of one app registration, and when each runs out.

| Flag                  | Default | Effect                                                                |
| --------------------- | ------- | --------------------------------------------------------------------- |
| `--app-name NAME`     |         | Display name of the app. Give this **or** `--app-id`                  |
| `--app-id APPID`      |         | `appId` of the app. Skips the display name search                     |
| `--match`             | `exact` | How to match a display name: `exact`, `prefix` or `search`            |
| `--expiring-within N` | `30`    | Days before the end date that count as expiring                       |
| `--fail-on-expiry`    |         | List everything, then exit **6** if any credential lapsed or is close |
| `-c, --columns`       |         | Columns for `table` and `csv`                                         |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure apps get-client-secrets --app-name "Company Incident.io SCIM"
pctl azure apps get-client-secrets --app-id 8f468c48-e9ac-4dd7-973d-9704b9cdd56d -o json
pctl azure apps get-client-secrets --app-name "$APP" --expiring-within 60 --fail-on-expiry
```

### Naming the app

`get-client-secrets`, `add-client-secret` and `remove-client-secret` all name the app with
one of two flags, and exactly one must be given:

- `--app-id` takes the `appId` (Application (client) ID). It skips the display name search,
  so it is the exact way to name an app. It must be a GUID, and an object ID is not accepted.
- `--app-name` takes the display name, matched as `--match` says. An ambiguous name is
  refused with exit 2, as [`get` does](#an-ambiguous-name-is-refused), and the message
  suggests `--app-id`.

Giving both, or neither, exits 2 before anything is sent. An unknown name or `appId` exits 4.

### The columns

| Column          | Meaning                                                                    |
| --------------- | -------------------------------------------------------------------------- |
| `type`          | `secret` or `certificate`                                                  |
| `name`          | The description given when it was created                                  |
| `status`        | `expired`, `expiring` or `valid`; `unknown` if Graph sent no end date      |
| `daysRemaining` | Whole days left, rounded down; negative once lapsed; `0` means under a day |
| `endDateTime`   | When it stops working, in UTC as Graph reports it                          |
| `keyId`         | Identifies the credential: the `--key-id` of `remove-client-secret`        |

`-o json` also carries `app`, `appId`, `startDateTime` and `hint`. Rows are listed soonest to
end first, secrets and certificates together.

### Status

| Status     | When                                                           |
| ---------- | -------------------------------------------------------------- |
| `expired`  | The end date is now or in the past                             |
| `expiring` | It ends within `--expiring-within` days, the boundary included |
| `valid`    | It ends later than that                                        |

`daysRemaining` is rounded down so a credential never looks as if it has longer than it does.

### Using it as a check

`--fail-on-expiry` makes the command usable in a pipeline. It still prints every credential,
so the failure arrives with its detail, then exits **6**:

```
$ pctl azure apps get-client-secrets --app-name "$APP" --fail-on-expiry
...
Error: 1 expired and 1 expiring within 30 days, of 3 credential(s).
$ echo $?
6
```

An app with no credentials passes, and so does one whose credentials have no end date to
judge by. See [Output and exit codes](Output-and-Exit-Codes#the-distinctions-that-matter) for
how 6 differs from 5.

### What is never shown

Graph returns a name, a key ID, the dates and a short hint for an existing secret. It
returns the **value** only once, when the secret is created. `get-client-secrets` shows what
Graph returns and nothing else, and creates nothing. A certificate's key material is not shown
either.

**Federated credentials** are a separate resource, shown on their own tab in the portal. They
are not listed here.

---

## `add-client-secret`

Creates a client secret on an app registration, and keeps its value. **Writes.**

Graph shows the value of a new client secret exactly once, in the response that creates it.
A command that made one with nowhere to put the value would be a way to throw credentials
away, so this one refuses to run unless the value has somewhere to go.

| Flag                 | Default        | Effect                                                              |
| -------------------- | -------------- | ------------------------------------------------------------------- |
| `--app-name NAME`    |                | Display name of the app. Give this **or** `--app-id`                |
| `--app-id APPID`     |                | `appId` of the app. Skips the display name search                   |
| `--name NAME`        |                | **Required.** The new secret's name, its description in the portal  |
| `--valid-for-days N` | `180`          | How long it is valid, from 1 to 365. A tenant policy may allow less |
| `--store-in SECRET`  |                | Secrets Manager secret, by name or ARN, to add the new values to    |
| `--show-secret`      |                | Also print the value, once                                          |
| `--overwrite`        |                | Replace keys the `--store-in` secret already has                    |
| `--secret-region`    | `eu-central-1` | Region of the `--store-in` secret                                   |
| `--match`            | `exact`        | How to match a display name                                         |

Plus the [credential and global options](Common-Options). At least one of `--store-in` and
`--show-secret` is required; both may be given.

```bash
pctl azure apps add-client-secret --app-name "Company Incident.io SCIM" \
    --name terraform --store-in platform/app-credentials
pctl azure apps add-client-secret --app-id 8f468c48-e9ac-4dd7-973d-9704b9cdd56d \
    --name ci --valid-for-days 90 --show-secret
```

### What is stored

With `--store-in`, three keys are added to the JSON object held by that secret, and every
other key in it is kept:

| Key                            | Value                                           |
| ------------------------------ | ----------------------------------------------- |
| `<app>_<name>_client_id`       | the app's `appId`                               |
| `<app>_<name>_client_secret`   | the new value                                   |
| `<app>_<name>_client_exp_date` | when it stops working, in UTC, as Graph says it |

The app name and the secret name are lowercased, and every run of characters other than
letters and digits becomes one underscore. App `Incident SCIM` and secret `terraform` give
`incident_scim_terraform_client_id`. A name with no letter or digit in it is refused, since
it would make keys that start with a bare underscore.

The stored expiry is the `endDateTime` Graph returned, not the one that was asked for. A
tenant policy can shorten a secret, and the real end date is the one worth keeping.

The Secrets Manager secret must **already exist** and hold a **JSON object**. It is never
created, and a plain-string secret is refused.

### What it checks and what it undoes

- **Nothing is created without a destination.** With neither `--store-in` nor `--show-secret`
  it exits 2 before any request, because the value would be lost.
- **The destination is checked first.** Before the secret exists, the Secrets Manager
  secret is read: it must exist, not be scheduled for deletion, be a JSON object, and not
  already hold any of the three keys unless `--overwrite` is given. A destination that
  cannot take the values is found out about while there is still nothing to lose.
- **A name the app already uses is refused**, case-insensitively. Creating is not
  idempotent, so running a pipeline twice would otherwise add a second live secret.
- **A failed write removes the secret again.** If storing fails after Graph created the
  secret, the new secret is removed, and the command exits 5 saying so. If even the
  removal fails, the message carries the key ID, so you can remove it by hand: it is live
  and nobody holds its value.
- **A create is never repeated.** After a server error or a dropped connection, the secret
  may or may not exist, and sending again could make two. Only throttling (429) is retried,
  because it means the request was refused. The error says the outcome is unknown.
- **The value never reaches output it was not asked to.** Not the report, not the summary,
  not `-v` logging, and not an error message. Only `--show-secret` prints it, once.

### The report

```json
{
  "app": "Company Incident.io SCIM",
  "appId": "8f468c48-e9ac-4dd7-973d-9704b9cdd56d",
  "name": "terraform",
  "keyId": "3f1a9c52-0b7d-4e0e-9a54-1c2d3e4f5a6b",
  "endDateTime": "2027-05-11T12:00:00Z",
  "storedIn": "platform/app-credentials",
  "storedKeys": [
    "company_incident_io_scim_terraform_client_id",
    "company_incident_io_scim_terraform_client_secret",
    "company_incident_io_scim_terraform_client_exp_date"
  ]
}
```

`storedIn` and `storedKeys` are `null` without `--store-in`, and `secret` is present only with
`--show-secret`. The `keyId` is what `remove-client-secret` takes.

### Permissions

- **Graph:** `Application.ReadWrite.All` or `Directory.ReadWrite.All`.
- **AWS**, on the `--store-in` secret: `secretsmanager:DescribeSecret`,
  `secretsmanager:GetSecretValue` and `secretsmanager:PutSecretValue`. AWS credentials come
  from the usual chain (`AWS_PROFILE`, SSO, an assumed role). See
  [Permissions](Permissions#secrets-manager).

---

## `remove-client-secret`

Removes one client secret from an app registration. **Writes, and cannot be undone.**

| Flag              | Default | Effect                                                              |
| ----------------- | ------- | ------------------------------------------------------------------- |
| `--app-name NAME` |         | Display name of the app. Give this **or** `--app-id`                |
| `--app-id APPID`  |         | `appId` of the app. Skips the display name search                   |
| `--key-id KEYID`  |         | **Required.** The secret's key ID, as `get-client-secrets` shows it |
| `--force`         |         | Remove a secret that still has more than 30 days left               |
| `--match`         | `exact` | How to match a display name                                         |

```bash
pctl azure apps get-client-secrets --app-name "$APP" -o json | jq '.[] | {name, keyId, status}'
pctl azure apps remove-client-secret --app-name "$APP" --key-id 3f1a9c52-0b7d-4e0e-9a54-1c2d3e4f5a6b
```

### Only a key ID names the secret

There is no `--name`. Secret names are not unique, an app can hold two with the same name,
and removal is permanent, so nothing here is ever a choice between several. The key ID is
unique. A key ID that matches nothing exits 4. A key ID that belongs to a **certificate** is
refused with exit 2: Graph asks for proof of possession of an existing certificate to
remove one, which this command cannot give, so only client secrets can be removed.

### When `--force` is needed

Whatever still authenticates with a secret stops working the moment it is removed, so the
guard is about how much time the secret has left:

| The secret                                 | `--force`? |
| ------------------------------------------ | ---------- |
| has already expired                        | no         |
| ends within 30 days, the 30th day included | no         |
| ends in more than 30 days                  | **yes**    |
| has no end date                            | **yes**    |

A secret that has lapsed or is about to is the ordinary thing to clean up. One with a long
time left may well be in use. Without `--force` the command exits 2 and sends nothing,
saying how many days are left. `--force` on a secret that does not need it is harmless.

The 30 days are the same window `get-client-secrets` calls `expiring`, so the two agree on
where the line is.

### What it does not do

It removes the secret from the app registration only. A copy kept in Secrets Manager, for
example by `add-client-secret`, is not touched.

**Permission:** `Application.ReadWrite.All` or `Directory.ReadWrite.All`.

---

## Which command do I want?

| Question                                            | Command                                                                             |
| --------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Who has access to this application?                 | [`sp assignments`](Azure-Service-Principals#assignments)                            |
| Who owns it?                                        | [`sp owners`](Azure-Service-Principals#owners)                                      |
| When does its client secret run out?                | `apps get-client-secrets --app-name "<name>"`                                       |
| Will a secret expire in the next 60 days?           | `apps get-client-secrets --app-name "<name>" --expiring-within 60 --fail-on-expiry` |
| What are its redirect URIs, required permissions?   | `apps get`                                                                          |
| I need a new client secret, kept in Secrets Manager | `apps add-client-secret --app-name "<name>" --name <n> --store-in <secret>`         |
| Remove a secret that expired                        | `apps remove-client-secret --app-name "<name>" --key-id <keyId>`                    |
| I have an `appId`, what is the SP object ID?        | `apps get --app <appId> --with-sp`                                                  |
| I have a name, is it registered here at all?        | `apps get --app "<name>"`                                                           |

## Related

- [Service principals](Azure-Service-Principals) — the other half of the pair
- [Permissions](Permissions)
- [Common options](Common-Options)
