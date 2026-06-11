# QQ Bot Integration

pp-Echo can connect to the official QQ Bot API v2 as an external messaging channel. The QQ adapter receives webhook events, maps each QQ conversation to a pp-Echo session, runs the existing Agent Runtime, and sends a text reply back to QQ.

## Supported

- Official QQ Bot API v2 webhook callback validation (`op=13`).
- C2C text messages.
- QQ group text messages triggered by `/pp`.
- Text replies for C2C and group conversations.
- App access token retrieval and refresh.
- Stable QQ conversation to pp-Echo session mapping.
- Event dedupe with a local TTL store.
- User and group allowlists.
- Per-conversation serialization so one QQ conversation does not run multiple messages through the same session concurrently.
- Run timeout and observable `run_timed_out` events.

## Not Yet Supported

- Image understanding.
- Downloading QQ files into `AttachmentService`.
- Voice transcription.
- Markdown template messages.
- In-QQ approval buttons.
- WebSocket gateway access.

The code keeps a `maybe_ingest_qq_attachments(...)` boundary so QQ media can later flow into:

```text
QQ media/file event
  -> download bytes
  -> AttachmentService.upload_bytes(session_id, filename, data)
  -> Agent reads the attachment through existing attachment tools
```

## Install

```bash
pip install -e ".[web,qqbot]"
```

## Environment

QQ Bot is disabled by default. Enable it explicitly:

```powershell
$env:PP_ECHO_QQBOT_ENABLED="true"
$env:PP_ECHO_QQBOT_APP_ID="your_app_id"
$env:PP_ECHO_QQBOT_APP_SECRET="your_app_secret"
$env:PP_ECHO_QQBOT_GROUP_TRIGGER="/pp"
$env:PP_ECHO_QQBOT_ALLOW_ALL_C2C="true"

pp-agent web --workspace "E:\Pycharm Project\GrowUP"
```

Optional settings:

```env
PP_ECHO_QQBOT_API_BASE=https://api.sgroup.qq.com
PP_ECHO_QQBOT_TOKEN_URL=https://bots.qq.com/app/getAppAccessToken
PP_ECHO_QQBOT_ALLOWED_USERS=
PP_ECHO_QQBOT_ALLOWED_GROUPS=
PP_ECHO_QQBOT_REPLY_MAX_CHARS=1800
PP_ECHO_QQBOT_REQUEST_TIMEOUT=10
PP_ECHO_QQBOT_RUN_TIMEOUT_SECONDS=180
PP_ECHO_QQBOT_MAX_QUEUE_PER_CONVERSATION=5
PP_ECHO_QQBOT_DEDUPE_TTL_SECONDS=600
PP_ECHO_QQBOT_SESSION_STORE=.pp-agent/integrations/qqbot-sessions.json
PP_ECHO_QQBOT_DEDUPE_STORE=.pp-agent/integrations/qqbot-dedupe.json
```

Webhook URL:

```text
https://your-domain.example.com/api/integrations/qqbot/webhook
```

Public QQ webhooks need HTTPS. For local sandbox testing, use a tunnel such as cloudflared or ngrok and configure any QQ platform URL or IP allowlist required by the official console.

## QQ Console Setup

1. Create a QQ Bot in the official platform.
2. Record the AppID and AppSecret.
3. Configure the webhook callback URL.
4. Subscribe to C2C and group message events.
5. Test callback validation.
6. Test C2C text and group `/pp` text messages.

## Group Usage

```text
/pp 你是谁？介绍一下当前项目。
/pp 总结一下这个仓库的功能。
/pp 帮我检查最近的错误日志。
```

C2C messages do not require `/pp` by default. If `PP_ECHO_QQBOT_ALLOW_ALL_C2C=false`, the sender must be listed in `PP_ECHO_QQBOT_ALLOWED_USERS`.

## Security Notes

- QQ is an external entrypoint.
- Group messages only trigger on `/pp` by default.
- Group and C2C allowlists are available.
- QQ does not bypass pp-Echo Approval Gate.
- Dangerous approvals are still completed in the local Web UI, not inside QQ.
- QQ messages are not automatically written to long-term memory.
- QQ attachments are not automatically imported into the workspace.
- AppSecret and access tokens are not returned by status APIs or included in prompts.
- AppSecret and access tokens are redacted from bot status, events, traces, and logs.

## Troubleshooting

- Callback validation failed: check `PP_ECHO_QQBOT_APP_SECRET` and the official webhook URL.
- Enabled but webhook returns 500: confirm AppID and AppSecret are set.
- Group has no response: ensure the message starts with `/pp` and the group is allowlisted if `PP_ECHO_QQBOT_ALLOWED_GROUPS` is set.
- Send message failed: check access token permissions, QQ platform rate limits, and event subscriptions.
- Local webhook unreachable: use public HTTPS tunneling and QQ platform allowlists.
- Waiting approval: open the local Web UI and approve or reject the pending action.
- Run timed out: inspect the Bot Center trace and adjust `PP_ECHO_QQBOT_RUN_TIMEOUT_SECONDS` only if needed.
- Queue full: the same QQ conversation already has too many pending messages; retry after the current run completes.
- Stopped but still running: `Stop` blocks new messages; `POST /api/bots/{bot_id}/stop?force=true` attempts to cancel known in-flight tasks.

## Bot Center Status Semantics

`enabled` is the desired logical state, not a process supervisor state. pp-Echo currently does not manage the QQ-only proxy process or cpolar/cloudflared. Bot Center health reports `process_state=not_managed` unless a future supervisor owns those processes.

Use `GET /api/bots/qq-main/health` for the effective status fields:

- `desired_state`
- `process_state`
- `agent_state`
- `ingress_state`
- `qq_state`
- `last_message_at`
- `last_run_at`
- `last_reply_at`
- `last_error`
- `warnings`

The current adapter is intentionally text-only: no image understanding, no automatic QQ file import, and no QQ-side approval buttons.

