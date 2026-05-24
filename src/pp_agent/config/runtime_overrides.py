# 导入未来版本的注解语法兼容（让类型注解写法更灵活）
from __future__ import annotations

# 深拷贝：复制字典/对象时，会完整复制所有嵌套内容，不会影响原数据
from copy import deepcopy
# 路径处理工具类：用于处理文件/文件夹路径
from pathlib import Path
# 可重入锁：多线程环境下保证数据安全，同一个线程可以多次加锁
from threading import RLock
# 类型注解：Any 表示任意类型
from typing import Any

# 导入一个工具函数：根据路径字符串修改字典里的嵌套值（比如 "a.b.c" → 改 dict["a"]["b"]["c"]）
from pp_agent.config.patch import set_path_value


class RuntimeOverrideStore:
    """
    【类功能】进程级别的运行时配置覆盖存储器
    用途：给调试接口（/debug）、网页调试控制器 使用的临时配置覆盖
    特点：只在当前进程内存里生效，重启后消失
    """

    def __init__(self) -> None:
        # 线程锁：保证多线程同时读写时数据不会错乱
        self._lock = RLock()
        # 核心存储结构：{工作区路径字符串: {配置键值对}}
        # 按不同工作区（workspace）分开存储配置覆盖
        self._by_workspace: dict[str, dict[str, Any]] = {}

    def get(self, workspace: Path) -> dict[str, Any]:
        """
        获取某个工作区的所有运行时覆盖配置
        :param workspace: 工作区路径（文件夹）
        :return: 该工作区的所有配置（深拷贝，外部修改不会影响内部存储）
        """
        # 加锁：保证线程安全读取
        with self._lock:
            # 根据工作区路径取 key，拿到对应配置；没有就返回空字典
            # 深拷贝：防止外部拿到引用后篡改内部数据
            return deepcopy(self._by_workspace.get(_key(workspace), {}))

    def set_path(self, workspace: Path, path: str, value: Any) -> dict[str, Any]:
        """
        给某个工作区的【嵌套配置路径】设置值
        例：path="llm.model.temperature"，就会自动修改对应层级的配置
        :param workspace: 工作区路径
        :param path: 配置路径字符串（如 a.b.c）
        :param value: 要设置的值
        :return: 设置后的完整配置（深拷贝）
        """
        with self._lock:
            # 把工作区路径转成字符串 key
            key = _key(workspace)
            # 获取该工作区当前的所有配置，没有则为空字典
            current = self._by_workstore.get(key, {})
            # 调用工具函数：根据路径修改嵌套配置
            updated = set_path_value(current, path, value)
            # 把更新后的配置存回去
            self._by_workspace[key] = updated
            # 返回深拷贝后的最新配置
            return deepcopy(updated)

    def clear(self, workspace: Path) -> None:
        """清空某个工作区的所有运行时覆盖配置"""
        with self._lock:
            # 从字典里删除该工作区的配置，不存在则忽略
            self._by_workspace.pop(_key(workspace), None)


def _key(workspace: Path) -> str:
    """
    工具函数：把 Path 路径转成标准字符串 key
    作用：统一路径格式（绝对路径），避免相同路径不同写法被当成不同 key
    """
    # 解析为绝对路径并转字符串
    return str(workspace.resolve())


# 【全局单例】整个程序共用一个运行时配置覆盖存储器
runtime_overrides = RuntimeOverrideStore()