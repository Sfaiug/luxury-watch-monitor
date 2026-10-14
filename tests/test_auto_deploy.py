"""deploy/auto_deploy.sh follows main: against a local repository, with pip and systemctl replaced by recorders."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy" / "auto_deploy.sh"


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


class Server:
    """A checkout of a local main, as the server has it, and a log of what a deploy ran."""

    def __init__(self, tmp_path):
        self.origin = tmp_path / "origin"
        self.checkout = tmp_path / "checkout"
        self.log = tmp_path / "ran.log"
        self.bin = tmp_path / "bin"

        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        (self.origin / "deploy").mkdir()
        (self.origin / "deploy" / "auto_deploy.sh").write_text(SCRIPT.read_text())
        (self.origin / "deploy" / "auto_deploy.sh").chmod(0o755)
        self.push("requirements.txt", "aiohttp\n")
        git(tmp_path, "clone", "-q", str(self.origin), str(self.checkout))

        self.recorder(
            self.checkout / "venv" / "bin" / "pip", commands='cat "$4" > /dev/null'
        )
        self.recorder(self.bin / "sudo")

    def recorder(self, path, exit_code=0, commands=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'#!/bin/sh\nset -e\necho "{path.name} $*" >> "{self.log}"\n'
            f'{commands}\nexit {exit_code}\n'
        )
        path.chmod(0o755)

    def push(self, name, content):
        (self.origin / name).write_text(content)
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", name)

    def deploy(self):
        """Run one timer tick; what it ran, in order."""
        self.log.write_text("")
        result = subprocess.run(
            [str(self.checkout / "deploy" / "auto_deploy.sh")],
            env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
        )
        return result.returncode, self.log.read_text().splitlines()


RESTART = "sudo -n systemctl restart extras-luxury-watch-monitor"
INSTALL = "pip install --quiet -r /dev/stdin"


@pytest.fixture
def server(tmp_path):
    return Server(tmp_path)


def test_a_new_main_is_checked_out_installed_and_restarted_once(server):
    assert server.deploy() == (0, [INSTALL, RESTART])
    assert server.deploy() == (0, [])

    server.push("monitor.py", "print('new')\n")

    assert server.deploy() == (0, [INSTALL, RESTART])
    assert (server.checkout / "monitor.py").read_text() == "print('new')\n"
    assert server.deploy() == (0, [])


def test_a_failed_restart_is_tried_again(server):
    server.recorder(server.bin / "sudo", exit_code=1)
    code, ran = server.deploy()
    assert code != 0 and ran == [INSTALL, RESTART]

    server.recorder(server.bin / "sudo")
    assert server.deploy() == (0, [INSTALL, RESTART])
    assert server.deploy() == (0, [])


def test_requirements_first_leaves_old_code_on_install_failure_and_retries(server):
    assert server.deploy() == (0, [INSTALL, RESTART])
    deployed = (server.checkout / ".git" / "deployed").read_text()
    old_requirements = (server.checkout / "requirements.txt").read_text()
    requirements = "aiohttp\ncurl_cffi\n"
    server.push("requirements.txt", requirements)
    server.push("monitor.py", "print('new')\n")

    installed = server.checkout / "installed.txt"
    head_at_install = server.checkout / "head-at-install.txt"
    fail_install = server.checkout / "fail-install"
    fail_install.touch()
    server.recorder(
        server.checkout / "venv" / "bin" / "pip",
        commands=(
            f'cat "$4" > "{installed}"\n'
            f'git rev-parse HEAD > "{head_at_install}"\n'
            f'test ! -e "{fail_install}"'
        ),
    )

    code, ran = server.deploy()
    assert code != 0 and ran == [INSTALL]
    assert installed.read_text() == requirements
    assert head_at_install.read_text() == deployed
    assert (server.checkout / "requirements.txt").read_text() == old_requirements
    assert not (server.checkout / "monitor.py").exists()
    assert (server.checkout / ".git" / "deployed").read_text() == deployed

    fail_install.unlink()
    assert server.deploy() == (0, [INSTALL, RESTART])
    assert installed.read_text() == requirements
    assert head_at_install.read_text() == deployed
    assert (server.checkout / "requirements.txt").read_text() == requirements
    assert (server.checkout / "monitor.py").read_text() == "print('new')\n"
    assert (server.checkout / ".git" / "deployed").read_text() != deployed
    assert server.deploy() == (0, [])


def test_files_the_monitor_writes_are_left_alone(server):
    (server.checkout / "seen_watches.json").write_text("{}")

    server.deploy()
    server.push("monitor.py", "print('new')\n")
    server.deploy()

    assert (server.checkout / "seen_watches.json").read_text() == "{}"
