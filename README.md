<!-- mcp-name: io.github.vmware-skills/vmware-log-insight -->

# VMware-Log-Insight

Search and correlate infrastructure logs without changing the source system.

English · [简体中文](README-CN.md)

Community-maintained · MIT · Not an official VMware/Broadcom product.

[![18-second illustrative investigation demo](https://raw.githubusercontent.com/vmware-skills/marketplace/main/assets/demos/vmware-skills-en.gif)](https://github.com/vmware-skills/marketplace/blob/main/assets/demos/vmware-skills-en.mp4)

Synthetic-data animation, not a live recording. [Watch the narrated family introduction (~2 min)](https://github.com/vmware-skills/marketplace/blob/main/assets/demos/vmware-skills-en.mp4)

## Why use it?

- Search log events and discover fields.
- Aggregate results and inspect log spikes.
- Keep pagination and evidence limits visible.

## Get started

Install the published CLI and inspect its commands:

```sh
uv tool install vmware-log-insight==2.4.4
vmware-log-insight --help
```

Requires uv and Python >=3.10. Configure targets and credentials locally before remote queries. [Setup guide](skills/vmware-log-insight/references/setup-guide.md).

For Claude Code and other host installation paths, see the [family portal](https://github.com/vmware-skills/marketplace).

## Know the boundaries

Remote operations are read-only. Product versions and authentication contracts differ; current support and unverified Log Management 9.1 boundaries are documented.

## Go deeper

- [Capabilities](skills/vmware-log-insight/references/capabilities.md)
- [CLI reference](skills/vmware-log-insight/references/cli-reference.md)
- [Agent guardrails](skills/vmware-log-insight/references/agent-guardrails.md)
- [Detailed usage and architecture](skills/vmware-log-insight/references/detailed-guide.md)
- [Canonical skill instructions](skills/vmware-log-insight/SKILL.md)

Part of [VMware Skills](https://github.com/vmware-skills/marketplace): 15 skills, 14 MCP servers and one shared Policy library. If it helps your work, star the family portal.

[Issues and feedback](https://github.com/vmware-skills/VMware-Log-Insight/issues) · [MIT](LICENSE)
