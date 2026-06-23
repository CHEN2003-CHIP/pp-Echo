from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pp_agent.bots.models import BotConfig, default_qq_main_config
from pp_agent.bots.paths import ensure_bot_dirs, get_bot_config_path, get_bot_index_path

SECRET_KEYS = {"secret", "app_secret", "token", "access_token", "password", "private_key"}


class BotRegistry:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    def ensure_default(self) -> BotConfig:
        configs = self._load_configs()
        if "qq-main" not in configs:
            configs["qq-main"] = default_qq_main_config()
            self._save_configs(configs)
        else:
            self._write_config_snapshot(configs["qq-main"])
        return configs["qq-main"]

    def list_configs(self, *, readonly: bool = False) -> list[BotConfig]:
        if not readonly:
            self.ensure_default()
        return list(self._load_configs().values())

    def get_config(self, bot_id: str) -> BotConfig:
        self.ensure_default()
        configs = self._load_configs()
        if bot_id not in configs:
            raise KeyError(bot_id)
        return configs[bot_id]

    def update_config(self, bot_id: str, patch: dict[str, Any]) -> BotConfig:
        configs = self._load_configs()
        if bot_id not in configs:
            raise KeyError(bot_id)
        base = configs[bot_id].model_dump(mode="json")
        merged = _deep_merge(base, _strip_secrets(patch))
        updated = BotConfig.model_validate(merged)
        configs[bot_id] = updated
        self._save_configs(configs)
        return updated

    def enable(self, bot_id: str) -> BotConfig:
        return self.update_config(bot_id, {"enabled": True})

    def disable(self, bot_id: str) -> BotConfig:
        return self.update_config(bot_id, {"enabled": False})

    def _load_configs(self) -> dict[str, BotConfig]:
        path = get_bot_index_path(self.workspace)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        raw_items = payload.get("bots") if isinstance(payload, dict) else []
        if isinstance(raw_items, dict):
            raw_items = list(raw_items.values())
        configs: dict[str, BotConfig] = {}
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                try:
                    config = BotConfig.model_validate(_strip_secrets(item))
                except Exception:
                    continue
                configs[config.id] = config
        return configs

    def _save_configs(self, configs: dict[str, BotConfig]) -> None:
        index_path = get_bot_index_path(self.workspace)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "bots": [config.model_dump(mode="json", exclude_none=True) for config in configs.values()],
        }
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for config in configs.values():
            self._write_config_snapshot(config)

    def _write_config_snapshot(self, config: BotConfig) -> None:
        ensure_bot_dirs(self.workspace, config.platform, config.id)
        path = get_bot_config_path(self.workspace, config.platform, config.id)
        path.write_text(json.dumps(config.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(secret_key in lowered for secret_key in SECRET_KEYS):
                continue
            safe[key] = _strip_secrets(item)
        return safe
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value
