#!/usr/bin/env bash
# Sets up the dashboard app side: virtualenv, dependencies, .env, the X
# session file, and the systemd service. The OS-level kiosk steps (packages,
# autologin) are in SETUP.md and only need doing once.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"
cd "$HERE"

echo "==> Creating virtualenv"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
echo "==> Installing Python dependencies"
./venv/bin/pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env  (edit it and add your HA token)"
else
  echo "==> .env already exists, leaving it alone"
fi

echo "==> Installing X session file to ~/.xinitrc"
cp config/xinitrc "$HOME/.xinitrc"
chmod +x "$HOME/.xinitrc"

echo "==> Installing systemd service"
sed "s#__DIR__#$HERE#g; s#__USER__#$USER_NAME#g" \
  systemd/starlight-dashboard.service \
  | sudo tee /etc/systemd/system/starlight-dashboard.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable starlight-dashboard >/dev/null

echo
echo "Done."
echo "Next:"
echo "  1. Edit .env and add your Home Assistant token."
echo "  2. sudo systemctl start starlight-dashboard"
echo "  3. Check it from another machine: http://$(hostname -I | awk '{print $1}'):8080"
echo "  4. Finish the autologin step in SETUP.md, then reboot."
