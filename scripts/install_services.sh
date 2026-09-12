#!/bin/bash
# Installs and starts all Broll Notetaker systemd services. Run after setup_server.sh.
# Usage: sudo ./scripts/install_services.sh
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Run this as root (sudo ./scripts/install_services.sh)." >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cp "$REPO_DIR"/systemd/*.service /etc/systemd/system/
systemctl daemon-reload

SERVICES=(
  broll-xvfb
  broll-pulseaudio
  broll-backend
  broll-notes-worker
  broll-meet-worker
  broll-transcription-worker
)

for svc in "${SERVICES[@]}"; do
  systemctl enable --now "$svc"
done

echo ""
echo "All services started. Useful commands:"
echo "  systemctl status broll-backend"
echo "  journalctl -u broll-meet-worker -f"
echo "  sudo systemctl restart broll-backend   # after pulling code changes"
