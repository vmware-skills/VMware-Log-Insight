<!-- mcp-name: io.github.vmware-skills/vmware-log-insight -->

# VMware Log Insight

> **Disclaimer**: Community-maintained open-source project, **not affiliated with,
> endorsed by, or sponsored by VMware, Inc. or Broadcom Inc.** "VMware", "vSphere",
> and "Aria" are trademarks of Broadcom. Source is publicly auditable under the MIT license.

Read-only log search and aggregation for **VMware Aria Operations for Logs**
(formerly vRealize Log Insight) — the appliance that collects syslog from ESXi
hosts, vCenter, and VMs. The centralized-log data source for the VMware skill
family. **Strictly non-destructive**: it queries, it never writes.

## Upgrading to 2.0

2.0 renames all 7 MCP tools so every name starts with a verb (e.g. `alert_get` → `get_log_alert`, `alert_history` → `get_log_alert_history`, `alert_list` → `list_log_alerts`). The full old → new table is in
[RELEASE_NOTES.md](RELEASE_NOTES.md#v200--mcp-tools-renamed-verb-first). Nothing else changes: same tools, parameters,
safety gates and CLI commands. If an agent prompt, script or `~/.vmware/rules.yaml` names a tool, update it — though deny
rules written with the old names keep working with vmware-policy ≥ 1.18 (`vmware-audit policy` lists any rule the
renames widened), and vmware-pilot ≥ 1.13 translates old names in saved workflows.
If an install older than 2.0 shares that `rules.yaml`, give it vmware-policy ≥ 1.18.2 too: it matches each rule
against both the old and the new name, so one file serves both.

## Companion Skills

| Need | Skill | Tools |
|---|---|:-:|
| Raw centralized logs + spikes | **vmware-log-insight** (this) | 7 |
| vCenter events & alarms | [vmware-monitor](https://github.com/vmware-skills/VMware-Monitor) | 27 |
| Metrics, anomalies, capacity | [vmware-aria](https://github.com/vmware-skills/VMware-Aria) | 28 |
| Incident correlation / root cause | [vmware-debug](https://github.com/vmware-skills/VMware-Debug) — feed it `search_logs` output | 2 |
| VM lifecycle / operations | [vmware-aiops](https://github.com/vmware-skills/VMware-AIops) | 49 |

## Install

```bash
uv tool install vmware-log-insight
mkdir -p ~/.vmware-log-insight
cp config.example.yaml ~/.vmware-log-insight/config.yaml   # edit host/username/provider
echo 'VMWARE_LOG_INSIGHT_PROD_PASSWORD=...' > ~/.vmware-log-insight/.env
chmod 600 ~/.vmware-log-insight/.env
vmware-log-insight doctor
```

### Offline / Air-Gapped Install (from source)

This project uses the modern PEP 517 build system (hatchling), so there is **no
`setup.py`** by design — that is expected, not a missing file. If you cloned the
source and hit `ERROR: File "setup.py" or "setup.cfg" not found ... editable mode
currently requires a setuptools-based build`, your `pip` is older than 21.3 and
cannot do an *editable* (`-e`) install with a non-setuptools backend. Editable
mode is a developer convenience, not needed to run the tool — do one of:

```bash
# From the source tree — a normal (non-editable) install builds a wheel:
pip install .              # NOT  pip install -e .

# ...or upgrade pip first, and editable works too:
pip install --upgrade pip && pip install -e .
```

For a **truly air-gapped host**, build the wheels on a connected machine and copy
them over — the target then needs no network:

```bash
# On a connected machine, collect this package + its dependencies as wheels:
pip wheel . -w dist        # → dist/*.whl   (or: uv build, for just this package)

# Copy dist/ to the air-gapped host, then install offline:
pip install --no-index --find-links dist vmware-log-insight
```

## MCP Tools (7 — all read-only)

| Tool | What |
|---|---|
| `search_logs` | Search events by time window + text (whole-token match), up to 200 events |
| `aggregate_logs` | Count/aggregate over time bins (UCOUNT/AVG/... of a `field`), with z-score spike detection |
| `list_log_fields` | List the appliance's fields (name + type), for `aggregate_logs` `field` |
| `get_log_insight_version` | Appliance version/build |
| `list_log_alerts` / `get_log_alert` / `get_log_alert_history` | Query defined alerts and their trigger history |

## Workflows

- **Find errors fast** — `vmware-log-insight search -q error -l 1h`.
- **Where did logs burst?** — `vmware-log-insight aggregate -q error -l 6h --bin-ms 300000`, read `spikes[]`, then `search` the spike window.
- **Root cause** — pass `search_logs` results (plus vCenter events from vmware-monitor and metrics from vmware-aria) to **vmware-debug** `build_incident_timeline`.

## Troubleshooting

- `401 on /sessions` → check username/password/`provider` and the `VMWARE_LOG_INSIGHT_<TARGET>_PASSWORD` env var.
- `503 everywhere` → appliance starting up; `doctor` reports it as a status, not a crash.
- Empty results → widen `--last`; `text` matches whole tokens, not substrings; default API port is **9543** (set `port` if different).
- `UCOUNT needs a field` → pass `--field` (names from `fields`); COUNT and SAMPLE take none.

## Security

Read-only by construction. Credentials in `~/.vmware-log-insight/.env` (`chmod 600`);
plaintext passwords auto-obfuscated to grep-safe `b64:` (obfuscation, not
encryption — inject from a secret manager for real secrecy). TLS on by default.
See [SECURITY.md](SECURITY.md).

<!-- usage: remote-and-exposure -->
## Remote access (HTTPS) and limiting tools

By default `vmware-log-insight mcp` speaks stdio to one local client and offers every tool. Two options change that
(vmware-policy ≥ 1.21.0).

**Serve over HTTPS** so clients on other machines can connect. Every caller needs a bearer token:

```bash
vmware-audit token create alice          # prints the token once; give it to alice
vmware-audit token list                  # names only
vmware-audit token revoke alice          # refused from its next request, no restart
vmware-log-insight mcp --transport https --host 0.0.0.0 --port 8443 \
    --cert /etc/vmware-mcp/server.pem --key /etc/vmware-mcp/server-key.pem \
    --public-name mcp.example.com
```

Connect a client (Claude Code shown; any MCP client that supports streamable HTTP and custom headers works):

```bash
claude mcp add --transport http vmware-log-insight https://mcp.example.com:8443/mcp \
    --header "Authorization: Bearer $VMWARE_MCP_TOKEN"
```

```json
{
  "mcpServers": {
    "vmware-log-insight": {
      "type": "http",
      "url": "https://mcp.example.com:8443/mcp",
      "headers": { "Authorization": "Bearer ${VMWARE_MCP_TOKEN}" }
    }
  }
}
```

- The server will not start without a token, refuses Host/Origin values outside `--public-name`, and checks
  before it binds that unauthenticated requests get 401. Use a certificate your clients trust for those names.
- Behind a TLS-terminating reverse proxy on the same machine use `--transport http --host 127.0.0.1
  --public-name mcp.example.com` and pass the `Authorization` header through.
- Behind a load balancer or gateway on another machine, keep `--transport https` (a self-signed certificate is
  fine), list in `--public-name` the host name the balancer sends as `Host`, and have it forward `Authorization`.
  Its health probe can use `GET /healthz`, which needs no token and returns only `{"status": "ok"}`
  (vmware-policy ≥ 1.23.0).
- Send `traceparent` or `X-Request-ID` with each request to have it stored on the audit row;
  `vmware-audit log --correlation-id ID` then finds the calls behind one platform request.
- The audit log records each caller as `token:<name>`. Calls run side by side, with or without a target: each
  target keeps up to `VMWARE_MCP_POOL_SIZE` sessions (default 2), and each session is a login on the target. A call
  that finds them all busy waits at most 300 s for one.
- **Everyone who can reach the endpoint acts with this server's account.** Tokens identify callers; they grant
  nothing on the platform. Run one endpoint per privilege level.
- **Several people or roles on one endpoint:** run `vmware-audit roles enable` once, then give each token a role (`vmware-audit token create NAME --role reader`, or a role in `roles.yaml` naming tools and targets; vmware-policy ≥ 1.24.0). A role limits what the token may call on this endpoint; it cannot grant more than the account has. See vmware-policy's README, "Roles for network callers".

**Limiting tools:** every tool of this server is read-only, so `--expose read` changes nothing here; it
exists for the write-capable skills. Least privilege comes from the account the server uses.

Details: `skills/vmware-log-insight/references/setup-guide.md` ("Serving MCP over HTTPS", "Limiting which tools are offered").

## License

MIT.
