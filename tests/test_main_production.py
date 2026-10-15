"""Tests for production entrypoint startup behavior."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import main_production
from config import APP_CONFIG


@pytest.mark.parametrize(
    "webhook_url, bot_channel_id, shared_channel_id",
    [
        ("https://discord.com/api/webhooks/test/token", "", ""),
        ("", "123456789", ""),
        ("", "", "123456789"),
        ("", "", ""),
    ],
)
def test_validate_environment_webhook_or_bot_channel(
    monkeypatch, tmp_path, test_site_config, webhook_url, bot_channel_id, shared_channel_id
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_WEBHOOK_URL", webhook_url)
    monkeypatch.setenv("TEST_CHANNEL_ID", bot_channel_id)
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", shared_channel_id)
    monkeypatch.setattr(main_production, "SITE_CONFIGS", {"test_site": test_site_config})

    is_valid, messages = main_production.validate_environment()

    assert is_valid
    if webhook_url or bot_channel_id or shared_channel_id:
        assert messages == []
    else:
        assert len(messages) == 1
        assert messages[0].startswith("⚠️")
        assert "Test Site" in messages[0]
        assert "TEST_WEBHOOK_URL" in messages[0]
        assert "channel" in messages[0].lower()


def test_validate_environment_bot_channel_keeps_write_permission_error(
    monkeypatch, tmp_path, test_site_config
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_WEBHOOK_URL", "")
    monkeypatch.setenv("TEST_CHANNEL_ID", "123456789")
    monkeypatch.setattr(main_production, "SITE_CONFIGS", {"test_site": test_site_config})

    def refuse_write(*args, **kwargs):
        raise PermissionError("read-only directory")

    monkeypatch.setattr(Path, "write_text", refuse_write)

    is_valid, messages = main_production.validate_environment()

    assert not is_valid
    assert any("No write permission" in message for message in messages)


def test_main_production_keeps_persisted_history_path_from_environment(temp_dir):
    repo_root = Path(__file__).resolve().parents[1]
    (temp_dir / ".env").write_text(
        (repo_root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    seen_file = temp_dir / "data" / "seen_watches.json"
    seen_file.parent.mkdir()
    seed = {"shop": ["old"], "filter:111": ["offer1"]}
    seen_file.write_text(json.dumps(seed), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root),
        "SEEN_WATCHES_FILE": str(seen_file),
    }

    subprocess.run(
        [sys.executable, "-c", """
import logging, sys
from pathlib import Path
import main_production
from persistence import PersistenceManager
manager = PersistenceManager(logging.getLogger(__name__))
assert manager.seen_items_file == Path(sys.argv[1]), "The template overrode the persisted path"
state = manager.load_seen_items()
assert {key: list(ids) for key, ids in state.items()} == {"shop": ["old"], "filter:111": ["offer1"]}
state["shop"].add("new")
state["filter:111"].add("offer2")
manager.save_seen_items(state)
fresh = PersistenceManager(manager.logger)
assert fresh.load_seen_items() == state
fresh.seen_items_file.write_text('{"shop": [', encoding="utf-8")
assert fresh.load_seen_items() == state
""", str(seen_file)],
        cwd=temp_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )


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
