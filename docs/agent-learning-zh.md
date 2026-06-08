# pp-Echo 学习指南（中文）

阅读这份文档前，先记住一个最重要的前提：`pp-Echo` 当前是一个 `Windows-first` 项目。它的 runtime、审批模型、safe rewind、session tree 和工具体系都是真实存在并且值得学习的，但它还不应该被描述成一个已经完成的跨平台 agent 平台，也不应该被包装成一个成熟的 agent team 框架。

这份文档面向刚接触 agent 系统的开发者。目标不是覆盖每一个实现细节，而是帮助你尽快建立正确心智模型：

1. 这个项目是怎么启动起来的。
2. runtime、tools、approvals、sessions、memory、UI 分别在什么位置。
3. 你应该按什么顺序阅读源码。
4. 如果想继续扩展，这个项目适合从哪里下手。

## 0. 先建立正确预期

先把这几件事记清楚，再继续往下读：

- 当前最清晰、最主支持、最适合上手的路径是 Windows。
- 项目核心架构已经很完整，足够作为 agent engineering 学习样本。
- `subagent` 已经存在，但目前还是 MVP 级能力。
- `agent team` 更适合被理解成发展方向，而不是已完成系统。

## 0A. 现在的 subagent 到底是什么

仓库里已经有明确的子代理委派路径，但范围是刻意收窄的。

当前真实状态：

- 用户可以显式写 `@subagent`
- runtime 会把这类请求导向 `spawn_subagent`
- 当前内建 child spec 主要是 `repo-researcher` 和 `change-reviewer`
- 子代理路径更像一次受控委派：fork session、限制工具、运行约束 prompt、回传 summary

它是真实可用的，但它不等于“完整的多 agent planner”，更不等于“成熟 agent team 系统”。

## 1. 这个项目到底是什么

`pp-Echo` 是一个 `Windows-first`、`CLI-first` 的本地 coding agent 项目。

它的核心价值不只是“生成代码”，而是把一套真正可研究、可运行、可扩展的 agent 工程骨架放在你面前，包括：

- 先规划，再执行
- 对高风险动作设置审批门
- 持久化 session 与 timeline
- 支持 git-backed checkpoint 和 safe rewind
- 集成 skills、extensions、MCP 和 memory retrieval
- 同时提供 CLI 和 TUI 两种交互界面

如果用系统视角来理解，可以把它看成：

`CLI/TUI 外壳 + runtime 主循环 + tool/policy 安全层 + session/timeline/checkpoint 存储层 + skills/extensions/MCP 能力层 + memory 检索增强层`

## 2. 当前成熟度怎么理解

### 已经值得学习的部分

- runtime 主循环已经成型
- 工具注册和审批模型已经成型
- session tree 和 rewind 设计已经成型
- checkpoint 与代码工作区恢复已经成型
- CLI / TUI 都能反映 runtime 行为
- memory、skills、extensions、MCP 已经接入体系
- `@subagent` 入口和受控子代理路径已经存在

### 仍在演进的部分

- 项目整体仍然是 Windows-first
- subagent 还比较窄
- 还不是完整 agent team orchestration
- 某些 capability 和体验细节还在继续打磨

## 3. 为什么要明确写 Windows-first

项目现在明确写成 `Windows-first`，不是为了保守，而是为了避免读者产生错误预期。

当前现实是：

- 最快的启动体验主要围绕 Windows 设计
- 辅助脚本主要是 Windows 的 `.bat`
- shell 执行和部分交互体验也更偏向 Windows 路径
- Linux/macOS 兼容不是当前主线目标

所以更准确的说法是：

`现在最适合学习和运行 pp-Echo 的环境是 Windows。`

## 4. 快速上手

### Windows 上最快的启动方式

```powershell
set PP_AGENT_API_KEY=your_api_key
.\start-agent.bat
```

### Windows 上快速启动 TUI

```powershell
set PP_AGENT_API_KEY=your_api_key
.\echo-cli.bat
```

### 通用 Python 启动方式

```powershell
set PP_AGENT_API_KEY=your_api_key
set PYTHONPATH=src
python -m pp_agent.cli.main chat
```

如果你只是第一次体验，建议优先走 `chat`，再看 `tui`。

## 5. subagent 当前真实进度

这是学习时最容易被高估的一块，所以单独讲清楚。

### 现在已经有的能力

- 用户可以显式请求 `@subagent`
- runtime 会优先走 `spawn_subagent`
- 当前有少量内建 child spec
- 子代理执行路径是真实存在的

### 当前子代理具体怎么工作

- 先从当前 session fork 出子 session
- 给子代理设置更窄的 system prompt
- 给子代理更受限的工具 allowlist
- 执行一次受控子任务
- 把结果以 summary 形式返回主代理

### 现在还没有的能力

- 完整的多 agent planner
- 长时运行的 agent team 协作体系
- 丰富的 child role 生态
- 高度自动化的多代理自治

如果要用一句话描述当前状态：

`pp-Echo 已经有 subagent MVP，但还不是成熟的 agent team 系统。`

## 6. 推荐阅读顺序

如果你是第一次系统性阅读这个仓库，推荐按这个顺序：

1. [src/pp_agent/cli/main.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/cli/main.py)
2. [src/pp_agent/app/bootstrap.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/app/bootstrap.py)
3. [src/pp_agent/runtime/runtime.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/runtime.py)
4. [src/pp_agent/tools/registry.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/tools/registry.py)
5. [src/pp_agent/runtime/session_host.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/session_host.py)
6. [src/pp_agent/runtime/git_checkpoint.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/git_checkpoint.py)
7. [src/pp_agent/runtime/safe_rewind.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/safe_rewind.py)
8. [src/pp_agent/storage/settings.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/storage/settings.py)
9. [src/pp_agent/cli/chat.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/cli/chat.py)
10. [src/pp_agent/tui/app.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/tui/app.py)

这个顺序的好处是：你会先看到系统入口，再看到装配层，再看到 runtime 核心，最后再回头看 UI 和体验层。

## 7. 跟着一条请求走完整个系统

一个用户请求大致会这样流过系统：

### 第 1 步：从入口进入

入口通常是：

- CLI chat
- CLI run
- TUI

对应文件：

- [src/pp_agent/cli/main.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/cli/main.py)

### 第 2 步：bootstrap 组装系统

接着进入：

- [src/pp_agent/app/bootstrap.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/app/bootstrap.py)

这里会把系统真正组装起来，包括：

- settings
- stores
- tool registry
- llm client
- runtime
- memory
- skills
- extensions
- MCP

### 第 3 步：进入 runtime 主循环

核心文件：

- [src/pp_agent/runtime/runtime.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/runtime.py)

runtime 负责：

- 接收用户输入
- 构建上下文
- 请求模型
- 解析 assistant 文本和 tool call
- 必要时暂停等待 planner approval
- 执行工具
- 发出 lifecycle events
- 持久化状态

### 第 4 步：通过 ToolRegistry 执行工具

核心文件：

- [src/pp_agent/tools/registry.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/tools/registry.py)

这里负责统一回答：

- 有哪些工具
- 工具暴露什么 schema
- 哪些工具允许模型调用
- 哪些动作需要审批
- 工具最终如何执行

### 第 5 步：写入存储与会话系统

相关数据会落到：

- session store
- timeline store
- pending approvals
- checkpoint metadata

这也是为什么 `pp-Echo` 不只是一个简单聊天程序，而是一个带状态、可恢复、可回退的 agent 系统。

## 8. 核心模块分别适合学什么

### 8.1 `runtime/runtime.py`

这是整个项目最值得精读的文件之一。

你可以重点学：

- turn-based agent execution
- planner pause points
- 工具调用调度
- 错误处理
- tool call 执行回填

### 8.2 `tools/registry.py`

这是理解“agent 工具系统”的关键入口。

你可以重点学：

- 工具注册
- tool metadata
- permission domain
- 执行入口统一化
- 扩展工具接入方式

### 8.3 `runtime/session_host.py`

这个模块能帮助你理解为什么这里的 session 不是简单消息列表。

你可以重点学：

- session 生命周期
- session tree 组织方式
- fork / rewind 操作
- session 与 checkpoint 的协同

### 8.4 `runtime/git_checkpoint.py` 和 `runtime/safe_rewind.py`

这是项目辨识度很高的一块。

它告诉你一件很重要的事：

`真正可用的 coding agent，应该有可逆性，而不是只会一直往前改。`

### 8.5 `storage/settings.py`

这个文件适合用来理解项目配置是怎么收口的。

你可以重点看：

- 默认值
- 环境变量
- 本地配置文件
- `AGENTS.md` 与 system prompt 的关系

它也能帮助你看清当前 Windows-first 的一些边界。

### 8.6 `memory/*`

memory 相关模块适合帮助你理解“检索增强”是怎样嵌进 runtime 的。

### 8.7 `skills/*`、`extensions/*`、`mcp/*`

这几部分适合理解：

- 如何让 runtime 获得额外能力
- 如何把本地扩展接进来
- 如何与外部能力协议对接

### 8.8 `cli/*` 和 `tui/*`

这部分更适合理解：

- 用户如何观察 runtime 行为
- 同一套 runtime 如何支撑不同 UI

## 9. 常见误解

### 误解 1：现在已经是成熟 agent team 了

不是。当前更准确的说法是 subagent MVP，不是成熟 agent team。

### 误解 2：既然核心架构跨平台味道很重，就已经正式跨平台了

不是。当前公开定位仍然应该是 Windows-first。

### 误解 3：planner approval 和 execution approval 是一回事

不是。项目里明确区分了计划阶段和执行阶段的风险控制。

### 误解 4：session 就是聊天记录

不是。这里的 session 更接近带分叉能力的版本化会话。

### 误解 5：memory 就是把历史全部塞回 prompt

不是。这里更接近检索增强，而不是简单拼接历史。

## 10. 当前限制

为了不让学习者高估完成度，这里把当前限制说清楚：

- 当前最适合使用的环境是 Windows
- Linux/macOS 不是当前主支持路径
- subagent 现在更偏 summary-oriented child handoff
- `agent team` 仍然是方向，不是完成品
- 某些能力边界和体验细节仍在继续演进

## 11. 新手或贡献者最适合从哪里下手

如果你想快速进入状态，建议优先做这些事情：

- 先跑通一次 Windows 下的启动流程
- 再读 runtime、approval、session、subagent 相关主线
- 然后再看 memory 和 capability wiring
- 最后再去读 CLI/TUI 的展现层
- 如果想做小改动，优先围绕 runtime 邻近模块做增量理解

## 12. 接下来最值得继续精读的文件

如果你读完这份文档，最值得继续往下深挖的是：

- [src/pp_agent/runtime/runtime.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/runtime.py)
- [src/pp_agent/tools/registry.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/tools/registry.py)
- [src/pp_agent/runtime/session_host.py](/E:/Pycharm%20Project/pp-Echo/src/pp_agent/runtime/session_host.py)

配合阅读：

- [docs/source-map.md](/E:/Pycharm%20Project/pp-Echo/docs/source-map.md)
- [docs/source-reading-roadmap.md](source-reading-roadmap.md)

如果你是中文读者，这份文档应该帮助你快速回答三个问题：

- 这个项目现在适合拿来学什么
- 哪些部分已经真实可学
- 哪些地方还不能高估完成度
