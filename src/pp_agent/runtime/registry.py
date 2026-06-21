from __future__ import annotations

from pp_agent.runtime.profile import RuntimeProfile, default_runtime_profile


class RuntimeRegistry:
    """
    RuntimeRegistry stores RuntimeProfile declarations only.

    It deliberately does not instantiate or dispatch runtimes; AgentRuntime remains the
    execution path for pp_echo_native, and future runtimes can be added behind a separate
    adapter without changing this profile table.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, RuntimeProfile] = {}
        self.register(default_runtime_profile())

    def register(self, profile: RuntimeProfile) -> None:
        self._profiles[profile.id] = profile

    def get(self, runtime_id: str) -> RuntimeProfile:
        return self._profiles[runtime_id]

    def list(self) -> list[RuntimeProfile]:
        return list(self._profiles.values())

    def get_default(self) -> RuntimeProfile:
        return self.get("pp_echo_native")


DEFAULT_RUNTIME_REGISTRY = RuntimeRegistry()


def register(profile: RuntimeProfile) -> None:
    DEFAULT_RUNTIME_REGISTRY.register(profile)


def get(runtime_id: str) -> RuntimeProfile:
    return DEFAULT_RUNTIME_REGISTRY.get(runtime_id)


def list() -> list[RuntimeProfile]:  # noqa: A001
    return DEFAULT_RUNTIME_REGISTRY.list()


def get_default() -> RuntimeProfile:
    return DEFAULT_RUNTIME_REGISTRY.get_default()
