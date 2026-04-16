# Contributing to pp-Echo

Thanks for helping improve pp-Echo.

## Project Focus

pp-Echo is a Windows-first coding agent CLI built around three ideas:

- visible planning before execution
- approval-first handling for risky actions
- git-backed rewind for repo state and conversation state

Good contributions usually make one of these loops clearer, safer, faster, or easier to adopt.

## Local Development

### Fastest dev loop

```powershell
set PP_AGENT_API_KEY=your_api_key
set PYTHONPATH=src
python -m pp_agent.cli.main chat
```

### Optional installed CLI

```powershell
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
pp-agent chat
```

If editable install fails on an older environment, use the source-run path first and update your packaging tools later.

## Test Commands

Run the full test suite:

```powershell
python -m pytest
```

Helpful focused commands:

```powershell
python -m pytest tests\smoke
python -m pytest tests\runtime
python -m pytest tests\api
```

## Pull Requests

- Keep each PR focused on one user-visible improvement or one internal refactor.
- Update docs when CLI behavior, startup flow, approvals, checkpointing, subagent delegation rules, or capability discovery changes.
- Prefer adding or updating tests with behavior changes.
- Call out risks, migration notes, and user-facing command changes in the PR description.

## Commit Guidance

- Use clear, descriptive commit messages.
- Mention the user-facing intent, not just the implementation detail.
- Avoid mixing unrelated cleanup into the same commit.

## Demo and README Assets

README visuals live in `docs/assets/`.

When refreshing the landing page:

- keep the hero image aligned with the current product positioning
- refresh screenshots if terminal commands or output layout changes
- update `docs/assets/demo.gif` when the onboarding story changes

Keep README assets easy to refresh and close to the current CLI behavior.

## Release Notes

Release materials live here:

- current release notes: `releases/v0.2.0.md`
- reusable template: `.github/release-template.md`

When preparing a release:

- summarize highlights first
- list CLI-facing changes separately
- note breaking changes or migration steps explicitly
- keep a short `Next Up` section to show project momentum

## Where Contributions Help Most

- onboarding and Quick Start polish
- approvals UX and session visibility
- checkpoint / rewind reliability
- skills, extensions, and MCP discoverability
- demo assets and repository presentation
