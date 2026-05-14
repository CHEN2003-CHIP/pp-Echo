from importlib import import_module

__all__ = [
    "LearningCandidate",
    "LearningCurator",
    "LearningExtractor",
    "LearningRuntime",
    "LearningSettings",
    "LearningStore",
    "BootstrapMemoryManager",
    "FileMemoryWriter",
]


def __getattr__(name: str):
    if name in {"LearningCandidate", "LearningSettings"}:
        module = import_module("pp_agent.learning.models")
        return getattr(module, name)
    if name == "LearningCurator":
        module = import_module("pp_agent.learning.curator")
        return getattr(module, name)
    if name == "LearningExtractor":
        module = import_module("pp_agent.learning.extractor")
        return getattr(module, name)
    if name == "LearningRuntime":
        module = import_module("pp_agent.learning.runtime")
        return getattr(module, name)
    if name == "LearningStore":
        module = import_module("pp_agent.learning.store")
        return getattr(module, name)
    if name == "BootstrapMemoryManager":
        module = import_module("pp_agent.learning.bootstrap_memory")
        return getattr(module, name)
    if name == "FileMemoryWriter":
        module = import_module("pp_agent.learning.file_memory_writer")
        return getattr(module, name)
    raise AttributeError(name)
