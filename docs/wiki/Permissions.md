# Permissions

What to grant before a command works, and how to tell a missing permission from a broken
credential.

## Microsoft Graph

These are **application** permissions, granted to the app registration and
**admin-consented**. Delegated permissions are not used: `pctl` authenticates as the app,
not as you.

| Permission                                                   | Needed for                                                                                            |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `Group.Read.All`                                             | `groups list`, `groups get`, `groups members`                                                         |
| `User.Read.All`                                              | `users get`; group members; resolving an owner or assignment target by name or address                |
| `Application.Read.All` **or** `Directory.Read.All`           | `apps list`, `apps get`; `sp list`, `sp get`, `sp assignments`, `sp owners`                           |
| `Application.ReadWrite.All` **or** `Directory.ReadWrite.All` | `sp add-owner`, `sp remove-owner` — **nothing else**                                                  |
| `Synchronization.ReadWrite.All`                              | `sp provision` — **nothing else**                                                                     |
| `EntitlementManagement.Read.All`                             | `eam list-packages`, `get-package`, `list-catalogs`, `get-catalog`, `list-assignments`, `get-request` |
| `EntitlementManagement.ReadWrite.All`                        | `eam add-assignment`, `eam remove-assignment`, `eam delete-package`                                   |

`Directory.Read.All` covers every read on its own, if the app already has it. Grant the two
`ReadWrite` permissions only where those specific commands are actually needed — they are
broad, and 25 of the 30 commands do not want them.

### Per command

| Command                          | Permission                                                                             | Writes |
| -------------------------------- | -------------------------------------------------------------------------------------- | ------ |
| `azure token`                    | none beyond a valid credential                                                         |        |
| `azure raw`                      | whatever the path you call requires                                                    | maybe  |
| `azure groups list`              | `Group.Read.All`                                                                       |        |
| `azure groups get`               | `Group.Read.All`, plus `User.Read.All` for `--members`/`--owners`                      |        |
| `azure groups members`           | `Group.Read.All` + `User.Read.All`                                                     |        |
| `azure users get`                | `User.Read.All`                                                                        |        |
| `azure apps list`                | `Application.Read.All`                                                                 |        |
| `azure apps get`                 | `Application.Read.All`                                                                 |        |
| `azure sp list`                  | `Application.Read.All`                                                                 |        |
| `azure sp get`                   | `Application.Read.All`                                                                 |        |
| `azure sp assignments`           | `Application.Read.All`                                                                 |        |
| `azure sp owners`                | `Application.Read.All`                                                                 |        |
| `azure sp add-owner`             | `Application.ReadWrite.All` + `User.Read.All`                                          | ✅     |
| `azure sp remove-owner`          | `Application.ReadWrite.All` + `User.Read.All`                                          | ✅     |
| `azure sp provision`             | `Synchronization.ReadWrite.All` + `User.Read.All`/`Group.Read.All` to resolve subjects | ✅     |
| `azure eam list-packages`        | `EntitlementManagement.Read.All`                                                       |        |
| `azure eam get-package`          | `EntitlementManagement.Read.All`                                                       |        |
| `azure eam list-catalogs`        | `EntitlementManagement.Read.All`                                                       |        |
| `azure eam get-catalog`          | `EntitlementManagement.Read.All`                                                       |        |
| `azure eam list-assignments`     | `EntitlementManagement.Read.All`                                                       |        |
| `azure eam get-request`          | `EntitlementManagement.Read.All`                                                       |        |
| `azure eam add-assignment`       | `EntitlementManagement.ReadWrite.All` + `User.Read.All`                                | ✅     |
| `azure eam remove-assignment`    | `EntitlementManagement.ReadWrite.All` + `User.Read.All`                                | ✅     |
| `azure eam delete-package`       | `EntitlementManagement.ReadWrite.All`                                                  | 💥     |
| `commands`, `tree`, `completion` | none, they never call a provider                                                       |        |

### Checking what you actually have

A missing permission surfaces as **exit 5** with `Authorization_RequestDenied` and
`Insufficient privileges to complete the operation`. Check the token rather than the portal,
because **a token issued before consent was granted does not carry the new role**:

```bash
pctl azure token --decode | jq -r '.roles[]' | sort
```

If the role is missing there but present in the portal, the cached token predates the
consent. Clear it and try again:

```bash
pctl azure token --clear-cache
```

Tokens are cached for up to an hour, so this is a common few-minutes-of-confusion.

### 401 vs 403

Graph is consistent about these, and so is `pctl`:

| Status | Means                              | Fix                                           |
| ------ | ---------------------------------- | --------------------------------------------- |
| 401    | The token is invalid or expired    | Check tenant, client ID and secret            |
| 403    | The token is fine, the role is not | Grant and consent the permission, clear cache |

A persistent 401 is **not** a consent problem. `pctl` retries once with a fresh token before
reporting it, so if you see one the credentials themselves are wrong.

## AWS

`pctl aws` uses the boto3 credential chain and needs IAM permissions on the table it reads.
Every DynamoDB command is read-only — nothing in `pctl aws` writes.

| Command            | IAM action               |
| ------------------ | ------------------------ |
| `aws ddb tables`   | `dynamodb:ListTables`    |
| `aws ddb describe` | `dynamodb:DescribeTable` |
| `aws ddb scan`     | `dynamodb:Scan`          |
| `aws ddb query`    | `dynamodb:Query`         |
| `aws ddb get`      | `dynamodb:GetItem`       |

A read-only policy covering all five:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:ListTables"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable",
        "dynamodb:Scan",
        "dynamodb:Query",
        "dynamodb:GetItem"
      ],
      "Resource": "arn:aws:dynamodb:eu-central-1:123456789012:table/my-table"
    }
  ]
}
```

`dynamodb:ListTables` cannot be scoped to a table — it is an account-level action, so
`"Resource": "*"` is required for `ddb tables` and only for it.

Querying a secondary index needs the index in the resource ARN as well:

```
arn:aws:dynamodb:eu-central-1:123456789012:table/my-table/index/*
```

## Secrets Manager

If you use `--secret-id` to hold the Graph credentials, the caller also needs:

| IAM action                      | On               |
| ------------------------------- | ---------------- |
| `secretsmanager:GetSecretValue` | the secret's ARN |

The secret is a JSON document with `client_id` and `client_secret` keys. See
[Getting Started](Getting-Started#credentials).

## Related

- [Troubleshooting](Troubleshooting) — what each failure actually means
- [Output and exit codes](Output-and-Exit-Codes) — exit 3 vs 5
