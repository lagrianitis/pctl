# Security

## Never store cloud credentials in a configuration file

No cloud provider credential is ever written into a file that lives in the repo or
ships with the package. This covers AWS access keys and session tokens, Azure client
secrets and certificates, bearer or refresh tokens, and any other long-lived
provider secret.

Off limits, without exception:

- `pyproject.toml`, `.gitlab-ci.yml`, `.env`, YAML/JSON/INI/TOML config, Dockerfiles
  and Containerfiles, Kubernetes manifests, Terraform `.tfvars`.
- Source defaults: no secret as a literal, a fallback value, or a click option default.
- Test fixtures and sample data, beyond the obvious dummies already in use
  (`"testing"` for AWS keys, the fake tenant and JWT in the `helpers` module).

### Where credentials come from instead

Follow the chain that `config.py` already implements, in this order:

1. **Environment variables** — `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
   `AZURE_CLIENT_SECRET`, and the standard AWS variables.
2. **AWS Secrets Manager** via `--secret-id` / `PCTL_AZURE_SECRET_ID`, resolved at
   runtime by `secrets.py`.
3. **The provider's own credential chain** — the boto3 chain for AWS (profiles, SSO,
   assumed roles, instance credentials) and `DefaultAzureCredential` for Azure
   (`az login`, managed identity, workload identity).

In CI, secrets come from masked/protected GitLab CI variables or OIDC role
assumption. Do not commit them, and do not echo them into job logs.

### Rules that follow from this

- **Do not accept a secret as a CLI flag.** Flags land in shell history and `ps`
  output. Secrets come from the environment or a secret manager. `--secret-id` names
  a secret; it is not the secret. Follow the same pattern for any new provider.
- **The one deliberate exception is `pctl oauth --client-secret`.** The owner chose to
  allow it, knowing the cost, so that every `oauth` setting can be given as a flag as well
  as an environment variable, with the flag winning. It is the only such flag: `azure`
  still has none, and a new provider does not get one on the strength of this. The
  environment variable and `--secret-id` remain the documented way, and the flag's help
  text says why. Never log the value, keep it out of `repr`, and never echo it back in
  output.
- **Config files may reference, never contain.** A secret's identifier, ARN or
  environment variable name is fine; its value is not.
- `.env.example` holds placeholder names with empty or obviously fake values, and is
  the only `.env*` file that may be committed. Keep real `.env` files gitignored.
- **Mask secrets in output.** Default to masked, like `pctl azure token` does, and
  make the raw form an explicit opt-in (`--raw`). Never log a secret, and keep
  credential fields out of `repr` (`field(repr=False)`).
- Cached tokens stay in the user cache directory with `0600` files inside a `0700`
  directory. Never cache a credential inside the repo or the package.
- If a task seems to need a credential in a config file, stop and ask. Do not invent
  a placeholder that looks real, and do not work around the rule.
