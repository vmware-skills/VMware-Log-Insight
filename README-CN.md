<!-- mcp-name: io.github.vmware-skills/vmware-log-insight -->

# VMware Log Insight（中文）

要用自己的模型和 Agent 平台进行只读自测，请看 marketplace 根目录的[共享模型适配自测任务](https://github.com/vmware-skills/marketplace/blob/main/MODEL_FIT_SELF_TEST.md)。

> **声明**：本项目为社区维护的开源项目，**与 VMware, Inc. 或 Broadcom Inc. 无任何隶属、
> 背书或赞助关系。** "VMware"、"vSphere"、"Aria" 为 Broadcom 商标。源码以 MIT 许可证公开可审计。

面向 **VMware Aria Operations for Logs**（原 vRealize Log Insight，集中收集 ESXi / vCenter /
VM syslog 的日志平台）的**只读**日志检索与聚合。VMware skill 家族的集中日志数据源。
**严格无破坏性**：只查询，从不写入。

## 升级到 2.0

2.0 把全部 7 个 MCP 工具改成动词在前（例如 `alert_get` → `get_log_alert`, `alert_history` → `get_log_alert_history`, `alert_list` → `list_log_alerts`），完整的新旧名对照表见
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

| 工具 | 作用 |
|---|---|
| `search_logs` | 按时间窗 + 文本检索事件（按整词匹配），最多 200 条 |
| `aggregate_logs` | 按时间桶计数/聚合（对某个 `field` 做 UCOUNT/AVG/...），附 z-score 突刺检测 |
| `list_log_fields` | 列出设备上的字段（名称 + 类型），供 `aggregate_logs` 的 `field` 使用 |
| `get_log_insight_version` | 设备版本/构建号 |
| `list_log_alerts` / `get_log_alert` / `get_log_alert_history` | 查询已定义的告警及其触发历史 |

## 常用工作流

- **快速找错**：`vmware-log-insight search -q error -l 1h`
- **日志何时突增**：`vmware-log-insight aggregate -q error -l 6h --bin-ms 300000`，看 `spikes[]`，再 `search` 突刺时间窗
- **根因定位**：把 `search_logs` 结果（连同 vmware-monitor 的 vCenter 事件、vmware-aria 的指标）交给 **vmware-debug** 的 `build_incident_timeline`

## 排障

- `/sessions 返回 401` → 检查 username/password/`provider` 以及 `VMWARE_LOG_INSIGHT_<TARGET>_PASSWORD` 环境变量。
- `处处 503` → 设备正在启动；`doctor` 把它报告为状态，而不是崩溃。
- 结果为空 → 放宽 `--last`；`text` 按整词匹配，不是子串（可试 `word*`）；默认 API 端口是 **9543**（不同请设置 `port`）。
- `UCOUNT needs a field` → 传 `--field`（名称来自 `fields`）；COUNT 和 SAMPLE 不带字段。

## 安全

结构上只读。凭据存于 `~/.vmware-log-insight/.env`（`chmod 600`）；明文密码首次加载自动
转为 grep 不可见的 `b64:` 形式（**是混淆不是加密**——真合规请从 secret manager 注入）。
默认开启 TLS 校验。详见 [SECURITY.md](SECURITY.md)。

<!-- usage: remote-and-exposure -->
## 远程访问（HTTPS）与限制工具

默认情况下 `vmware-log-insight mcp` 通过 stdio 服务一个本地客户端，并提供全部工具。以下两个选项可以改变这一点
（需 vmware-policy ≥ 1.21.0）。

**通过 HTTPS 提供服务**，让其他机器上的客户端连接。每个调用者都需要一个 bearer token：

```bash
vmware-audit token create alice          # 只显示一次，交给 alice
vmware-audit token list                  # 只列名字
vmware-audit token revoke alice          # 下一个请求起即拒绝，无需重启
vmware-log-insight mcp --transport https --host 0.0.0.0 --port 8443 \
    --cert /etc/vmware-mcp/server.pem --key /etc/vmware-mcp/server-key.pem \
    --public-name mcp.example.com
```

连接客户端（以 Claude Code 为例；任何支持 streamable HTTP 和自定义请求头的 MCP 客户端都可以）：

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

- 没有 token 时服务不会启动；`--public-name` 之外的 Host/Origin 一律拒绝；绑定端口前会自检，确认未认证请求得到 401。
  证书要用客户端信任、且覆盖这些名字的证书。
- 在同一台机器上由反向代理终结 TLS 时，用 `--transport http --host 127.0.0.1 --public-name mcp.example.com`，
  并让代理透传 `Authorization` 头。
- 负载均衡或网关在另一台机器上时，保持 `--transport https`（自签证书也可以），在 `--public-name` 里写上负载均衡
  转发时带的 `Host` 名，并让它透传 `Authorization`。健康检查可以用 `GET /healthz`：不需要 token，只返回
  `{"status": "ok"}`（需 vmware-policy ≥ 1.23.0）。
- 每个请求带上 `traceparent` 或 `X-Request-ID`，它会记进审计记录；用 `vmware-audit log --correlation-id ID`
  就能查到平台上某一次请求对应的调用。
- 审计日志把每个调用者记为 `token:<名字>`。无论是否指定 target，调用都并行执行：每个 target 最多保持
  `VMWARE_MCP_POOL_SIZE` 个会话（默认 2），每个会话都是在该 target 上的一次登录。会话全被占用时，
  调用最多等待 300 秒。
- **能连到这个端点的人，都以该 server 配置的账号操作。** token 只用来识别调用者，不在平台上授予任何权限。
  每个权限级别单独起一个端点。
- **一个端点给多人或多种角色用：** 先运行一次 `vmware-audit roles enable`，再给每个 token 指定角色（`vmware-audit token create 名字 --role reader`，或在 `roles.yaml` 里定义可用的工具和 target；需 vmware-policy ≥ 1.24.0）。角色只能限定这个 token 在本端点上能调用什么，不能超出账号本身的权限。详见 vmware-policy README 的「网络调用者的角色」一节。

**限制工具：**本 server 的工具全部只读，所以 `--expose read` 在这里不改变任何东西，它是为有写工具的 skill
准备的。最小权限来自 server 使用的账号。

详见 `skills/vmware-log-insight/references/setup-guide.md`（"Serving MCP over HTTPS"、"Limiting which tools are offered"）。

## 许可证

MIT。
