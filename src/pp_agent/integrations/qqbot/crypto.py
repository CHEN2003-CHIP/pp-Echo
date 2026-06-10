from __future__ import annotations

from pp_agent.integrations.qqbot.errors import QQBotConfigError


ED25519_SEED_SIZE = 32


def sign_callback_validation(*, app_secret: str, plain_token: str, event_ts: str) -> dict[str, str]:
    if not app_secret:
        raise QQBotConfigError("QQ Bot app secret is required for callback validation.")
    try:
        from nacl.signing import SigningKey
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install pp-agent with the 'qqbot' extra to use QQ callback validation.") from exc

    seed = _secret_seed(app_secret)
    message = f"{event_ts}{plain_token}".encode("utf-8")
    signed = SigningKey(seed).sign(message)
    return {"plain_token": plain_token, "signature": signed.signature.hex()}


def _secret_seed(app_secret: str) -> bytes:
    raw = app_secret.encode("utf-8")
    if not raw:
        raise QQBotConfigError("QQ Bot app secret is required for callback validation.")
    while len(raw) < ED25519_SEED_SIZE:
        raw += raw
    return raw[:ED25519_SEED_SIZE]

