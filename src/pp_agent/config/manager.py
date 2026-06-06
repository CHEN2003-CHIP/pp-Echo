from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any

from pp_agent.config.patch import changed_paths_from_patch, merge_patch, set_path_value
from pp_agent.config.runtime_overrides import runtime_overrides
from pp_agent.config.schema import (
    ConfigValidationError,
    config_error,
    config_schema,
    field_for_path,
    reload_policy_for_paths,
    validate_project_config_paths,
    validate_runtime_path,
    validate_session_path,
    validate_settings,
)
from pp_agent.session.session_config import SessionConfigStore
from pp_agent.storage.settings import (
    FILE_MEMORY_PROTOCOL_PROMPT,
    SUBAGENT_ORCHESTRATION_PROMPT,
    Settings,
)


class ConfigConflictError(ValueError):
    def __init__(self, *, expected_hash: str, actual_hash: str) -> None:
        super().__init__("Config was changed by another writer")
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


@dataclass(frozen=True)
class ConfigSnapshot:
    settings: Settings
    config_hash: str
    effective_hash: str
    config_version: str
    source_map: dict[str, str]
    reload_policy: str
    pending_effects: list[str]
    project_config: dict[str, Any]
    profile_config: dict[str, Any]
    session_config: dict[str, Any]
    runtime_config: dict[str, Any]
    effective_config: dict[str, Any]
    active_profile: str | None
    profiles: list[str]

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        return {
            "settings": self.settings.model_dump(mode=mode),
            "config_hash": self.config_hash,
            "effective_hash": self.effective_hash,
            "config_version": self.config_version,
            "source_map": dict(self.source_map),
            "reload_policy": self.reload_policy,
            "pending_effects": list(self.pending_effects),
            "project_config": deepcopy(self.project_config),
            "profile_config": deepcopy(self.profile_config),
            "session_config": deepcopy(self.session_config),
            "runtime_config": deepcopy(self.runtime_config),
            "effective_config": deepcopy(self.effective_config),
            "active_profile": self.active_profile,
            "profiles": list(self.profiles),
            "schema": config_schema(),
        }


class ConfigManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.project_dir = self.workspace / ".pp-agent"
        self.config_path = self.project_dir / "config.json"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def get_project_config(self) -> dict[str, Any]:
        return self._read_project_config()

    def get_effective_snapshot(self, *, session_id: str | None = None) -> ConfigSnapshot:
        """
        加锁 → 读取所有配置源 → 按优先级合并 → 生成最终生效配置 → 打包成不可变的快照返回
        配置优先级：项目基础配置 < 激活的 profile < 会话配置 < 运行时覆盖配置
        """
        with self._lock:
            project = self._read_project_config()
            session = SessionConfigStore(self.workspace).load(session_id)
            runtime = runtime_overrides.get(self.workspace)
            active_profile = _active_profile(project, session)

            base_project = _settings_only_config(project)
            profile = _profile_config(project, active_profile)
            session_settings = _settings_only_session(session)
            runtime_settings = _settings_only_runtime(runtime)

            merged = merge_patch(merge_patch(merge_patch(base_project, profile), session_settings), runtime_settings)
           
            settings = self._settings_from_project_data(merged)

            source_map = self._source_map(base_project, profile, session_settings, runtime_settings, active_profile=active_profile)
            project_hash = hash_config(project)
            effective_payload = settings.model_dump(mode="json")
            effective_hash = hash_config(effective_payload)
            changed_paths = list(source_map)
            policy = reload_policy_for_paths(changed_paths)
            pending_effects = _pending_effects(changed_paths)
            return ConfigSnapshot(
                settings=settings.model_copy(deep=True),
                config_hash=project_hash,
                effective_hash=effective_hash,
                config_version=effective_hash[:16],
                source_map=source_map,
                reload_policy=policy,
                pending_effects=pending_effects,
                project_config=project,
                profile_config=profile,
                session_config=session,
                runtime_config=runtime,
                effective_config=merged,
                active_profile=active_profile,
                profiles=sorted(_profiles(project)),
            )

    def patch_project_config(self, patch: dict[str, Any], *, base_hash: str | None = None) -> ConfigSnapshot:
        """安全地给项目配置打补丁 → 校验并发冲突 → 合并修改 → 写入文件 → 返回最新生效快照
（本质：线程安全 + 乐观锁 + 配置热更新）"""
        if not isinstance(patch, dict):
            raise ValueError("Config patch must be a JSON object")
        with self._lock:
            current = self._read_project_config()
            current_hash = hash_config(current)
            self._check_hash(base_hash, current_hash)
            updated = merge_patch(current, patch)
            if not isinstance(updated, dict):
                raise ValueError("Project config must remain a JSON object")
            self._validate_project_config(updated)
            self._write_project_config(updated)
            return self.get_effective_snapshot()

    def set_path(self, path: str, value: Any, *, base_hash: str | None = None) -> ConfigSnapshot:
        """根据「点分隔路径」直接修改配置里的任意字段（比如 api.key），
        自动处理嵌套结构、并发安全、校验、写入，最后返回最新快照。"""
        with self._lock:
            current = self._read_project_config()
            current_hash = hash_config(current)
            self._check_hash(base_hash, current_hash)
            updated = set_path_value(current, path, value)
            self._validate_project_config(updated)
            self._write_project_config(updated)
            return self.get_effective_snapshot()

    def set_session_model(self, session_id: str, model: str) -> ConfigSnapshot:
        SessionConfigStore(self.workspace).set_model(session_id, model)
        return self.get_effective_snapshot(session_id=session_id)

    def set_profile_path(self, profile: str, path: str, value: Any, *, base_hash: str | None = None, session_id: str | None = None) -> ConfigSnapshot:
        profile = _validate_profile_name(profile)
        with self._lock:
            current = self._read_project_config()
            current_hash = hash_config(current)
            self._check_hash(base_hash, current_hash)
            updated = set_path_value(current, f"profiles.{profile}.{path}", value)
            self._validate_project_config(updated)
            self._write_project_config(updated)
            return self.get_effective_snapshot(session_id=session_id)

    def set_active_profile(self, profile: str | None, *, base_hash: str | None = None, session_id: str | None = None) -> ConfigSnapshot:
        profile = _validate_profile_name(profile) if profile else None
        with self._lock:
            current = self._read_project_config()
            current_hash = hash_config(current)
            self._check_hash(base_hash, current_hash)
            updated = set_path_value(current, "active_profile", profile)
            self._validate_project_config(updated)
            self._write_project_config(updated)
            return self.get_effective_snapshot(session_id=session_id)

    def set_runtime_override(self, path: str, value: Any, *, session_id: str | None = None) -> ConfigSnapshot:
        validate_runtime_path(path)
        runtime_overrides.set_path(self.workspace, path, value)
        return self.get_effective_snapshot(session_id=session_id)

    def set_session_path(self, session_id: str, path: str, value: Any) -> ConfigSnapshot:
        validate_session_path(path)
        store = SessionConfigStore(self.workspace)
        updated = set_path_value(store.load(session_id), path, value)
        self._validate_session_config(updated)
        self._validate_effective_data(session_id=session_id, session_config=updated)
        store.save(session_id, updated)
        return self.get_effective_snapshot(session_id=session_id)

    def set_session_profile(self, session_id: str, profile: str | None) -> ConfigSnapshot:
        profile = _validate_profile_name(profile) if profile else None
        project = self._read_project_config()
        if profile and profile not in _profiles(project):
            raise ConfigValidationError([config_error("active_profile", "unknown_profile", f"Unknown profile: {profile}")])
        SessionConfigStore(self.workspace).set_active_profile(session_id, profile)
        return self.get_effective_snapshot(session_id=session_id)

    def reload_policy_for_patch(self, patch: dict[str, Any]) -> str:
        return reload_policy_for_paths(changed_paths_from_patch(patch))

    def schema(self) -> dict[str, Any]:
        return config_schema()

    def _validate_project_config(self, data: dict[str, Any]) -> None:
        """校验项目配置的格式和逻辑，包括 profile 和 active_profile 的有效性、
        项目配置路径的合法性、项目配置的完整性和有效性。"""
        _validate_profile_block(data)
        validate_project_config_paths(data)
        validate_settings(self._settings_from_project_data(_settings_only_config(data)))
        for name, profile in _profiles(data).items():
            try:
                validate_settings(self._settings_from_project_data(merge_patch(_settings_only_config(data), profile)))
            except ConfigValidationError as exc:
                raise ConfigValidationError([
                    {**item, "path": f"profiles.{name}.{item.get('path', '')}".rstrip(".")}
                    for item in exc.errors
                ]) from exc

    def _validate_session_config(self, data: dict[str, Any]) -> None:
        unknown = [path for path in changed_paths_from_patch(_settings_only_session(data)) if field_for_path(path) is None]
        if unknown:
            raise ConfigValidationError.from_paths("Unknown session config path", unknown)
        for path in changed_paths_from_patch(_settings_only_session(data)):
            validate_session_path(path)

    def _validate_effective_session(self, session_id: str) -> None:
        snapshot = self.get_effective_snapshot(session_id=session_id)
        validate_settings(snapshot.settings)

    def _validate_effective_data(self, *, session_id: str | None, session_config: dict[str, Any]) -> None:
        project = self._read_project_config()
        active_profile = _active_profile(project, session_config)
        merged = merge_patch(
            merge_patch(_settings_only_config(project), _profile_config(project, active_profile)),
            _settings_only_session(session_config),
        )
        validate_settings(self._settings_from_project_data(merged))

    def _settings_from_project_data(self, data: dict[str, Any]) -> Settings:
        """
        把纯字典格式的合并配置 → 转换成强类型的 Settings 对象，并完成目录创建、环境变量覆盖、系统提示注入等初始化工作。
        """
        workspace = self.workspace.resolve()
        project_dir = workspace / ".pp-agent"
        project_dir.mkdir(parents=True, exist_ok=True)
        global_dir = Settings._resolve_global_dir(project_dir)
        settings = Settings(workspace=workspace, global_dir=global_dir, project_dir=project_dir)
        settings._apply_environment_overrides()
        settings.apply_project_config_data(data)
        self._apply_system_prompts(settings)
        return settings

    def _apply_system_prompts(self, settings: Settings) -> None:
        agents_md = self.workspace / "AGENTS.md"
        system_md = self.project_dir / "SYSTEM.md"
        if system_md.exists():
            settings.system_prompt = system_md.read_text(encoding="utf-8")
        if agents_md.exists():
            settings.system_prompt += "\n\nWorkspace instructions:\n" + agents_md.read_text(encoding="utf-8")
        if settings.memory.file_memory_enable and settings.memory.file_memory_search_enable:
            settings.system_prompt += "\n\nFile memory protocol:\n" + FILE_MEMORY_PROTOCOL_PROMPT
        settings.system_prompt += "\n\nSubagent orchestration protocol:\n" + SUBAGENT_ORCHESTRATION_PROMPT

    def _read_project_config(self) -> dict[str, Any]:
        """读取并解析项目的 JSON 配置文件，返回字典；如果文件不存在返回空字典；格式非法则抛错。"""
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid project config JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Project config must be a JSON object")
        return data

    def _write_project_config(self, data: dict[str, Any]) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_name(f".config.{os.getpid()}.{int(time.time() * 1000)}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)

    @staticmethod
    def _check_hash(base_hash: str | None, current_hash: str) -> None:
        if base_hash is not None and base_hash != current_hash:
            raise ConfigConflictError(expected_hash=base_hash, actual_hash=current_hash)

    @staticmethod
    def _source_map(
        project: dict[str, Any],
        profile: dict[str, Any],
        session: dict[str, Any],
        runtime: dict[str, Any],
        *,
        active_profile: str | None,
    ) -> dict[str, str]:
        source: dict[str, str] = {}
        layers: list[tuple[str, dict[str, Any]]] = [("project", project)]
        if active_profile:
            layers.append((f"profile:{active_profile}", profile))
        layers.extend([("session", session), ("runtime", runtime)])
        for layer_name, layer in layers:
            for path in changed_paths_from_patch(layer):
                if path:
                    source[path] = layer_name
        if active_profile:
            source["active_profile"] = "session" if session else "project"
        return source


def hash_config(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


_managers: dict[str, ConfigManager] = {}
_manager_lock = RLock()


def get_config_manager(workspace: Path) -> ConfigManager:
    """为每个工作目录（workspace）创建且仅创建一个 ConfigManager 实例"""
    key = str(workspace.resolve())
    with _manager_lock:
        manager = _managers.get(key)
        if manager is None:
            manager = ConfigManager(workspace)
            _managers[key] = manager
        return manager


def _settings_only_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    """ 忽略 debug 项，返回其他项的深拷贝副本 """
    if not runtime:
        return {}
    return {key: value for key, value in runtime.items() if key != "debug"}


def _settings_only_config(config: dict[str, Any]) -> dict[str, Any]:
    """忽略 profiles 和 active_profile 项，返回其他项的深拷贝副本 """
    return {key: deepcopy(value) for key, value in config.items() if key not in {"profiles", "active_profile"}}


def _settings_only_session(session: dict[str, Any]) -> dict[str, Any]:
    """忽略 active_profile 项，返回其他项的深拷贝副本 """
    return {key: deepcopy(value) for key, value in session.items() if key != "active_profile"}


def _profiles(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = project.get("profiles", {})
    if not isinstance(raw, dict):
        return {}
    return {str(name): deepcopy(value) for name, value in raw.items() if isinstance(value, dict)}


def _profile_config(project: dict[str, Any], active_profile: str | None) -> dict[str, Any]:
    """返回激活的 profile 配置，如果没有激活的 profile 返回空字典 """
    if not active_profile:
        return {}
    return _profiles(project).get(active_profile, {})


def _active_profile(project: dict[str, Any], session: dict[str, Any]) -> str | None:
    value = session.get("active_profile", project.get("active_profile"))
    if value is None or value == "":
        return None
    return str(value)


def _validate_profile_block(project: dict[str, Any]) -> None:
    raw_profiles = project.get("profiles", {})
    if raw_profiles is not None and not isinstance(raw_profiles, dict):
        raise ConfigValidationError([config_error("profiles", "type", "profiles must be an object")])
    for name, profile in _profiles(project).items():
        _validate_profile_name(name)
        try:
            validate_project_config_paths(profile)
        except ConfigValidationError as exc:
            raise ConfigValidationError([
                {**item, "path": f"profiles.{name}.{item.get('path', '')}".rstrip(".")}
                for item in exc.errors
            ]) from exc
    active = project.get("active_profile")
    if active not in (None, "") and str(active) not in _profiles(project):
        raise ConfigValidationError([config_error("active_profile", "unknown_profile", f"Unknown profile: {active}")])


def _validate_profile_name(profile: str | None) -> str:
    name = str(profile or "").strip()
    if not name:
        raise ConfigValidationError([config_error("active_profile", "value", "Profile name cannot be empty")])
    if any(char in name for char in ".\\/"):
        raise ConfigValidationError([config_error("active_profile", "value", "Profile name cannot contain path separators or dots")])
    return name


def _pending_effects(paths: list[str]) -> list[str]:
    """检查哪些配置项修改后不能热重载，需要提示用户重启 / 重新加载。"""
    effects: list[str] = []
    for path in paths:
        policy = reload_policy_for_paths([path])
        if policy != "hot":
            effects.append(f"{path}:{policy}")
    return sorted(set(effects))
