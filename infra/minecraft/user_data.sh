#!/bin/bash
set -euxo pipefail

dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user

mkdir -p /opt/mc/data

docker run -d -it --name mc \
  -p 25565:25565 \
  -e EULA=TRUE \
  -e VERSION=LATEST \
  -e MEMORY=1G \
  -v /opt/mc/data:/data \
  --restart unless-stopped \
  itzg/minecraft-server