"""Tests for production entrypoint startup behavior."""

import os
import subprocess
import sys
from pathlib import Path


def test_main_production_loads_cwd_dotenv_before_config_import(temp_dir):
    (temp_dir / ".env").write_text(
        "\n".join(
            [
                "CHECK_INTERVAL_SECONDS=181",
                "ENABLE_MUV_ACTIONS=true",
                "MUV_ACTION_LABEL=E2E Label",
            ]
        ),
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)
    env_keys = (
        "CHECK_INTERVAL_SECONDS",
        "ENABLE_MUV_ACTIONS",
        "MUV_ACTION_LABEL",
    )
    for key in env_keys:
        env.pop(key, None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import main_production\n"
                "from config import APP_CONFIG\n"
                "print(APP_CONFIG.check_interval_seconds)\n"
                "print(APP_CONFIG.enable_muv_actions)\n"
                "print(APP_CONFIG.muv_action_label)\n"
            ),
        ],
        cwd=temp_dir,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip().splitlines()[-3:] == [
        "181",
        "True",
        "E2E Label",
    ]
