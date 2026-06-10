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
- QQ messages are not automatically written to long-term memory.
- QQ attachments are not automatically imported into the workspace.
- AppSecret and access tokens are not returned by status APIs or included in prompts.

## Troubleshooting

- Callback validation failed: check `PP_ECHO_QQBOT_APP_SECRET` and the official webhook URL.
- Enabled but webhook returns 500: confirm AppID and AppSecret are set.
- Group has no response: ensure the message starts with `/pp` and the group is allowlisted if `PP_ECHO_QQBOT_ALLOWED_GROUPS` is set.
- Send message failed: check access token permissions, QQ platform rate limits, and event subscriptions.
- Local webhook unreachable: use public HTTPS tunneling and QQ platform allowlists.

