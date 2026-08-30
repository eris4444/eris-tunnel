#!/usr/bin/env bash
#
# Eris Tunnel - one command installer
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/eris4444/eris-tunnel/main/install.sh)
#
# Options:
#   --port <n>          panel port          (default: random 20000-45000)
#   --username <name>   admin username      (default: admin)
#   --password <pass>   admin password      (default: random)
#   --branch <name>     source branch       (default: main)
#   --lang fa|en        panel language      (default: fa)
#
set -euo pipefail

REPO="eris4444/eris-tunnel"
BRANCH="main"
APP_DIR="/opt/eris-tunnel"
DATA_DIR="/etc/eris-tunnel"
SERVICE="eris-tunnel"
VENV="$APP_DIR/venv"

PANEL_PORT=""
ADMIN_USER="admin"
ADMIN_PASS=""
LANGUAGE="fa"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
BLUE=$'\033[0;36m'; PURPLE=$'\033[0;35m'; BOLD=$'\033[1m'; NC=$'\033[0m'

info()  { echo -e "${BLUE}::${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
die()   { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

banner() {
cat <<'ART'

   ______     _        _____                       _
  |  ____|   (_)      |_   _|                     | |
  | |__   _ __ _ ___    | |_   _ _ __  _ __   ___ | |
  |  __| | '__| / __|   | | | | | '_ \| '_ \ / _ \| |
  | |____| |  | \__ \   | | |_| | | | | | | |  __/| |
  |______|_|  |_|___/   |_|\__,_|_| |_|_| |_|\___||_|

  SSH  +  Backhaul  tunnel panel
ART
echo
}

# ── arguments ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)     PANEL_PORT="${2:-}"; shift 2 ;;
    --username) ADMIN_USER="${2:-}"; shift 2 ;;
    --password) ADMIN_PASS="${2:-}"; shift 2 ;;
    --branch)   BRANCH="${2:-}";     shift 2 ;;
    --lang)     LANGUAGE="${2:-}";   shift 2 ;;
    -h|--help)
      cat <<'USAGE'
Eris Tunnel installer

  --port <n>          panel port          (default: keep current, else random)
  --username <name>   admin username      (default: admin)
  --password <pass>   admin password      (default: random)
  --branch <name>     source branch       (default: main)
  --lang fa|en        panel language      (default: fa)
USAGE
      exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

banner
[[ $EUID -eq 0 ]] || die "run this installer as root (try: sudo -i)"
[[ -d /run/systemd/system ]] || die "systemd is required and was not detected"

case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64|armv7l|i686) : ;;
  *) warn "untested architecture: $(uname -m)" ;;
esac

if [[ -z "$PANEL_PORT" ]]; then
  # An upgrade must not move the panel to a new random port.
  if [[ -f "$DATA_DIR/config.json" ]]; then
    PANEL_PORT=$(grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]\+' "$DATA_DIR/config.json"                  | grep -o '[0-9]\+$' || true)
  fi
  [[ -z "$PANEL_PORT" ]] && PANEL_PORT=$(( (RANDOM % 25000) + 20000 ))
fi
[[ "$PANEL_PORT" =~ ^[0-9]+$ ]] && (( PANEL_PORT > 0 && PANEL_PORT < 65536 )) \
  || die "invalid port: $PANEL_PORT"

# ── dependencies ─────────────────────────────────────────────────────────
install_packages() {
  local packages_apt="python3 python3-venv python3-pip curl tar openssh-client sshpass ca-certificates"
  local packages_rpm="python3 python3-pip curl tar openssh-clients sshpass ca-certificates"
  local packages_arch="python python-pip curl tar openssh sshpass ca-certificates"
  local packages_apk="python3 py3-pip curl tar openssh-client sshpass ca-certificates"

  if command -v apt-get >/dev/null 2>&1; then
    info "installing packages with apt"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || warn "apt-get update reported problems, continuing"
    # shellcheck disable=SC2086
    apt-get install -y -qq $packages_apt >/dev/null
  elif command -v dnf >/dev/null 2>&1; then
    info "installing packages with dnf"
    dnf install -y epel-release >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    dnf install -y $packages_rpm >/dev/null || warn "some packages could not be installed"
  elif command -v yum >/dev/null 2>&1; then
    info "installing packages with yum"
    yum install -y epel-release >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    yum install -y $packages_rpm >/dev/null || warn "some packages could not be installed"
  elif command -v pacman >/dev/null 2>&1; then
    info "installing packages with pacman"
    # shellcheck disable=SC2086
    pacman -Sy --noconfirm --needed $packages_arch >/dev/null
  elif command -v apk >/dev/null 2>&1; then
    info "installing packages with apk"
    # shellcheck disable=SC2086
    apk add --no-cache $packages_apk >/dev/null
  else
    warn "no supported package manager found - make sure python3 and ssh are installed"
  fi
}

install_packages
command -v python3 >/dev/null 2>&1 || die "python3 is required but was not installed"
command -v sshpass >/dev/null 2>&1 || warn "sshpass is missing: SSH password auth will be unavailable"
ok "dependencies ready"

# ── source ───────────────────────────────────────────────────────────────
UPGRADE=false
[[ -f "$DATA_DIR/config.json" ]] && UPGRADE=true

info "downloading Eris Tunnel ($BRANCH)"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

if ! curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" \
      -o "$TMP_DIR/src.tar.gz"; then
  die "could not download the source archive - check the server's internet access"
fi

tar -xzf "$TMP_DIR/src.tar.gz" -C "$TMP_DIR"
SRC_DIR=$(find "$TMP_DIR" -maxdepth 1 -type d -name 'eris-tunnel-*' | head -n1)
[[ -n "$SRC_DIR" ]] || die "unexpected archive layout"

systemctl stop "$SERVICE" 2>/dev/null || true

mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/backend" "$APP_DIR/web"
cp -r "$SRC_DIR/backend" "$SRC_DIR/web" "$APP_DIR/"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/" 2>/dev/null || true
cp "$SRC_DIR/uninstall.sh" "$APP_DIR/" 2>/dev/null || true
chmod +x "$APP_DIR/uninstall.sh" 2>/dev/null || true
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"
ok "source installed in $APP_DIR"

# ── python environment ───────────────────────────────────────────────────
info "creating the python environment"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV" 2>/dev/null || die "could not create a virtualenv - install python3-venv"
fi
"$VENV/bin/pip" install --quiet --upgrade pip wheel >/dev/null 2>&1 || true
if ! "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"; then
  die "installing python dependencies failed"
fi
ok "python environment ready"

# ── account + settings ───────────────────────────────────────────────────
SETUP_ARGS=(setup --port "$PANEL_PORT" --language "$LANGUAGE" --username "$ADMIN_USER")
[[ -n "$ADMIN_PASS" ]] && SETUP_ARGS+=(--password "$ADMIN_PASS")

SETUP_JSON=$(cd "$APP_DIR" && "$VENV/bin/python" -m backend.cli "${SETUP_ARGS[@]}")
ADMIN_USER=$(echo "$SETUP_JSON" | sed -n 's/.*"username": *"\([^"]*\)".*/\1/p')
NEW_PASS=$(echo "$SETUP_JSON"   | sed -n 's/.*"password": *"\([^"]*\)".*/\1/p')

# ── systemd unit ─────────────────────────────────────────────────────────
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Eris Tunnel Panel
Documentation=https://github.com/$REPO
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV/bin/python -m backend.server
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "$SERVICE" >/dev/null 2>&1
sleep 2

if ! systemctl is-active --quiet "$SERVICE"; then
  echo
  warn "the panel service did not start; recent log:"
  journalctl -u "$SERVICE" -n 25 --no-pager || true
  die "installation failed"
fi
ok "panel service is running"

# ── firewall ─────────────────────────────────────────────────────────────
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "$PANEL_PORT/tcp" >/dev/null 2>&1 && ok "opened port $PANEL_PORT in ufw"
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PANEL_PORT/tcp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 && ok "opened port $PANEL_PORT in firewalld"
fi

# ── eris CLI ─────────────────────────────────────────────────────────────
cat > /usr/local/bin/eris <<'CLI'
#!/usr/bin/env bash
# Eris Tunnel helper - `eris help` for the command list.
set -euo pipefail
APP_DIR="/opt/eris-tunnel"
VENV="$APP_DIR/venv"
SERVICE="eris-tunnel"
GREEN=$'\033[0;32m'; BLUE=$'\033[0;36m'; NC=$'\033[0m'

need_root() { [[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }; }

panel_url() {
  local port ip
  port=$("$VENV/bin/python" -c "import json;print(json.load(open('/etc/eris-tunnel/config.json'))['port'])" 2>/dev/null || echo "?")
  ip=$(curl -s -4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
  echo "http://${ip:-<server-ip>}:$port"
}

case "${1:-help}" in
  start)     need_root; systemctl start   "$SERVICE"; echo "${GREEN}started${NC}" ;;
  stop)      need_root; systemctl stop    "$SERVICE"; echo "stopped" ;;
  restart)   need_root; systemctl restart "$SERVICE"; echo "${GREEN}restarted${NC}" ;;
  status)    systemctl status "$SERVICE" --no-pager ;;
  log|logs)  journalctl -u "$SERVICE" -n "${2:-100}" --no-pager ;;
  follow)    journalctl -u "$SERVICE" -f ;;
  url)       panel_url ;;
  info)      need_root; cd "$APP_DIR" && "$VENV/bin/python" -m backend.cli info; echo "url: $(panel_url)" ;;
  reset)
    need_root
    cd "$APP_DIR"
    out=$("$VENV/bin/python" -m backend.cli reset ${2:+--username "$2"})
    user=$(echo "$out" | sed -n 's/.*"username": *"\([^"]*\)".*/\1/p')
    pass=$(echo "$out" | sed -n 's/.*"password": *"\([^"]*\)".*/\1/p')
    systemctl restart "$SERVICE"
    echo "${BLUE}username:${NC} $user"
    echo "${BLUE}password:${NC} $pass"
    ;;
  port)
    need_root
    [[ -n "${2:-}" ]] || { echo "usage: eris port <number>"; exit 1; }
    cd "$APP_DIR" && "$VENV/bin/python" -m backend.cli set-port "$2" >/dev/null
    if command -v ufw >/dev/null 2>&1; then ufw allow "$2/tcp" >/dev/null 2>&1 || true; fi
    systemctl restart "$SERVICE"
    echo "${GREEN}panel now on port $2${NC} -> $(panel_url)"
    ;;
  update)
    need_root
    bash <(curl -fsSL https://raw.githubusercontent.com/eris4444/eris-tunnel/main/install.sh)
    ;;
  uninstall) need_root; bash "$APP_DIR/uninstall.sh" ;;
  *)
    cat <<'HELP'
Eris Tunnel

  eris start|stop|restart|status   control the panel service
  eris log [n] | follow            read panel logs
  eris info                        show panel settings and URL
  eris url                         print the panel URL
  eris reset [username]            reset the admin login
  eris port <number>               change the panel port
  eris update                      reinstall the latest version
  eris uninstall                   remove Eris Tunnel
HELP
    ;;
esac
CLI
chmod +x /usr/local/bin/eris

# ── summary ──────────────────────────────────────────────────────────────
SERVER_IP=$(curl -s -4 --max-time 5 https://api.ipify.org 2>/dev/null || true)
[[ -z "$SERVER_IP" ]] && SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -z "$SERVER_IP" ]] && SERVER_IP="<server-ip>"

echo
echo -e "${PURPLE}${BOLD}────────────────────────────────────────────────${NC}"
if $UPGRADE && [[ -z "$NEW_PASS" ]]; then
  echo -e " ${GREEN}${BOLD}Eris Tunnel updated${NC}"
  echo
  echo -e "   ${BOLD}Panel:${NC}    http://$SERVER_IP:$PANEL_PORT"
  echo -e "   ${BOLD}Login:${NC}    unchanged (run ${BLUE}eris reset${NC} if forgotten)"
else
  echo -e " ${GREEN}${BOLD}Eris Tunnel installed${NC}"
  echo
  echo -e "   ${BOLD}Panel:${NC}    http://$SERVER_IP:$PANEL_PORT"
  echo -e "   ${BOLD}Username:${NC} $ADMIN_USER"
  echo -e "   ${BOLD}Password:${NC} $NEW_PASS"
fi
echo
echo -e "   ${BOLD}Manage:${NC}   ${BLUE}eris${NC} (status, log, reset, port, update, uninstall)"
echo -e "${PURPLE}${BOLD}────────────────────────────────────────────────${NC}"
echo
warn "save these credentials now - the password is not shown again"
echo
