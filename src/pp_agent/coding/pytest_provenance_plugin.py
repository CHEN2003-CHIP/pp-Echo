from __future__ import annotations

from pathlib import Path

from pp_agent.coding.pytest_provenance import write_pytest_provenance_attestation


def pytest_addoption(parser) -> None:
    group = parser.getgroup("pp-echo-validation-provenance")
    group.addoption("--pp-echo-pytest-provenance-file", action="store", default=None)
    group.addoption("--pp-echo-pytest-provenance-nonce", action="store", default=None)
    group.addoption("--pp-echo-pytest-logical-command-digest", action="store", default=None)


def pytest_sessionfinish(session, exitstatus) -> None:
    config = session.config
    artifact = config.getoption("--pp-echo-pytest-provenance-file")
    nonce = config.getoption("--pp-echo-pytest-provenance-nonce")
    logical_digest = config.getoption("--pp-echo-pytest-logical-command-digest")
    if not artifact or not nonce or not logical_digest:
        return
    write_pytest_provenance_attestation(
        artifact_path=Path(str(artifact)),
        nonce=str(nonce),
        logical_command_digest=str(logical_digest),
        pytest_exit_status=int(exitstatus),
    )
