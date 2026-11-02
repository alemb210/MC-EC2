#!/bin/bash
# Sets up a Minecraft server. Runs on first boot from the launch template, and can be rerun through
# SSM to update an existing server (see infra/README.md), so every step must be safe to repeat.
set -euxo pipefail

dnf install -y docker
command -v aws >/dev/null || dnf install -y awscli-2

# Saving happens during instance shutdown: Docker gives the container --stop-timeout to exit, and the
# itzg image gives Minecraft STOP_DURATION to save. Keep STOP_DURATION < --stop-timeout < TimeoutStopSec.
# Don't add a "docker stop" shutdown hook: it would mark the container as manually stopped, and
# --restart unless-stopped would no longer bring it back on the next boot.
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/mc-shutdown.conf <<'EOF'
[Service]
TimeoutStopSec=150
EOF
systemctl daemon-reload
systemctl enable --now docker
usermod -aG docker ec2-user

cat > /usr/local/bin/mc-sync-access <<'SYNC_ACCESS'
#!/usr/bin/python3
"""Makes the Minecraft whitelist match this server's saved access settings.

The API saves {"mode": "public" | "whitelist", "players": [...]} in Parameter Store. This runs on
every boot, and through the mc-ec2-sync-access SSM document when the settings change."""
import fcntl
import json
import re
import subprocess
import sys
import time
import urllib.request

CONTAINER = "mc"
METADATA = "http://169.254.169.254/latest"
PLAYER_NAME = re.compile(r"[A-Za-z0-9_]{3,16}")
READY_TIMEOUT = 900
LOCK_FILE = "/run/mc-sync-access.lock"


def metadata(path):
    token_request = urllib.request.Request(f"{METADATA}/api/token", method="PUT",
                                           headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    with urllib.request.urlopen(token_request, timeout=5) as response:
        token = response.read().decode()
    request = urllib.request.Request(f"{METADATA}/meta-data/{path}", headers={"X-aws-ec2-metadata-token": token})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode()


def load_settings():
    server_id = metadata("tags/instance/ServerId")
    region = metadata("placement/region")
    result = subprocess.run(
        ["aws", "ssm", "get-parameter", "--region", region, "--name", f"/mc-ec2/servers/{server_id}/access",
         "--query", "Parameter.Value", "--output", "text"], capture_output=True, text=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    # A server nobody has configured is public. Any other failure must not open a whitelisted server.
    if "ParameterNotFound" in result.stderr:
        return {"mode": "public", "players": []}
    raise RuntimeError(f"Could not read access settings: {result.stderr}")


def docker_exec(*args):
    return subprocess.run(["docker", "exec", CONTAINER, *args], check=True, capture_output=True, text=True,
                          timeout=30).stdout


def rcon(*args):
    output = docker_exec("rcon-cli", *args)
    print(f"{' '.join(args)}: {output.strip()}")


def wait_until_ready():
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        try:
            docker_exec("rcon-cli", "list")
            return
        except (subprocess.SubprocessError, OSError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def sync(settings):
    if settings["mode"] == "public":
        rcon("whitelist", "off")
        return
    wanted = {p.lower(): p for p in settings["players"] if PLAYER_NAME.fullmatch(p)}
    current = {e["name"].lower(): e["name"] for e in json.loads(docker_exec("cat", "/data/whitelist.json"))}
    removed = [name for key, name in current.items() if key not in wanted]
    for name in removed:
        rcon("whitelist", "remove", name)
    for key, name in wanted.items():
        if key not in current:
            rcon("whitelist", "add", name)
    rcon("whitelist", "on")
    rcon("whitelist", "reload")
    for name in removed:
        rcon("kick", name)


def main():
    # Overlapping runs wait here, and each reads the settings only after getting the lock.
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        wait_until_ready()
        sync(load_settings())


if __name__ == "__main__":
    sys.exit(main())
SYNC_ACCESS
chmod 755 /usr/local/bin/mc-sync-access

cat > /etc/systemd/system/mc-sync-access.service <<'EOF'
[Unit]
Description=Apply this server's saved Minecraft access settings
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mc-sync-access

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable mc-sync-access.service

mkdir -p /opt/mc/data

if docker inspect mc >/dev/null 2>&1; then
  docker stop -t 120 mc
  docker rm mc
fi

# The whitelist is always on at startup, so nobody can join a whitelisted server before
# mc-sync-access runs. On a public server, mc-sync-access then turns it off.
docker run -d -it --name mc \
  -p 25565:25565 \
  -e EULA=TRUE \
  -e VERSION=LATEST \
  -e MEMORY=1G \
  -e STOP_DURATION=90 \
  -e ENABLE_WHITELIST=TRUE \
  -e ENFORCE_WHITELIST=TRUE \
  -v /opt/mc/data:/data \
  --stop-timeout 120 \
  --restart unless-stopped \
  itzg/minecraft-server

systemctl start --no-block mc-sync-access.service
