#!/usr/bin/env bash
# NeonCore 5G — native docker-ce install for WSL2 (Ubuntu 24.04 noble)
# Run this yourself in a terminal with a TTY: bash ~/neoncore-5g/setup/install-docker.sh
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
fi
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -qq
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let docker run under WSL2's systemd (wsl.conf already has systemd=true)
sudo systemctl enable --now docker

# Allow running docker without sudo
sudo usermod -aG docker "$USER"

echo
echo "=== Install complete ==="
echo "Log out and back into this WSL distro (or run 'newgrp docker') for the group change to apply."
echo "Then verify with: docker run hello-world"
