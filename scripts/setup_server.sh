#!/bin/bash
# One-time server setup: system packages, dedicated user, native MongoDB, Python venv.
#
# Prerequisites: Ubuntu/Debian server, this repo already copied to /opt/broll-notetaker,
# and /opt/broll-notetaker/.env filled in (cp .env.example .env first).
#
# Usage: sudo ./scripts/setup_server.sh
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Run this as root (sudo ./scripts/setup_server.sh)." >&2
  exit 1
fi

INSTALL_DIR="/opt/broll-notetaker"
SERVICE_USER="broll"

if [ ! -f "$INSTALL_DIR/.env" ]; then
  echo "$INSTALL_DIR/.env not found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

echo "==> Installing base system packages"
apt-get update
apt-get install -y \
  python3 python3-venv python3-pip \
  gnupg curl \
  redis-server \
  xvfb pulseaudio ffmpeg

echo "==> Adding MongoDB's official apt repo (not in default Ubuntu/Debian repos)"
# Adjust "jammy" below if you're on a different Ubuntu release (noble, focal, ...) -
# check https://www.mongodb.com/docs/manual/administration/install-on-linux/ for support.
UBUNTU_CODENAME="$(lsb_release -cs 2>/dev/null || echo jammy)"
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${UBUNTU_CODENAME}/mongodb-org/7.0 multiverse" \
  > /etc/apt/sources.list.d/mongodb-org-7.0.list
apt-get update
apt-get install -y mongodb-org

echo "==> Creating service user '$SERVICE_USER'"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --create-home --shell /bin/bash "$SERVICE_USER"

echo "==> Enabling MongoDB and Redis"
systemctl enable --now mongod
systemctl enable --now redis-server

echo "==> Python virtualenv + dependencies"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "==> Installing Playwright's Chromium (as root, so its --with-deps apt step works;"
echo "    installed to a fixed shared path so the 'broll' user can find it at runtime)"
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
"$INSTALL_DIR/.venv/bin/playwright" install --with-deps chromium
chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"

echo "==> Creating MongoDB indexes"
PYTHONPATH="$INSTALL_DIR:$INSTALL_DIR/backend" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/init_db.py"

echo "==> Data/secrets directories"
mkdir -p "$INSTALL_DIR/data/audio" "$INSTALL_DIR/secrets"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo ""
echo "Done. Next steps:"
echo "  1. Put your Google service account JSON at $INSTALL_DIR/secrets/google-service-account.json"
echo "  2. Run scripts/bootstrap_auth.py LOCALLY (not on this server) to generate the"
echo "     chrome-profile/ dir, then copy it to $INSTALL_DIR/secrets/ on this server."
echo "  3. Run sudo ./scripts/install_services.sh to install and start the systemd services."
