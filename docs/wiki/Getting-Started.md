# Getting Started

## Install

`pctl` needs **Python 3.14 or newer** and is managed with [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lagrianitis/pctl.git
cd pctl
uv sync --extra fast          # dev install, with the optional speed-ups
uv run pctl --help
```

Two optional extras:

| Extra   | Adds             | Why                                                         |
| ------- | ---------------- | ----------------------------------------------------------- |
| `fast`  | `uvloop`, `h2`   | A faster event loop, and HTTP/2 to Graph                    |
| `azure` | `azure-identity` | `DefaultAzureCredential`, so `az login` works as a fallback |

Both are detected at runtime and degrade gracefully when absent — nothing fails because you
skipped them.

```bash
uv sync --extra fast --extra azure    # everything
uv sync --no-dev                      # app only, no test tooling
```

## Credentials

### Microsoft Graph

Resolved in this order, first match wins:

1. `--tenant-id` and `--client-id` flags
2. `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
3. `--secret-id` / `PCTL_AZURE_SECRET_ID`, reading a JSON secret from AWS Secrets Manager
4. `DefaultAzureCredential`, if `azure-identity` is installed — `az login`, managed
   identity, workload identity

**A Graph client secret is never a flag.** Flags land in shell history and in `ps` output,
so `azure` has no `--client-secret`. `--secret-id` names a secret; it does not carry one.
For OAuth tokens, see [OAuth](OAuth).

```bash
export AZURE_TENANT_ID=contoso.onmicrosoft.com
export AZURE_CLIENT_ID=00000000-0000-0000-0000-000000000000
export AZURE_CLIENT_SECRET=...        # prefer a secret manager
```

> `pctl` does **not** read `.env` by itself. If you keep one, source it:
>
> ```bash
> set -a; source .env; set +a
> ```

### AWS

The standard boto3 chain: `--profile`, `--region`, `AWS_PROFILE`, `AWS_REGION`, shared
config, SSO, assumed roles, instance credentials. `--endpoint-url` points any DynamoDB
command at a local instance.

## First commands

```bash
uv run pctl azure token                       # prove the credentials work
uv run pctl azure groups list --limit 5
uv run pctl aws ddb tables
```

`pctl azure token` masks the token by default and reports its expiry. It is the cheapest way
to tell a credential problem from a permission problem — see
[Troubleshooting](Troubleshooting).

## Find things without reading this wiki

```bash
pctl commands | grep -i assign      # search the whole surface
pctl tree                           # see its shape
pctl completion --shell zsh >> ~/.zshrc
```

[Finding a command](Finding-Commands) covers all three. Turning on completion is the single
highest-value minute you can spend here.

## Shortcuts worth knowing early

**Unambiguous prefixes work** at every level:

```bash
pctl az gr li          # pctl azure groups list
pctl azure eam list-p  # pctl azure eam list-packages
```

**Aliases** exist because the portal and Graph disagree on names:

```bash
pctl azure enterprise-apps get --name "..."   # same as: azure sp get
pctl azure access-packages list-packages      # same as: azure eam list-packages
```

**Global options** work before the case or on the leaf command, but **not in between**:

```bash
pctl -o json azure groups list      # works
pctl azure groups list -o json      # works
pctl azure -o json groups list      # usage error
```

## Where to go next

- [Permissions](Permissions) — what to grant before anything works
- [Output and exit codes](Output-and-Exit-Codes) — formats, and scripting against exit codes
- [Common options](Common-Options) — the flags that recur everywhere
