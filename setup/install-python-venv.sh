#!/usr/bin/env bash
# NeonCore 5G — install python3-venv (needed to build an isolated env for the Phase 5 CLI).
# Run this yourself in a terminal with a TTY: bash ~/neoncore-5g/setup/install-python-venv.sh
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip

echo "python3-venv installed OK"
