# `pctl azure apps`

Application registrations — what the Entra ID portal calls **App registrations**. Read-only.

**Permission:** `Application.Read.All` or `Directory.Read.All`.

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

## Which command do I want?

| Question                                          | Command                                                  |
| ------------------------------------------------- | -------------------------------------------------------- |
| Who has access to this application?               | [`sp assignments`](Azure-Service-Principals#assignments) |
| Who owns it?                                      | [`sp owners`](Azure-Service-Principals#owners)           |
| What are its redirect URIs, required permissions? | `apps get`                                               |
| I have an `appId`, what is the SP object ID?      | `apps get --app <appId> --with-sp`                       |
| I have a name, is it registered here at all?      | `apps get --app "<name>"`                                |

## Related

- [Service principals](Azure-Service-Principals) — the other half of the pair
- [Permissions](Permissions)
- [Common options](Common-Options)
