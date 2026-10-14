<!-- mcp-name: io.github.vmware-skills/vmware-log-insight -->

# VMware Log Insight（中文）

> **声明**：本项目为社区维护的开源项目，**与 VMware, Inc. 或 Broadcom Inc. 无任何隶属、
> 背书或赞助关系。** "VMware"、"vSphere"、"Aria" 为 Broadcom 商标。源码以 MIT 许可证公开可审计。

面向 **VMware Aria Operations for Logs**（原 vRealize Log Insight，集中收集 ESXi / vCenter /
VM syslog 的日志平台）的**只读**日志检索与聚合。VMware skill 家族的集中日志数据源。
**严格无破坏性**：只查询，从不写入。

## 升级到 2.0

2.0 把 7 个 MCP 工具改成动词在前（例如 `alert_get` → `get_log_alert`, `alert_history` → `get_log_alert_history`, `alert_list` → `list_log_alerts`），完整的新旧名对照表见
[RELEASE_NOTES.md](RELEASE_NOTES.md#v200--mcp-tools-renamed-verb-first)。其他都不变：工具、参数、安全确认门和 CLI 命令都一样。
如果 agent 提示词、脚本或 `~/.vmware/rules.yaml` 里写了工具名，请改成新名——不过用旧名写的 deny 规则在
vmware-policy ≥ 1.18 下仍然生效（`vmware-audit policy` 会列出因改名而多匹配的规则），vmware-pilot ≥ 1.13 也会自动转换已保存工作流里的旧名。
如果还有 2.0 之前的安装共用这个 `rules.yaml`，请把它的 vmware-policy 也升到 ≥ 1.18.2：它会按新旧两个名字匹配每条规则，一份文件两边都管用。

## 配套 Skill

| 需求 | Skill | 工具数 |
|---|---|:-:|
| 原始集中日志 + 突刺 | **vmware-log-insight**（本项目） | 7 |
| vCenter 事件与告警 | [vmware-monitor](https://github.com/vmware-skills/VMware-Monitor) | 27 |
| 指标 / 异常 / 容量 | [vmware-aria](https://github.com/vmware-skills/VMware-Aria) | 28 |
| 故障关联 / 根因 | [vmware-debug](https://github.com/vmware-skills/VMware-Debug)（把 `search_logs` 结果喂给它） | 2 |
| VM 生命周期 / 运维 | [vmware-aiops](https://github.com/vmware-skills/VMware-AIops) | 49 |

## 安装

```bash
uv tool install vmware-log-insight
mkdir -p ~/.vmware-log-insight
cp config.example.yaml ~/.vmware-log-insight/config.yaml   # 填写 host/username/provider
echo 'VMWARE_LOG_INSIGHT_PROD_PASSWORD=...' > ~/.vmware-log-insight/.env
chmod 600 ~/.vmware-log-insight/.env
vmware-log-insight doctor
```

## MCP 工具（7 个，全只读）

`search_logs`（按时间窗 + 文本 + 字段过滤检索）、`aggregate_logs`（按时间桶聚合 + z-score
突刺检测）、`list_log_fields`、`get_log_insight_version`、`list_log_alerts` / `get_log_alert` / `get_log_alert_history`。

## 常用工作流

- **快速找错**：`vmware-log-insight search -q error -l 1h`
- **日志何时突增**：`vmware-log-insight aggregate -q error -l 6h --bin-ms 300000`，看 `spikes[]`，再 `search` 突刺时间窗
- **根因定位**：把 `search_logs` 结果（连同 vmware-monitor 的 vCenter 事件、vmware-aria 的指标）交给 **vmware-debug** 的 `build_incident_timeline`

## 安全

结构上只读。凭据存于 `~/.vmware-log-insight/.env`（`chmod 600`）；明文密码首次加载自动
转为 grep 不可见的 `b64:` 形式（**是混淆不是加密**——真合规请从 secret manager 注入）。
默认开启 TLS 校验。详见 [SECURITY.md](SECURITY.md)。

## 许可证

MIT。
