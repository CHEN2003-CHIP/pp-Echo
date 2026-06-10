from __future__ import annotations

import pytest

from pp_agent.integrations.qqbot.crypto import sign_callback_validation
from pp_agent.integrations.qqbot.errors import QQBotConfigError


def test_sign_callback_validation_returns_stable_hex() -> None:
    first = sign_callback_validation(app_secret="secret", plain_token="plain", event_ts="123")
    second = sign_callback_validation(app_secret="secret", plain_token="plain", event_ts="123")

    assert first["plain_token"] == "plain"
    assert first["signature"]
    int(first["signature"], 16)
    assert first == second


def test_sign_callback_validation_changes_with_token() -> None:
    one = sign_callback_validation(app_secret="secret", plain_token="one", event_ts="123")
    two = sign_callback_validation(app_secret="secret", plain_token="two", event_ts="123")

    assert one["signature"] != two["signature"]


def test_sign_callback_validation_requires_secret() -> None:
    with pytest.raises(QQBotConfigError):
        sign_callback_validation(app_secret="", plain_token="plain", event_ts="123")

