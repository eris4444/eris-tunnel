#!/usr/bin/env bash
#
# Eris Tunnel - uninstaller. Removes the panel, its tunnels and (optionally)
# all stored configuration.
#
set -euo pipefail

APP_DIR="/opt/eris-tunnel"
DATA_DIR="/etc/eris-tunnel"
SERVICE="eris-tunnel"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

[[ $EUID -eq 0 ]] || { echo -e "${RED}run as root${NC}"; exit 1; }

KEEP_DATA=false
[[ "${1:-}" == "--keep-data" ]] && KEEP_DATA=true

echo -e "${YELLOW}Removing Eris Tunnel…${NC}"

# Panel service
systemctl disable --now "$SERVICE" 2>/dev/null || true
rm -f "/etc/systemd/system/$SERVICE.service"

# Every tunnel unit the panel created
for unit in /etc/systemd/system/eris-ssh-*.service /etc/systemd/system/eris-backhaul-*.service; do
  [[ -e "$unit" ]] || continue
  name=$(basename "$unit")
  systemctl disable --now "$name" 2>/dev/null || true
  rm -f "$unit"
  echo "  removed $name"
done

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

rm -rf "$APP_DIR"
rm -f /usr/local/bin/eris

if $KEEP_DATA; then
  echo -e "${YELLOW}kept configuration in $DATA_DIR${NC}"
else
  rm -rf "$DATA_DIR"
fi

echo -e "${GREEN}✓ Eris Tunnel removed${NC}"
