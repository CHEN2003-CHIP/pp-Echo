from __future__ import annotations

from pp_agent.integrations.qqbot.config import load_qqbot_config


def test_qqbot_config_defaults_disabled() -> None:
    config = load_qqbot_config({})

    assert config.enabled is False
    assert config.allow_all_c2c is True
    assert config.reply_max_chars == 1800


def test_qqbot_config_enabled_and_allowlists() -> None:
    config = load_qqbot_config(
        {
            "PP_ECHO_QQBOT_ENABLED": "true",
            "PP_ECHO_QQBOT_APP_ID": "app",
            "PP_ECHO_QQBOT_APP_SECRET": "secret",
            "PP_ECHO_QQBOT_ALLOWED_USERS": "u1, u2",
            "PP_ECHO_QQBOT_ALLOWED_GROUPS": "g1,g2",
            "PP_ECHO_QQBOT_REPLY_MAX_CHARS": "20",
        }
    )

    assert config.enabled is True
    assert config.configured is True
    assert config.allowed_users == ("u1", "u2")
    assert config.allowed_groups == ("g1", "g2")
    assert config.reply_max_chars == 1800

