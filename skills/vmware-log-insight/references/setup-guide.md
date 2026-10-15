# vmware-log-insight Setup Guide

## Install

```bash
uv tool install vmware-log-insight==2.3.0
mkdir -p ~/.vmware-log-insight
cp config.example.yaml ~/.vmware-log-insight/config.yaml
```

## Configure targets

Edit `~/.vmware-log-insight/config.yaml`:

```yaml
targets:
  prod:
    host: loginsight.example.com
    username: admin
    port: 9543            # public API port (default 9543)
    verify_ssl: true
    provider: Local       # Local | ActiveDirectory | <vIDM provider name>
    environment: production   # production | staging | lab — see below
default_target: prod
```

### `environment` — an optional label

`environment` is an optional free-form label on a target. An environment-scoped
`deny` rule in `~/.vmware/rules.yaml` can match on it — for example, to freeze
writes on `production`; a target with no label is simply not matched by such a
rule.

Every tool this skill ships is read-only, and reads are never gated — so the
label changes nothing for Log Insight today. Set it anyway to keep the family's
config files consistent, so a future write tool is correctly scoped. Run
`vmware-audit policy` to see the rules in force.

## Credentials

Passwords are **never** stored in `config.yaml`. Set the per-target env var:

```bash
# ~/.vmware-log-insight/.env  (chmod 600)
VMWARE_LOG_INSIGHT_PROD_PASSWORD=yourpassword
```

```bash
chmod 600 ~/.vmware-log-insight/.env
```

The env var name is `VMWARE_LOG_INSIGHT_<TARGET>_PASSWORD` where `<TARGET>` is the
upper-cased target name (hyphens → underscores).

### Password obfuscation at rest

On first load, any plaintext `*_PASSWORD` value in `.env` is automatically
rewritten to a grep-safe `b64:<encoded>` form and decoded transparently at
runtime, so a casual `grep` of the file no longer reveals the password. Values
are read/written through python-dotenv's own parser, so the stored secret never
drifts from what you configured.

> **This is obfuscation, not encryption.** Anyone who can read the file can still
> decode it. For real secrecy at rest, do not store the password in `.env` at all —
> inject it from a secret manager (HashiCorp Vault, CyberArk, AWS Secrets Manager,
> or a Kubernetes Secret) into the `VMWARE_LOG_INSIGHT_<TARGET>_PASSWORD`
> environment variable at process start. The code reads the env var either way:
> ```bash
> export VMWARE_LOG_INSIGHT_PROD_PASSWORD="$(vault kv get -field=password secret/loginsight/prod)"
> vmware-log-insight mcp
> ```

## Verify

```bash
vmware-log-insight doctor
```

Checks: config file, `.env` permissions, config parse, password env vars, network
reachability (TCP 9543), authentication, appliance version, MCP server import.

## MCP client configuration

```json
{
  "command": "uvx",
  "args": ["--from", "vmware-log-insight==2.3.0", "vmware-log-insight-mcp"],
  "env": { "VMWARE_LOG_INSIGHT_CONFIG": "~/.vmware-log-insight/config.yaml" }
}
```

If you installed with `uv tool install`, prefer the entry point `vmware-log-insight mcp`
(no PyPI resolution at startup — robust behind corporate TLS proxies, 踩坑 #25).

## Serving MCP over HTTPS

By default the MCP server speaks stdio to one local client. To let clients on other machines reach it, serve it over
HTTPS. Every caller then needs a bearer token.

```bash
vmware-audit token create alice                      # prints the token once; give it to alice
vmware-log-insight mcp --transport https --host 0.0.0.0 --port 8443 \
    --cert /etc/vmware-mcp/server.pem --key /etc/vmware-mcp/server-key.pem \
    --public-name mcp.example.com
```

- Clients connect to `https://mcp.example.com:8443/mcp` and send `Authorization: Bearer <token>`.
- `--public-name` lists every host name clients use (comma-separated); requests for any other Host or Origin are
  refused. Use a certificate your clients trust for those names.
- Behind a reverse proxy that terminates TLS (Nginx, HAProxy) on the same machine, use
  `--transport http --host 127.0.0.1 --public-name mcp.example.com` (the names the proxy forwards in `Host`), and
  have the proxy pass the `Authorization` header through.
- `vmware-audit token list` / `token revoke NAME` manage callers; a revoked token is refused from its next request.
  Replace a leaked token under a new name.
- The server will not start without at least one token, and checks before it binds that unauthenticated requests
  are refused.
- Each audit row records the caller as `token:<name>`. Calls run side by side, with or without a target: each
  target keeps up to `VMWARE_MCP_POOL_SIZE` sessions (default 2), and each session is a login on the target. A call
  that finds them all busy waits at most 300 s for one.
- **Everyone who can reach the endpoint acts with this server's account.** Tokens identify callers; they grant
  nothing on the platform. Run one endpoint per privilege level (for example a read-only account behind
  `--expose read`, and a separate endpoint for operators).

## Security

> **Disclaimer**: Community-maintained open-source project, **not affiliated with,
> endorsed by, or sponsored by VMware, Inc. or Broadcom Inc.**

1. **Source Code** — https://github.com/vmware-skills/VMware-Log-Insight (MIT).
2. **Config file contents** — `config.yaml` holds only host/port/username/provider;
   no passwords or tokens. Secrets live only in `.env` (`chmod 600`).
3. **Webhook data scope** — none. This skill makes no outbound calls except to the
   configured Log Insight appliance.
4. **TLS verification** — on by default (`verify_ssl: true`); disable only for
   self-signed lab appliances.
5. **Prompt-injection protection** — all API text passes through `sanitize()`
   (truncation + C0/C1 control-char stripping).
6. **Least privilege** — use a read-only Log Insight service account; this skill
   only reads (events, aggregations, fields, alerts) and never writes.

**The account is the boundary.** This skill has no write tools, but an agent that can run shell commands can reach
the platform without it (SSH, curl, govc, PowerCLI). Give the service account only the read privileges it needs;
nothing in the skill can stop the same credentials being used another way.

