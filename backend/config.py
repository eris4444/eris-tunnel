"""Runtime paths and persisted panel settings for Eris Tunnel."""
import json
import os
import secrets
from pathlib import Path

APP_NAME = "Eris Tunnel"
VERSION = "1.0.0"

# Root of all persisted state. Overridable so the panel can run unprivileged
# during development.
HOME = Path(os.environ.get("ERIS_HOME", "/etc/eris-tunnel"))

CONFIG_FILE = HOME / "config.json"
DB_FILE = HOME / "eris.db"
BIN_DIR = HOME / "bin"
KEY_DIR = HOME / "keys"
ENV_DIR = HOME / "env"
BACKHAUL_DIR = HOME / "backhaul"
KNOWN_HOSTS = HOME / "known_hosts"

BACKHAUL_BIN = BIN_DIR / "backhaul"
SYSTEMD_DIR = Path(os.environ.get("ERIS_SYSTEMD_DIR", "/etc/systemd/system"))

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8686,
    "secret": "",
    "session_hours": 12,
    "language": "fa",
}


def ensure_dirs() -> None:
    for d in (HOME, BIN_DIR, KEY_DIR, ENV_DIR, BACKHAUL_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # Keys and stored SSH passwords must never be world readable.
    for d in (KEY_DIR, ENV_DIR):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def load() -> dict:
    ensure_dirs()
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    if not cfg.get("secret"):
        cfg["secret"] = secrets.token_hex(32)
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
