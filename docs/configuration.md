# pp-Echo 配置说明

本文集中说明 pp-Echo 的本地配置入口。它覆盖环境变量、项目级配置、资源清单以及常用 JSON 示例，方便读者在不展开 README 的情况下理解配置优先级。

## 配置加载顺序

pp-Echo 按下面顺序合并配置，后面的配置会覆盖前面的默认值：

1. 代码内置默认值，来自 `Settings`。
2. 环境变量覆盖。
3. 工作区配置 `.pp-agent/config.json`。
4. 仓库指引 `AGENTS.md`。
5. 可选系统指引 `.pp-agent/SYSTEM.md`。

核心实现位于 `src/pp_agent/storage/settings.py`。

## 常用环境变量

| 变量 | 作用 |
| --- | --- |
| `PP_AGENT_API_KEY` | OpenAI-compatible provider 的 API key。 |
| `PP_AGENT_BASE_URL` | 覆盖模型 provider base URL。 |
| `PP_AGENT_MODEL` | 覆盖默认模型名。 |
| `PP_AGENT_ENABLE_THINKING` | 开关 provider 特定 thinking/reasoning 参数。 |
| `PP_AGENT_HOME` | 覆盖全局 pp-Echo 状态目录。 |
| `PP_AGENT_SESSIONS_DIR` | 覆盖会话存储目录。 |
| `PP_AGENT_TIMELINES_DIR` | 覆盖 timeline 存储目录。 |
| `PP_AGENT_CHECKPOINTS_DIR` | 覆盖 checkpoint 存储目录。 |

## 项目级配置

在仓库根目录创建 `.pp-agent/config.json` 可以设置当前项目专属配置。典型字段包括：

```json
{
  "model": "your_model_name",
  "base_url": "https://your-provider.example/v1",
  "enable_thinking": false,
  "tool_policy": {
    "shell_timeout_seconds": 30,
    "permission_mode": "workspace-write",
    "ask_tools": ["run_shell", "write_file", "edit_file"],
    "tool_confirmation": {
      "write_file": true,
      "edit_file": true,
      "run_shell": true,
      "high_risk_plan": true
    }
  },
  "capabilities": {
    "builtin_tools": { "enable": true },
    "skills": { "enable_project": true, "enable_user": true },
    "extensions": { "enable_project": true, "enable_user": true },
    "mcp": { "enable": false, "config_paths": [] }
  }
}
```

## 配置原则

- 不要把真实 `.env`、API key、token 或 cookie 提交到仓库。
- release 前应确认 `.env.example` 可表达必要字段，而 `.env` 已被 `.gitignore` 忽略。
- 对工具权限、MCP、Browser、Memory 等能力做改动后，优先运行 `workflow doctor --json` 检查当前工作区状态。
- 如果配置会影响 runtime 装配，应同时检查 `src/pp_agent/app/bootstrap.py` 和 `src/pp_agent/storage/settings.py`。
