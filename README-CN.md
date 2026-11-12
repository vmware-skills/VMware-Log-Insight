<!-- mcp-name: io.github.vmware-skills/vmware-log-insight -->

# VMware-Log-Insight

通过日志搜索与关联调查基础设施，不修改源系统。

English · [简体中文](README-CN.md)

社区维护 · MIT 开源 · 非 VMware/Broadcom 官方产品。

[![18 秒调查示意演示](https://raw.githubusercontent.com/vmware-skills/marketplace/main/assets/demos/vmware-skills-zh.gif)](https://github.com/vmware-skills/marketplace/blob/main/assets/demos/vmware-skills-zh.mp4)

使用合成数据的示意动画，非实时录屏。[观看家族配音介绍（约 2 分钟）](https://github.com/vmware-skills/marketplace/blob/main/assets/demos/vmware-skills-zh.mp4)

## 能解决什么问题？

- 搜索日志事件并发现字段。
- 聚合结果并调查日志突增。
- 明确展示分页与证据限制。

## 快速开始

安装已发布 CLI，并查看可用命令：

```sh
uv tool install vmware-log-insight==2.4.4
vmware-log-insight --help
```

需要 uv 与 Python >=3.10。远程查询前，在本地配置目标与凭据。[配置指南](skills/vmware-log-insight/references/setup-guide.md).

Claude Code 及其他宿主安装方式见[家族门户](https://github.com/vmware-skills/marketplace/blob/main/README-CN.md)。

## 使用边界

远端操作只读。产品版本和认证契约存在差异；当前支持范围与尚未验证的 Log Management 9.1 边界见详细文档。

## 详细文档

- [能力范围](skills/vmware-log-insight/references/capabilities.md)
- [CLI 用法](skills/vmware-log-insight/references/cli-reference.md)
- [Agent 使用约束](skills/vmware-log-insight/references/agent-guardrails.md)
- [详细用法与架构](skills/vmware-log-insight/references/detailed-guide-CN.md)
- [唯一技能指令正本](skills/vmware-log-insight/SKILL.md)

属于 [VMware Skills 家族](https://github.com/vmware-skills/marketplace/blob/main/README-CN.md)：15 个 skill、14 个 MCP server 与一个共享 Policy 库。如果对你有用，欢迎 Star 家族门户。

[问题与反馈](https://github.com/vmware-skills/VMware-Log-Insight/issues) · [MIT](LICENSE)
