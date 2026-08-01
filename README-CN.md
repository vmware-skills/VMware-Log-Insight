<!-- mcp-name: io.github.vmware-skills/vmware-log-insight -->

# VMware Log Insight（中文）

> **声明**：本项目为社区维护的开源项目，**与 VMware, Inc. 或 Broadcom Inc. 无任何隶属、
> 背书或赞助关系。** "VMware"、"vSphere"、"Aria" 为 Broadcom 商标。源码以 MIT 许可证公开可审计。

面向 **VMware Aria Operations for Logs**（原 vRealize Log Insight，集中收集 ESXi / vCenter /
VM syslog 的日志平台）的**只读**日志检索与聚合。VMware skill 家族的集中日志数据源。
**严格无破坏性**：只查询，从不写入。

## 配套 Skill

| 需求 | Skill | 工具数 |
|---|---|:-:|
| 原始集中日志 + 突刺 | **vmware-log-insight**（本项目） | 7 |
| vCenter 事件与告警 | [vmware-monitor](https://github.com/vmware-skills/VMware-Monitor) | 27 |
| 指标 / 异常 / 容量 | [vmware-aria](https://github.com/vmware-skills/VMware-Aria) | 28 |
| 故障关联 / 根因 | [vmware-debug](https://github.com/vmware-skills/VMware-Debug)（把 `log_search` 结果喂给它） | 2 |
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

`log_search`（按时间窗 + 文本 + 字段过滤检索）、`log_aggregate`（按时间桶聚合 + z-score
突刺检测）、`log_fields`、`log_version`、`alert_list` / `alert_get` / `alert_history`。

## 常用工作流

- **快速找错**：`vmware-log-insight search -q error -l 1h`
- **日志何时突增**：`vmware-log-insight aggregate -q error -l 6h --bin-ms 300000`，看 `spikes[]`，再 `search` 突刺时间窗
- **根因定位**：把 `log_search` 结果（连同 vmware-monitor 的 vCenter 事件、vmware-aria 的指标）交给 **vmware-debug** 的 `incident_timeline`

## 安全

结构上只读。凭据存于 `~/.vmware-log-insight/.env`（`chmod 600`）；明文密码首次加载自动
转为 grep 不可见的 `b64:` 形式（**是混淆不是加密**——真合规请从 secret manager 注入）。
默认开启 TLS 校验。详见 [SECURITY.md](SECURITY.md)。

## 许可证

MIT。
