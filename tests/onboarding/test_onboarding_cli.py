import json
import subprocess
import sys


def test_cli_onboard_json_outputs_valid_json(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pp_agent.cli.main", "onboard", "--workspace", str(tmp_path), "--json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    payload = json.loads(result.stdout)
    assert payload["workspace"] == str(tmp_path.resolve())
    assert isinstance(payload["checks"], list)
