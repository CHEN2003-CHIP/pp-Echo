from __future__ import annotations

from typing import Iterable, Optional

from pp_agent.subagents.specs import SubAgentSpec, default_subagent_specs


class SubAgentCatalog:
    """
    子 Agent 规格目录。

    SubAgentCatalog 负责管理可用的 SubAgentSpec，
    例如 researcher、reviewer、code_reader、patch_worker 等子 Agent 类型。

    它只保存和查询规格，不负责真正运行子 Agent。
    真正的运行流程由 SubAgentManager 完成。

    主要职责：
    - 注册和保存 SubAgentSpec；
    - 根据 spec_name 查询子 Agent 规格；
    - 管理默认子 Agent 配置；
    - 校验 spec_name、allowed_tools、return_format、max_turns 等字段；
    - 为 SpawnSubagentTool / SubAgentManager 提供子 Agent 创建依据。

    简单说：
    Catalog 描述“有哪些子 Agent 可以用”；
    Manager 负责“怎么创建并运行这个子 Agent”。
    """
    

    def __init__(self, specs: Optional[dict[str, SubAgentSpec]] = None) -> None:
        seed = specs or default_subagent_specs()
        self._specs: dict[str, SubAgentSpec] = {}
        for spec in seed.values():
            self.register(spec)

    def register(self, spec: SubAgentSpec, *, replace: bool = False) -> None:
        if not replace and spec.name in self._specs:
            raise ValueError(f"Subagent '{spec.name}' is already registered.")
        self._specs[spec.name] = spec.model_copy(deep=True)

    def get(self, name: str) -> Optional[SubAgentSpec]:
        spec = self._specs.get(name)
        return spec.model_copy(deep=True) if spec is not None else None

    def list(self) -> list[SubAgentSpec]:
        return [spec.model_copy(deep=True) for spec in self._specs.values()]

    def names(self) -> list[str]:
        return list(self._specs)

    def replace_all(self, specs: Iterable[SubAgentSpec]) -> None:
        self._specs = {}
        for spec in specs:
            self.register(spec)
