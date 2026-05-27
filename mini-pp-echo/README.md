# mini-pp-echo

`mini-pp-echo` 是 pp-Echo 的教学最小版。它不接真实 LLM API，不依赖第三方库，只用 FakeLLM 和脚本化响应演示本地编程 Agent 的核心工程机制。

建议按顺序运行：

```powershell
python mini-pp-echo/01_loop.py
python mini-pp-echo/02_tool_call.py
python mini-pp-echo/03_file_edit.py
python mini-pp-echo/04_approval.py
python mini-pp-echo/05_memory.py
python mini-pp-echo/06_checkpoint.py
python mini-pp-echo/07_mcp_mock.py
```

对应关系：

| 文件 | 教学主题 | 完整工程参考 |
| --- | --- | --- |
| `01_loop.py` | 最小 Agent Loop | `src/pp_agent/runtime/runtime.py` |
| `02_tool_call.py` | Tool Registry 与工具调用 | `src/pp_agent/tools/registry.py` |
| `03_file_edit.py` | 文件读写与最小 patch | `src/pp_agent/tools/file_tools.py` |
| `04_approval.py` | Approval Gate 与安全策略 | `src/pp_agent/tools/policy.py`, `src/pp_agent/storage/approvals.py` |
| `05_memory.py` | 记忆检索与上下文注入 | `src/pp_agent/memory/*`, `src/pp_agent/learning/*` |
| `06_checkpoint.py` | Checkpoint 与回退 | `src/pp_agent/runtime/git_checkpoint.py`, `src/pp_agent/runtime/safe_rewind.py` |
| `07_mcp_mock.py` | MCP 风格工具发现与调用 | `src/pp_agent/mcp/*` |

这些脚本不是完整 Agent，也不会修改核心工程。它们的目标是让你先把概念跑起来，再去读真实代码。
