from __future__ import annotations

import json
from pathlib import Path

from pp_agent.domain import ChatMessage, TextPart
from pp_agent.learning import LearningCurator, LearningStore
from pp_agent.runtime.lifecycle import LEARNING_ITEM_APPLIED
from pp_agent.storage.settings import Settings


def learning_status_payload(workspace: Path) -> dict[str, object]:
    settings = Settings.load(workspace)
    store = LearningStore(settings.project_dir / "learning")
    skill_count = len(list((settings.project_dir / "skills").glob("*/SKILL.md")))
    return store.summary(project_skill_count=skill_count).model_dump(mode="json")


def learning_review_payload(workspace: Path) -> list[dict[str, object]]:
    settings = Settings.load(workspace)
    store = LearningStore(settings.project_dir / "learning")
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "confidence": item.confidence,
            "suggested_target": item.suggested_target,
            "status": item.status,
            "title": item.title,
        }
        for item in store.list_candidates(status="pending")
    ]


def learning_show_payload(workspace: Path, candidate_id: str) -> dict[str, object] | None:
    settings = Settings.load(workspace)
    store = LearningStore(settings.project_dir / "learning")
    candidate = store.get(candidate_id)
    if candidate is None:
        return None
    return candidate.model_dump(mode="json")


def reject_learning_candidate(workspace: Path, candidate_id: str) -> bool:
    settings = Settings.load(workspace)
    store = LearningStore(settings.project_dir / "learning")
    candidate = store.get(candidate_id)
    if candidate is None:
        return False
    store.update(candidate.mark_rejected())
    return True


def apply_learning_candidate(agent, workspace: Path, candidate_id: str, target: str) -> dict[str, object]:
    settings = Settings.load(workspace)
    store = LearningStore(settings.project_dir / "learning")
    candidate = store.get(candidate_id)
    if candidate is None:
        return {"ok": False, "error": f"Unknown learning candidate: {candidate_id}"}
    if candidate.status == "applied":
        return {"ok": False, "error": f"Learning candidate already applied: {candidate_id}"}
    curator = LearningCurator(workspace=workspace, settings=settings.learning)
    if target == "memory":
        entry = curator.memory_entry(candidate)
        store.append_project_memory(entry)
        path = str(store.memory_path)
    elif target == "skill":
        path_obj = curator.skill_path_for(candidate)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        skill_name = path_obj.parent.name
        path_obj.write_text(curator.skill_document(candidate, name=skill_name), encoding="utf-8")
        path = str(path_obj)
    else:
        return {"ok": False, "error": "Usage: /learn apply <id> memory|skill"}
    updated = candidate.mark_applied()
    store.update(updated)
    _emit_applied_event(agent, candidate_id=candidate_id, target=target, path=path)
    return {"ok": True, "id": candidate_id, "target": target, "path": path}


def consolidate_project_memory(agent, workspace: Path) -> dict[str, object]:
    settings = Settings.load(workspace)
    store = LearningStore(settings.project_dir / "learning")
    current = store.read_project_memory()
    curator = LearningCurator(workspace=workspace, settings=settings.learning)
    consolidated = _llm_consolidated_memory(agent, current, settings.learning.project_memory_char_limit)
    if consolidated is None:
        consolidated = curator.consolidated_memory(current, [])
    store.replace_project_memory(consolidated)
    return {"ok": True, "path": str(store.memory_path), "chars": len(consolidated)}


def dumps_payload(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _emit_applied_event(agent, *, candidate_id: str, target: str, path: str) -> None:
    event_factory = getattr(agent, "_event", None)
    emitter = getattr(agent, "_emit", None)
    if event_factory is None or emitter is None:
        return
    list(
        emitter(
            event_factory(
                LEARNING_ITEM_APPLIED,
                details={"candidate_id": candidate_id, "target": target, "path": path},
            )
        )
    )


def _llm_consolidated_memory(agent, current: str, limit: int) -> str | None:
    if len(current) <= limit:
        return current.strip()
    llm_client = getattr(agent, "llm_client", None)
    if llm_client is None:
        return None
    prompt = (
        "Consolidate this pp-Echo project memory into durable, non-duplicated bullets. "
        "Preserve project conventions, user preferences, reusable workflows, and pitfalls. "
        "Remove temporary logs and one-off details. "
        f"Keep the result under {limit} characters. Return only markdown bullets.\n\n"
        f"{current}"
    )
    messages = [
        ChatMessage(role="system", content=[TextPart(text="You curate concise project memory for a coding agent.")], timestamp=0),
        ChatMessage(role="user", content=[TextPart(text=prompt)], timestamp=0),
    ]
    try:
        text = "".join(str(event.get("text") or "") for event in llm_client.stream_chat(messages, tools=None)).strip()
    except Exception:  # noqa: BLE001
        return None
    if not text:
        return None
    return text[:limit].strip()
