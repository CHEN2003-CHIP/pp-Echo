# QQBot 配置和启动教程

这份文档面向“我想把手机 QQ / QQ 群消息接进 pp-Echo”的完整配置流程。更底层的 API 说明见 [`docs/integrations/qqbot.md`](qqbot.md)，Bot Center / Bot Gateway 设计见 [`docs/bot_center.md`](../bot_center.md)。

## 1. 准备条件

- 已能启动 pp-Echo Web UI。
- 已在 QQ 开放平台创建官方 QQ Bot。
- 已拿到 QQ Bot 的 `AppID` 和 `AppSecret`。
- 本地安装 Python `3.9+`，如需 Web UI 自动构建，安装 Node.js `20+`。
- 如果要让 QQ 官方服务器访问本地 webhook，需要一个 HTTPS 公网入口，例如 cpolar、cloudflared、frp、ngrok、VPS 反向代理或 Cloudflare Named Tunnel。

不要把完整 pp-Echo Web UI 暴露到公网。公网入口只应该转发 QQ webhook 需要的最小路径：

```text
GET  /api/integrations/qqbot/status
POST /api/integrations/qqbot/webhook
```

## 2. 配置环境变量

在 PowerShell 中设置 QQ Bot 凭据：

```powershell
setx PP_ECHO_QQBOT_APP_ID "your_app_id"
setx PP_ECHO_QQBOT_APP_SECRET "your_app_secret"
setx PP_ECHO_QQBOT_GROUP_TRIGGER "/pp"
setx PP_ECHO_QQBOT_ALLOW_ALL_C2C "true"
```

重新打开 PowerShell 或重新双击 `start-web.bat`，让环境变量生效。

可选 allowlist：

```powershell
setx PP_ECHO_QQBOT_ALLOWED_USERS "user_openid_1,user_openid_2"
setx PP_ECHO_QQBOT_ALLOWED_GROUPS "group_openid_1,group_openid_2"
```

说明：

- `AppSecret` 不会写入 Bot Center 的 `config.json`。
- `qq-main` 默认是 stopped，需要在 Web UI 的 Bots 页面手动 Start。
- 群聊默认必须带 `/pp` 才会触发 Agent。

## 3. 启动 Web UI

在仓库根目录运行：

```powershell
.\start-web.bat
```

默认访问：

```text
http://127.0.0.1:8765
```

打开 Web UI 后进入左侧导航的 `Bots`，你会看到默认的 `QQ 主机器人`。

## 4. 在 Bot Center 启动 QQ 主机器人

1. 打开 `Bots`。
2. 点击 `QQ 主机器人`。
3. 点击 `Start`。
4. 确认状态变成 `running` / `Idle`。

这一步是 logical start：pp-Echo Web 后端会开始处理 QQ webhook 消息，并在下面的目录写入事件和状态：

```text
.pp-agent/bots/qq/qq-main/
```

点击 `Stop` 后，webhook 仍会安全 ACK，但不会进入 Agent；事件里会出现：

```text
message_ignored reason=bot_stopped
```

## 5. 配置公网 HTTPS URL

启动你自己的 tunnel 工具。例如你得到：

```text
https://your-tunnel.example
```

在 Bot 详情页 `Config` 中把它粘贴到 `Public URL`，保存后 Bot Center 会生成：

```text
https://your-tunnel.example/api/integrations/qqbot/webhook
```

把这个完整 URL 填到 QQ 后台的 webhook / callback URL 中。

## 6. QQ 后台配置

在 QQ Bot 官方后台中：

1. 填写 webhook URL：

   ```text
   https://your-tunnel.example/api/integrations/qqbot/webhook
   ```

2. 订阅 C2C 消息事件。
3. 订阅群消息事件。
4. 执行 webhook 验证。pp-Echo 会处理 QQ 官方 `op=13` callback validation。
5. 保存配置。

## 7. 验证链路

本地状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/integrations/qqbot/status
```

Bot Center API：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/bots
```

公网状态：

```powershell
Invoke-RestMethod https://your-tunnel.example/api/integrations/qqbot/status
```

Web UI 验证：

- `Bots -> QQ 主机器人 -> Events` 查看 `webhook_verified`。
- 私聊 QQ Bot，查看 `message_received`、`agent_run_started`、`reply_sent`。
- 群聊发送 `/pp 你好`，确认进入 Agent。
- 群聊不带 `/pp`，确认 `message_ignored reason=missing_group_trigger`。

## 8. 常见问题

QQ 验证失败：

- 检查 `PP_ECHO_QQBOT_APP_SECRET` 是否和 QQ 后台一致。
- 确认 tunnel URL 是 HTTPS。
- 在 Bot Center 的 `Config` 中点击 `Test Verify`。

群聊不回复：

- 确认消息以 `/pp` 开头。
- 如果配置了 `PP_ECHO_QQBOT_ALLOWED_GROUPS`，确认 group openid 在 allowlist 中。

私聊不回复：

- 确认 `PP_ECHO_QQBOT_ALLOW_ALL_C2C=true`，或把用户 openid 加入 `PP_ECHO_QQBOT_ALLOWED_USERS`。

公网 URL 变了：

- tunnel 免费地址常会变化。
- 重新复制新的 public URL 到 Bot Center。
- 更新 QQ 后台 webhook URL。

Bot stopped 时消息被忽略：

- 这是安全设计。
- 到 `Bots -> QQ 主机器人` 点击 `Start`。

## 9. 安全建议

- 不要把完整 Web UI 暴露公网。
- 生产使用时配置 user/group allowlist。
- 群聊保留 `/pp` 触发词。
- 危险工具保留 Approval Gate。
- 不要把 AppSecret、access token 写入文档、日志或截图。
