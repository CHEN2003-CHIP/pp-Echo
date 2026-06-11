# Bot Center

Bot Center is pp-Echo's unified gateway for external message entry points. QQ Bot is the first adapter, but the storage layout, API, and UI are designed for more platforms such as Feishu, WeCom, Telegram, email, and scheduled jobs.

## Security Boundary

Do not expose the full pp-Echo Web UI to the public internet. Public tunnels should point only at the minimal QQ-only proxy endpoints:

- `GET /api/integrations/qqbot/status`
- `POST /api/integrations/qqbot/webhook`

The Bot Center page is a local control plane. It can start or stop a bot logically, inspect events, and configure the public URL, but it is not meant to be the public webhook surface.

QQ Bot keeps these defaults:

- `qq-main` is created automatically but starts stopped.
- Group messages require the `/pp` trigger.
- Tool approval is required by default.
- Shell access is disabled by default in bot policy.
- AppId and AppSecret still come from environment or existing secure configuration, not from Bot Center config files.

## Start Web

Start the Web UI as usual:

```powershell
.\start-web.bat
```

Then open the local Web UI. The left navigation includes `Bots`.

## Start QQ Main Bot

Open `Bots`, choose `QQ 主机器人`, and click `Start`. This performs logical start:

- `qq-main` becomes enabled and running.
- Incoming webhook messages are processed.
- `bot_started` is written to the bot event log.
- The bot data directory is created.

Click `Stop` to return to a safe stopped state. Incoming messages are acknowledged but ignored with `message_ignored` and `reason=bot_stopped`.

## Configure Public URL

Start your tunnel tool manually, for example cpolar, cloudflared, frp, ngrok, a VPS reverse proxy, or a Cloudflare Named Tunnel. Paste the public base URL into Bot Center:

```text
https://your-public-host.example
```

Bot Center trims trailing slashes and generates:

```text
https://your-public-host.example/api/integrations/qqbot/webhook
```

Paste that generated URL into the QQ Bot backend webhook setting.

## Verify

Local status:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/api/integrations/qqbot/status
```

Public status:

```powershell
Invoke-RestMethod https://your-public-host.example/api/integrations/qqbot/status
```

Simulated op=13 verification:

- Open Bot detail.
- Go to `Config`.
- Click `Test Verify`.
- Confirm `webhook_verified` appears in `Events`.

Phone QQ private chat:

- Send a message to the bot.
- Confirm `message_received`, `agent_run_started`, and `reply_sent` or `reply_failed`.
- Check `Trace` for the bot run index.

QQ group chat:

- Without `/pp`, the message should create `message_ignored` with `reason=missing_group_trigger`.
- With `/pp hello`, it should create `message_received` and start an Agent run.

Stopped bot:

- Click `Stop`.
- Send a message.
- Confirm `message_ignored` with `reason=bot_stopped`.

## Data Directory

Each bot owns an independent directory:

```text
.pp-agent/
  bots/
    qq/
      qq-main/
        config.json
        status.json
        events.jsonl
        messages.jsonl
        logs/
          bot.log
          error.log
        runs/
          YYYY-MM-DD/
            run_xxx.json
        traces/
        approvals/
```

`events.jsonl` contains lifecycle, message, webhook, run, approval, reply, and error events. `messages.jsonl` stores normalized incoming bot messages with source metadata. `runs/YYYY-MM-DD/*.json` stores the compatibility run index that links bot messages to pp-Echo sessions and future trace records.

## Common Issues

Cloudflared quick tunnel unavailable: use cpolar, frp, ngrok, a VPS reverse proxy, or a named Cloudflare tunnel. Bot Center only needs the final public base URL.

cpolar URL changed: paste the new public URL in Bot Center and update the QQ backend webhook URL.

QQ verification failed: check `PP_ECHO_QQBOT_APP_SECRET`, then run `Test Verify` in Bot Center. Secrets are not shown in the UI.

Group chat has no reply: include `/pp` before the message, or change the group trigger in config.

AppSecret mismatch: update the environment variable used by the Web backend and restart Web.

Allowlist ignored the message: check `allowed_user_ids` and `allowed_group_ids` in the Security tab.

Bot stopped ignored the message: click `Start` in Bot Center. Stopped bots acknowledge webhook calls but do not trigger Agent runs.

## Safety Recommendations

- Do not expose the full Web UI.
- Use user and group allowlists for production bots.
- Keep the `/pp` group trigger.
- Require approval for risky tools.
- Keep secrets out of config files, frontend payloads, and logs.

## Stable Bot Semantics

Bot Center `Start` and `Stop` are logical controls:

- `Start` sets `desired_state=enabled` and allows new webhook messages to enter the adapter.
- `Stop` sets `desired_state=disabled`; new webhook messages are acknowledged but recorded as `message_ignored`.
- `enabled=true` does not mean a process is running.
- This version does not supervise the QQ-only proxy process.
- This version does not supervise cpolar, cloudflared, frp, ngrok, or other tunnel processes.
- Read readiness from Bot Center health plus doctor/report output.

`GET /api/bots/{bot_id}/health` returns `effective_status`:

- `desired_state`: `enabled` or `disabled`.
- `process_state`: usually `not_managed` for QQ proxy/tunnel lifecycle.
- `agent_state`: `idle`, `receiving`, `running_agent`, `waiting_approval`, or `error`.
- `ingress_state`: `local_only`, `public_configured`, `public_reachable`, `public_unreachable`, or `unknown`.
- `qq_state`: `not_configured`, `configured`, `token_ok`, `token_error`, or `unknown`.
- `still_running_count`: known in-flight background tasks.
- `queued_count`: known queued messages.

Events have monotonic `event_id` values. The UI and API can poll incrementally with:

```text
GET /api/bots/{bot_id}/events?after_id=123&limit=100
```

Bot traces are stored as standard JSON in `traces/YYYY-MM-DD/*.json`. If a trace file is corrupted, list APIs return `corrupted=true` for that file instead of crashing.

Public URL validation is strict: production URLs must use `https://`. `http://localhost` and `http://127.0.0.1` are allowed only for local development. `file://`, `javascript://`, `ftp://`, and malformed URLs are rejected.

Common status troubleshooting:

- QQ verification failed: check `PP_ECHO_QQBOT_APP_SECRET` and the configured webhook URL.
- `public_configured` but not reachable: run a status check through the public tunnel and confirm the tunnel points to the QQ-only proxy.
- `token_error`: check QQ AppID/AppSecret and platform permissions.
- `waiting_approval`: approve or reject the pending action in the local Web UI.
- `run_timed_out`: inspect the trace and adjust `PP_ECHO_QQBOT_RUN_TIMEOUT_SECONDS` only if the work is expected to be slow.
- Stopped but still running: `Stop` blocks new messages by default; `POST /api/bots/{bot_id}/stop?force=true` attempts to cancel known in-flight tasks.

Current capability boundary:

- Text-only C2C and group messages.
- Group chat requires `/pp` by default.
- No image understanding.
- No automatic QQ file import.
- No QQ-side approval buttons.
- Approval remains in the local Web UI.
