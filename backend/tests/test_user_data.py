"""Checks infra/minecraft/user_data.sh, including its embedded mc-sync-access script, with no AWS or Docker."""
import base64
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "minecraft" / "user_data.sh"
USER_DATA = SCRIPT.read_text()

def number(pattern):
    return int(re.search(pattern, USER_DATA).group(1))

def test_is_valid_bash():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

def test_fits_ec2_user_data_limit():
    assert len(base64.b64encode(USER_DATA.encode())) < 16 * 1024

def test_shutdown_timeouts_leave_time_to_save():
    assert (number(r"STOP_DURATION=(\d+)") < number(r"--stop-timeout (\d+)") < number(r"TimeoutStopSec=(\d+)"))

def test_no_docker_stop_on_shutdown():
    # It would mark the container as manually stopped, so --restart unless-stopped wouldn't bring it back.
    assert "ExecStop" not in USER_DATA
    assert "--restart unless-stopped" in USER_DATA

def test_rerun_replaces_container_gracefully():
    assert "docker stop -t 120 mc" in USER_DATA
    assert "docker rm -f" not in USER_DATA

def test_whitelist_is_on_when_container_starts():
    run = USER_DATA[USER_DATA.index("docker run"):]
    assert "ENABLE_WHITELIST=TRUE" in run and "ENFORCE_WHITELIST=TRUE" in run

def test_sync_runs_on_every_boot_without_blocking_it():
    assert "systemctl enable mc-sync-access.service" in USER_DATA
    assert "Type=simple" in USER_DATA

# --- mc-sync-access, run against stub docker and aws commands ---

SYNC_SOURCE = re.search(r"<<'SYNC_ACCESS'\n(.*?)\nSYNC_ACCESS\n", USER_DATA, re.S).group(1)

FAKE_DOCKER = """#!/bin/sh
# docker exec mc <command...>
shift 2
echo "$*" >> "$STUB_DIR/calls"
case "$1" in
  cat) cat "$STUB_DIR/whitelist.json" ;;
  rcon-cli)
    if [ "$2" = "list" ] && [ -f "$STUB_DIR/not_ready" ]; then exit 1; fi
    echo ok ;;
esac
"""

FAKE_AWS = """#!/bin/sh
case "$STUB_PARAMETER" in
  MISSING) echo "An error occurred (ParameterNotFound)" >&2; exit 254 ;;
  DENIED) echo "An error occurred (AccessDenied)" >&2; exit 254 ;;
  *) echo "$STUB_PARAMETER" ;;
esac
"""

@pytest.fixture
def run_sync(tmp_path):
    """Runs the script with stubs on PATH; metadata is replaced so nothing leaves the machine."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"docker": FAKE_DOCKER, "aws": FAKE_AWS}.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    script = tmp_path / "sync.py"
    source = SYNC_SOURCE.replace('LOCK_FILE = "/run/mc-sync-access.lock"', f'LOCK_FILE = "{tmp_path}/lock"')
    source = source.replace("READY_TIMEOUT = 900", "READY_TIMEOUT = 0")
    source = source.replace('if __name__ == "__main__":', 'metadata = lambda path: "server-1" if "ServerId" in path else "us-east-1"\n\nif __name__ == "__main__":')
    script.write_text(source)

    def run(parameter, current=()):
        (tmp_path / "whitelist.json").write_text(json.dumps([{"uuid": "u", "name": n} for n in current]))
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_DIR": str(tmp_path),
               "STUB_PARAMETER": parameter if isinstance(parameter, str) else json.dumps(parameter)}
        result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
        calls_file = tmp_path / "calls"
        calls = [c for c in calls_file.read_text().splitlines() if c != "rcon-cli list"] if calls_file.exists() else []
        if calls_file.exists():
            calls_file.unlink()
        return result, calls

    run.dir = tmp_path
    return run

def test_public_turns_whitelist_off(run_sync):
    result, calls = run_sync({"mode": "public", "players": ["Steve"]})
    assert result.returncode == 0, result.stderr
    assert calls == ["rcon-cli whitelist off"]

def test_unconfigured_server_is_public(run_sync):
    result, calls = run_sync("MISSING")
    assert result.returncode == 0, result.stderr
    assert calls == ["rcon-cli whitelist off"]

def test_unreadable_settings_leave_whitelist_on(run_sync):
    result, calls = run_sync("DENIED")
    assert result.returncode != 0
    assert calls == []

def test_whitelist_adds_removes_and_kicks(run_sync):
    result, calls = run_sync({"mode": "whitelist", "players": ["Steve", "NewPlayer"]}, current=["steve", "OldPlayer"])
    assert result.returncode == 0, result.stderr
    assert calls == ["cat /data/whitelist.json", "rcon-cli whitelist remove OldPlayer",
                     "rcon-cli whitelist add NewPlayer", "rcon-cli whitelist on", "rcon-cli whitelist reload",
                     "rcon-cli kick OldPlayer"]

def test_empty_whitelist_admits_nobody(run_sync):
    result, calls = run_sync({"mode": "whitelist", "players": []}, current=["Steve"])
    assert result.returncode == 0, result.stderr
    assert "rcon-cli whitelist remove Steve" in calls
    assert "rcon-cli whitelist on" in calls

def test_invalid_names_in_parameter_are_ignored(run_sync):
    result, calls = run_sync({"mode": "whitelist", "players": ["a;reboot", "$(x)", "ok_name"]})
    assert result.returncode == 0, result.stderr
    added = [c for c in calls if " add " in c]
    assert added == ["rcon-cli whitelist add ok_name"]

def test_gives_up_when_server_never_ready(run_sync):
    (run_sync.dir / "not_ready").write_text("")
    result, calls = run_sync({"mode": "public", "players": []})
    assert result.returncode != 0
    assert calls == []
