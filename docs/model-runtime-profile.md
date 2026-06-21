# Model / Runtime Profile 分层

pp-Echo 现在把模型相关配置整理为 Provider / Model / Runtime / Connector 四层。Provider 负责供应商和认证，ModelCapabilityProfile 负责模型能力画像，RuntimeProfile 负责一次 Agent turn 的执行能力画像，Connector / Channel 负责 Web、CLI、QQBot 等消息入口。

## 四层职责

Provider 只负责供应商和认证方式，例如 OpenAI、DeepSeek、Qwen / DashScope、Anthropic 或自定义 OpenAI-compatible endpoint。Provider 可以描述协议、base URL、API key 环境变量名和推荐模型，但不承载具体模型能力判断。

ModelCapabilityProfile 负责具体模型的能力画像，例如 tool calling、JSON mode、streaming、vision、long context、reasoning mode、structured output、上下文窗口、输出上限、质量提示、运行时兼容性和成本提示。它不允许保存 API key、secret、token 或 password 类字段，适合写入 trace 和 run metadata。

RuntimeProfile 负责一次 Agent turn 由哪个运行时执行，以及这个运行时支持哪些 Agent 能力。当前默认 runtime 是 `pp_echo_native`，它对应现有 in-process `AgentRuntime`，复用 `SessionHost`、`ToolRegistry`、审批、checkpoint、memory、MCP 和 subagent 能力。

Connector / Channel 后续负责 Web、CLI、QQBot 等消息入口。Connector 只把外部消息规范化后交给 runtime，不决定模型能力，也不绕过 RuntimeProfile。

## pp_echo_native 能力

`pp_echo_native` 当前声明支持 planning、tool_calling、approval、checkpoint、memory、mcp、subagent、streaming、file_edit 和 shell_exec。它的隔离方式是 workspace-scoped execution，并在可用时结合 git-backed checkpoint 和 approval gate。

## Resolver 状态

新代码通过 resolver 获取 `ModelCapabilityProfile` 和 `RuntimeProfile`：

- `resolve_model_profile(config)`
- `resolve_runtime_profile(config)`

旧的 `provider_id + model_id` 兼容 adapter 已移除。用户配置仍然可以选择 provider/model，但能力判断只通过 `ModelCapabilityProfile`，运行时能力判断只通过 `RuntimeProfile`。

## Trace Metadata

每次 Agent run 开始后，runtime 会记录 `model_runtime_selected` lifecycle event，并进入 TraceRecorder 的事件流。TraceInspect 会展示 Model / Runtime 卡片，包含：

- `provider_id`
- `model_id`
- `runtime_id`
- `model_capabilities`
- `runtime_supports`

Trace run attributes 也会附带相同的 compact summary，方便后续按模型能力和运行时能力分析问题。

## 外部 CLI Runtime

未来可以接入 external CLI runtime，例如 Codex CLI、Claude Code 或 OpenCode。当前版本只保留 `external_cli_placeholder` 这样的 profile 形状，不实际启动或代理任何外部 CLI。真正接入时应新增 runtime adapter，并继续让 registry 只保存 profile 声明。
