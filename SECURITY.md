# Security Policy

## Disclaimer

This is a community-maintained open-source project and is **not affiliated with,
endorsed by, or sponsored by VMware, Inc. or Broadcom Inc.** "VMware", "vSphere",
and "Aria" are trademarks of Broadcom. Source code is publicly auditable at
[github.com/vmware-skills/VMware-Log-Insight](https://github.com/vmware-skills/VMware-Log-Insight)
under the MIT license.

## Reporting Vulnerabilities

Report security issues via a GitHub private security advisory on the repository,
or by email to the maintainer. Please do not open public issues for security bugs.

## Security Design

### Read-only by construction
This skill exposes **no write tools**. It only queries the Log Insight appliance
(events, aggregations, fields, alerts); it cannot ingest, edit, or delete logs or
alerts. There is no destructive surface to gate.

### Credential management
- Passwords are loaded from `~/.vmware-log-insight/.env` (`chmod 600`), never from
  `config.yaml` and never via MCP messages.
- Per-target convention: `VMWARE_LOG_INSIGHT_<TARGET>_PASSWORD`.
- **At-rest obfuscation**: plaintext `*_PASSWORD` values in `.env` are auto-rewritten
  to a grep-safe `b64:` form on first load (via python-dotenv's own parser, so the
  stored value never drifts). This is **obfuscation, not encryption** — for real
  secrecy, inject from a secret manager (Vault/CyberArk/AWS Secrets Manager/K8s
  Secret) into the env var at process start instead of storing `.env`.

### SSL/TLS verification
On by default (`verify_ssl: true`). Disable only for self-signed lab appliances.

### Transitive dependencies
Depends on `vmware-policy` (shared audit + `@vmware_tool` decorator + `sanitize`).
Read-tool calls are recorded to the shared audit DB (`~/.vmware/audit.db`).

### Prompt-injection protection
All text returned from the appliance passes through `sanitize()` (truncation +
C0/C1 control-character stripping) before reaching the agent.

## Static Analysis

```bash
uvx bandit -r vmware_log_insight/
```

Release bar: 0 Medium-or-higher severity findings.

## Supported Versions

The latest released version receives security fixes. Versions are kept aligned
across the VMware skill family.
