from __future__ import annotations


class QQBotError(Exception):
    """Base error for QQ Bot integration failures."""


class QQBotConfigError(QQBotError):
    """Raised when QQ Bot configuration is incomplete or invalid."""


class QQBotAPIError(QQBotError):
    """Raised when the official QQ Bot API returns an error."""

