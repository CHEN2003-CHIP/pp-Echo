# QQBot 配置和启动教程

这份文档记录从零启动官方 QQ Bot 接入 pp-Echo 的完整流程。更底层的接口说明见 [qqbot.md](qqbot.md)。

目标链路：

```text
手机 QQ
  -> QQ 官方平台
  -> 公网 HTTPS 地址
  -> 本机 QQBot-only proxy :8788
  -> pp-Echo Web :8765
  -> Agent Runtime
  -> QQ 官方发送接口
  -> 手机 QQ 收到回复
```

不要把完整 pp-Echo Web UI 暴露到公网。公网入口只应该转发这两个最小路由：

```text
GET  /api/integrations/qqbot/status
POST /api/integrations/qqbot/webhook
```

## 1. 准备条件

- 已在 QQ 开放平台创建官方 QQ Bot。
- 已拿到 QQ Bot 的 `AppID` 和 `AppSecret`。
- 本地能启动 pp-Echo Web。
- 本地安装 Python `3.9+`。
- 本地有一个公网 HTTPS 隧道工具。推荐先用 cpolar，国内网络下通常比 cloudflared/ngrok 更顺。

## 2. 配置 QQBot 环境变量

在 PowerShell 中设置系统环境变量：

```powershell
setx /M PP_ECHO_QQBOT_ENABLED "true"
setx /M PP_ECHO_QQBOT_APP_ID "your_app_id"
setx /M PP_ECHO_QQBOT_APP_SECRET "your_app_secret"
setx /M PP_ECHO_QQBOT_GROUP_TRIGGER "/pp"
setx /M PP_ECHO_QQBOT_ALLOW_ALL_C2C "true"
```

如果没有管理员权限，去掉 `/M` 设置为当前用户变量：

```powershell
setx PP_ECHO_QQBOT_ENABLED "true"
setx PP_ECHO_QQBOT_APP_ID "your_app_id"
setx PP_ECHO_QQBOT_APP_SECRET "your_app_secret"
setx PP_ECHO_QQBOT_GROUP_TRIGGER "/pp"
setx PP_ECHO_QQBOT_ALLOW_ALL_C2C "true"
```

设置后重新打开 PowerShell，或者重启 `start-web.bat`，让环境变量生效。

可选白名单：

```powershell
setx PP_ECHO_QQBOT_ALLOWED_USERS "user_openid_1,user_openid_2"
setx PP_ECHO_QQBOT_ALLOWED_GROUPS "group_openid_1,group_openid_2"
```

说明：

- `PP_ECHO_QQBOT_ENABLED=true` 必须设置，否则 webhook 会返回 disabled/404。
- `AppSecret` 不要写进文档、截图、日志或 Git。
- 私聊默认允许所有 C2C 用户，除非 `PP_ECHO_QQBOT_ALLOW_ALL_C2C=false`。
- 群聊默认必须以 `/pp` 开头才会进入 Agent。

## 3. 启动 pp-Echo Web

在仓库根目录运行：

```powershell
.\start-web.bat
```

或者：

```powershell
python -m pp_agent.cli.main web --workspace "E:\Pycharm Project\pp-Echo"
```

默认地址：

```text
http://127.0.0.1:8765
```

检查 QQBot 是否启用：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/integrations/qqbot/status
```

期望看到：

```json
{
  "enabled": true,
  "configured": true,
  "webhook_path": "/api/integrations/qqbot/webhook",
  "group_trigger": "/pp"
}
```

## 4. 启动 QQBot-only proxy

为了避免把完整 Web UI 暴露到公网，先启动只代理 QQBot 路由的小服务：

```powershell
python scripts\qqbot_proxy.py --target http://127.0.0.1:8765 --port 8788
```

检查代理：

```powershell
Invoke-RestMethod http://127.0.0.1:8788/api/integrations/qqbot/status
```

确认其他路径不会暴露：

```powershell
Invoke-WebRequest http://127.0.0.1:8788/api/health
```

这个请求应该返回 `404`。

## 5. 使用 cpolar 暴露 8788

### 5.1 下载 portable 版 cpolar

推荐下载免安装 zip，而不是 MSI。MSI 会尝试安装到 `C:\Program Files\cpolar` 并注册服务，可能需要管理员权限。

下载地址：

```text
https://www.cpolar.com/static/downloads/releases/3.3.12/cpolar-stable-windows-amd64.zip
```

解压后应有：

```text
cpolar.exe
```

验证：

```powershell
.\cpolar.exe version
```

### 5.2 配置 cpolar authtoken

登录 cpolar 后台，复制 authtoken，然后执行：

```powershell
.\cpolar.exe authtoken your_cpolar_token
```

只需要配置一次。

### 5.3 启动隧道

只暴露 QQBot-only proxy 的 `8788` 端口：

```powershell
.\cpolar.exe http 8788
```

成功后会看到类似：

```text
Tunnel Status    online
Forwarding       http://3545e59b.r9.cpolar.cn -> http://localhost:8788
Forwarding       https://3545e59b.r9.cpolar.cn -> http://localhost:8788
```

使用 HTTPS 地址：

```text
https://3545e59b.r9.cpolar.cn
```

公网 status 测试：

```powershell
Invoke-RestMethod https://3545e59b.r9.cpolar.cn/api/integrations/qqbot/status
```

期望看到：

```json
{
  "enabled": true,
  "configured": true
}
```

## 6. QQ 后台配置

QQ 官方后台 webhook/callback URL 填：

```text
https://你的-cpolar-域名/api/integrations/qqbot/webhook
```

例如：

```text
https://3545e59b.r9.cpolar.cn/api/integrations/qqbot/webhook
```

事件订阅建议：

### 单聊事件

必须选择：

```text
C2C消息事件
C2C_MESSAGE_CREATE
```

不用选择：

```text
C2C添加好友 FRIEND_ADD
C2C删除好友 FRIEND_DEL
C2C关闭消息推送 C2C_MSG_REJECT
C2C打开消息推送 C2C_MSG_RECEIVE
```

### 群事件

如果要群聊使用，选择群消息相关事件。优先找：

```text
群消息事件
GROUP_MESSAGE_CREATE
```

如果后台只有“@机器人消息事件”，选择：

```text
GROUP_AT_MESSAGE_CREATE
```

pp-Echo 当前兼容：

```text
C2C_MESSAGE_CREATE
GROUP_MESSAGE_CREATE
GROUP_AT_MESSAGE_CREATE
```

群聊仍建议用 `/pp` 触发：

```text
/pp 你好，介绍一下当前项目
```

如果你订阅的是 `GROUP_AT_MESSAGE_CREATE`，可能需要：

```text
@你的机器人 /pp 你好
```

### 其他事件

频道事件、互动事件可以先不选。当前 QQ adapter 的稳定能力是 C2C 文本和群文本。

## 7. 验证链路

### 本地验证

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/integrations/qqbot/status
Invoke-RestMethod http://127.0.0.1:8788/api/integrations/qqbot/status
```

### 公网验证

```powershell
Invoke-RestMethod https://你的-cpolar-域名/api/integrations/qqbot/status
```

### op=13 回调验证

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri https://你的-cpolar-域名/api/integrations/qqbot/webhook `
  -ContentType "application/json" `
  -Body '{"op":13,"d":{"plain_token":"test_plain","event_ts":"1234567890"}}'
```

期望返回：

```json
{
  "plain_token": "test_plain",
  "signature": "一串十六进制签名"
}
```

### 手机 QQ 测试

私聊 bot：

```text
hello
```

群聊：

```text
/pp hello
```

如果群事件是 `GROUP_AT_MESSAGE_CREATE`，测试：

```text
@你的机器人 /pp hello
```

## 8. 常见问题

### status 显示 disabled

检查：

```powershell
[Environment]::GetEnvironmentVariable("PP_ECHO_QQBOT_ENABLED", "Machine")
[Environment]::GetEnvironmentVariable("PP_ECHO_QQBOT_ENABLED", "User")
```

确认值是：

```text
true
```

重启 Web 后再测。

### status 显示 configured=false

检查：

```powershell
PP_ECHO_QQBOT_APP_ID
PP_ECHO_QQBOT_APP_SECRET
```

不要把 secret 打印到聊天或截图里。

### QQ 后台验证失败

检查：

- webhook URL 必须是 HTTPS。
- URL 必须包含 `/api/integrations/qqbot/webhook`。
- cpolar 窗口必须保持运行。
- `PP_ECHO_QQBOT_APP_SECRET` 必须和 QQ 后台一致。
- 先用公网 `op=13` 命令测试签名。

### 私聊收到 FileNotFoundError

这是旧版本 QQ session 映射创建方式导致的。修复后，新 QQ 会话会调用 pp-Echo 的 `create_session()` 创建真实 session。

如果本地已有旧坏映射，可以备份并删除：

```powershell
Copy-Item .pp-agent\integrations\qqbot-sessions.json .pp-agent\integrations\qqbot-sessions.json.bak
Remove-Item .pp-agent\integrations\qqbot-sessions.json
```

然后重启 Web。

### 群聊不回复

检查：

- 是否订阅了群事件。
- 消息是否以 `/pp` 开头。
- 如果订阅的是 `GROUP_AT_MESSAGE_CREATE`，是否 @ 了机器人。
- 如果配置了 `PP_ECHO_QQBOT_ALLOWED_GROUPS`，确认 group openid 在白名单里。

### 私聊不回复

检查：

- 是否订阅了 `C2C_MESSAGE_CREATE`。
- `PP_ECHO_QQBOT_ALLOW_ALL_C2C=true`，或者用户 openid 已加入 `PP_ECHO_QQBOT_ALLOWED_USERS`。

### cpolar 域名变化

免费域名可能会变化。每次变化后都要更新 QQ 后台 webhook URL：

```text
https://新的-cpolar-域名/api/integrations/qqbot/webhook
```

### Agent 需要审批

QQ 不会绕过 Approval Gate。如果 Agent 触发危险操作，QQ 会收到提示，让你去本地 Web UI 审批。

## 9. 启动顺序速查

每次要让 QQ Bot 工作，按这个顺序启动：

```powershell
# 1. 启动 pp-Echo Web
.\start-web.bat

# 2. 新开 PowerShell，启动 QQBot-only proxy
python scripts\qqbot_proxy.py --target http://127.0.0.1:8765 --port 8788

# 3. 新开 PowerShell，启动 cpolar
.\cpolar.exe http 8788
```

QQ 后台 webhook URL：

```text
https://cpolar给你的域名/api/integrations/qqbot/webhook
```

## 10. 安全建议

- 不要把完整 pp-Echo Web UI 暴露到公网。
- cpolar 只转发 `8788`，不要转发 `8765`。
- 生产或长期使用时配置 `PP_ECHO_QQBOT_ALLOWED_USERS` / `PP_ECHO_QQBOT_ALLOWED_GROUPS`。
- 群聊保留 `/pp` 触发词。
- 不要把 AppSecret、access token、cpolar authtoken 写进 Git、文档截图或公开聊天。
