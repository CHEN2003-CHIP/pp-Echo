from __future__ import annotations

from pathlib import Path

from pp_agent import api
from pp_agent.prompts.loader import load_prompt_templates
from pp_agent.skills.loader import load_skills


class FakeAgent:
    def __init__(self) -> None:
        self.session_id = 'session-1'
        self.state = type('State', (), {
            'pending_plan_token': None,
            'pending_tool_calls': [],
            'queued_messages': [],
            'messages': [],
        })()

    def prompt(self, _prompt: str):
        return []


class FakeEvent:
    def model_dump(self, mode: str = 'json') -> dict:
        return {'type': 'agent_end'}


class FakeRuntimeAgent(FakeAgent):
    def prompt(self, _prompt: str):
        return [FakeEvent()]


def test_api_run_returns_payload(monkeypatch, tmp_path: Path) -> None:
    from pp_agent.cli import _legacy_main_impl as legacy

    monkeypatch.setattr(legacy, 'build_agent', lambda workspace, session_id=None: FakeRuntimeAgent())
    payload = api.run('hello', workspace=tmp_path, json_mode=True)

    assert payload['session_id'] == 'session-1'
    assert payload['event_count'] == 1


def test_prompt_loader_prefers_project_over_user_and_builtin(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    user_root = tmp_path / 'user'
    (workspace / '.pp-agent' / 'prompts').mkdir(parents=True)
    (user_root / 'prompts').mkdir(parents=True)
    (workspace / '.pp-agent' / 'prompts' / 'system.md').write_text('project', encoding='utf-8')
    (user_root / 'prompts' / 'system.md').write_text('user', encoding='utf-8')

    templates = load_prompt_templates(workspace, user_root)

    assert templates['system'] == 'project'


def test_skill_loader_requires_frontmatter_and_prefers_project(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    user_root = tmp_path / 'user'
    project_skill = workspace / '.pp-agent' / 'skills' / 'demo' / 'SKILL.md'
    user_skill = user_root / 'skills' / 'demo' / 'SKILL.md'
    project_skill.parent.mkdir(parents=True)
    user_skill.parent.mkdir(parents=True)
    project_skill.write_text('---\nname: demo\ndescription: project skill\n---\nbody', encoding='utf-8')
    user_skill.write_text('---\nname: demo\ndescription: user skill\n---\nbody', encoding='utf-8')

    skills = load_skills(workspace, user_root)

    assert skills['demo'].description == 'project skill'

