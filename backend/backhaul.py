"""Backhaul tunnel management: binary installation, TOML config, systemd units.

Backhaul (github.com/Musixal/Backhaul) is a reverse-tunnel daemon. One side runs
as `server` (listens for the tunnel and exposes ports), the other as `client`.
"""
import io
import json
import os
import platform
import re
import secrets
import subprocess
import tarfile
import urllib.error
import urllib.request
import zipfile

from . import config, systemd

REPO = "Musixal/Backhaul"
API_LATEST = "https://api.github.com/repos/{}/releases/latest".format(REPO)
USER_AGENT = "eris-tunnel"

TRANSPORTS = ("tcp", "tcpmux", "udp", "ws", "wsmux", "wss", "wssmux")
LOG_LEVELS = ("debug", "info", "warn", "error", "fatal", "panic")
PORT_RULE_RE = re.compile(r"^[A-Za-z0-9_.:=\[\]-]{1,64}$")
ADDR_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,255}:[0-9]{1,5}$")


class ValidationError(ValueError):
    pass


# --- binary ----------------------------------------------------------------

def arch_tag() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine.startswith("armv7") or machine.startswith("armv6"):
        return "arm"
    if machine in ("i386", "i686"):
        return "386"
    return machine


def installed_version() -> str:
    if not config.BACKHAUL_BIN.exists():
        return ""
    try:
        proc = subprocess.run(
            [str(config.BACKHAUL_BIN), "-v"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "installed"
    out = (proc.stdout + proc.stderr).strip().splitlines()
    return out[0][:80] if out else "installed"


def _name_tokens(name: str) -> set:
    return set(t for t in re.split(r"[^a-z0-9]+", name.lower()) if t)


def _fetch(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_release() -> dict:
    data = json.loads(_fetch(API_LATEST, timeout=30).decode("utf-8"))
    return {
        "tag": data.get("tag_name", ""),
        "assets": [
            {"name": a["name"], "url": a["browser_download_url"]}
            for a in data.get("assets", [])
        ],
    }


def install_binary() -> dict:
    """Download the newest Backhaul build matching this host's architecture."""
    arch = arch_tag()
    try:
        release = latest_release()
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise ValidationError("could not reach GitHub: {}".format(exc))

    # Match on whole tokens: a plain substring test would pick the arm64
    # archive on an armv7 host.
    candidates = [
        a
        for a in release["assets"]
        if {"linux", arch} <= _name_tokens(a["name"])
    ]
    if not candidates:
        raise ValidationError(
            "no Backhaul build published for linux/{} in {}".format(arch, release["tag"])
        )
    asset = candidates[0]
    blob = _fetch(asset["url"], timeout=180)

    config.BIN_DIR.mkdir(parents=True, exist_ok=True)
    extracted = _extract_binary(asset["name"], blob)
    if not extracted:
        raise ValidationError("could not find the backhaul executable in the archive")

    target = config.BACKHAUL_BIN
    if target.exists():
        target.unlink()
    target.write_bytes(extracted)
    os.chmod(target, 0o755)
    return {"version": release["tag"], "asset": asset["name"], "arch": arch}


def _extract_binary(filename: str, blob: bytes):
    lower = filename.lower()
    if lower.endswith((".tar.gz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile() and os.path.basename(member.name) in (
                    "backhaul",
                    "backhaul_linux_" + arch_tag(),
                ):
                    handle = tar.extractfile(member)
                    if handle:
                        return handle.read()
            # Fall back to the single largest file in the archive.
            files = [m for m in tar.getmembers() if m.isfile()]
            if files:
                biggest = max(files, key=lambda m: m.size)
                handle = tar.extractfile(biggest)
                if handle:
                    return handle.read()
    elif lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            for name in names:
                if os.path.basename(name) == "backhaul":
                    return zf.read(name)
            if names:
                return zf.read(max(names, key=lambda n: zf.getinfo(n).file_size))
    else:
        return blob
    return None


# --- config ----------------------------------------------------------------

def _int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def validate(cfg: dict) -> dict:
    role = cfg.get("role")
    if role not in ("server", "client"):
        raise ValidationError("role must be 'server' or 'client'")

    transport = cfg.get("transport") or "tcp"
    if transport not in TRANSPORTS:
        raise ValidationError("unsupported transport: {}".format(transport))

    token = (cfg.get("token") or "").strip()
    if not token or len(token) > 128:
        raise ValidationError("token is required (max 128 characters)")
    if not re.match(r"^[A-Za-z0-9._@:+-]{1,128}$", token):
        raise ValidationError("token may only contain letters, digits and ._@:+-")

    log_level = cfg.get("log_level") or "info"
    if log_level not in LOG_LEVELS:
        raise ValidationError("invalid log level")

    clean = {
        "role": role,
        "transport": transport,
        "token": token,
        "log_level": log_level,
        "nodelay": bool(cfg.get("nodelay", True)),
        "sniffer": bool(cfg.get("sniffer", False)),
        "web_port": _int(cfg.get("web_port"), 0, 0, 65535),
        "keepalive_period": _int(cfg.get("keepalive_period"), 75, 1, 3600),
        "note": (cfg.get("note") or "")[:200],
    }

    if role == "server":
        bind_addr = (cfg.get("bind_addr") or "0.0.0.0:3080").strip()
        if not ADDR_RE.match(bind_addr):
            raise ValidationError("bind address must look like 0.0.0.0:3080")
        ports = []
        for rule in cfg.get("ports") or []:
            rule = str(rule).strip()
            if not rule:
                continue
            if not PORT_RULE_RE.match(rule):
                raise ValidationError("invalid port rule: {}".format(rule))
            ports.append(rule)
        clean.update(
            {
                "bind_addr": bind_addr,
                "ports": ports,
                "accept_udp": bool(cfg.get("accept_udp", False)),
                "heartbeat": _int(cfg.get("heartbeat"), 40, 1, 3600),
                "channel_size": _int(cfg.get("channel_size"), 2048, 16, 65536),
                "tls_cert": _path(cfg.get("tls_cert")),
                "tls_key": _path(cfg.get("tls_key")),
            }
        )
    else:
        remote_addr = (cfg.get("remote_addr") or "").strip()
        if not ADDR_RE.match(remote_addr):
            raise ValidationError("remote address must look like 1.2.3.4:3080")
        edge_ip = (cfg.get("edge_ip") or "").strip()
        if edge_ip and not re.match(r"^[A-Za-z0-9._:\[\]-]{1,255}$", edge_ip):
            raise ValidationError("invalid edge IP")
        clean.update(
            {
                "remote_addr": remote_addr,
                "edge_ip": edge_ip,
                "connection_pool": _int(cfg.get("connection_pool"), 8, 1, 1024),
                "aggressive_pool": bool(cfg.get("aggressive_pool", False)),
                "dial_timeout": _int(cfg.get("dial_timeout"), 10, 1, 600),
                "retry_interval": _int(cfg.get("retry_interval"), 3, 1, 600),
            }
        )

    if transport in ("tcpmux", "wsmux", "wssmux"):
        clean.update(
            {
                "mux_con": _int(cfg.get("mux_con"), 8, 1, 128),
                "mux_version": _int(cfg.get("mux_version"), 1, 1, 2),
                "mux_framesize": _int(cfg.get("mux_framesize"), 32768, 1024, 1048576),
                "mux_receivebuffer": _int(
                    cfg.get("mux_receivebuffer"), 4194304, 4096, 67108864
                ),
                "mux_streambuffer": _int(
                    cfg.get("mux_streambuffer"), 65536, 4096, 16777216
                ),
            }
        )
    return clean


def _path(value) -> str:
    value = (value or "").strip()
    if value and not re.match(r"^[A-Za-z0-9._/-]{1,255}$", value):
        raise ValidationError("invalid certificate path: {}".format(value))
    return value


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[{}]".format(", ".join(_toml_value(str(v)) for v in value))
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"{}"'.format(escaped)


def render_toml(name: str, cfg: dict) -> str:
    """Produce the Backhaul TOML for a validated config."""
    lines = [
        "# Generated by Eris Tunnel - {}".format(name),
        "# Manual edits are overwritten when the tunnel is saved in the panel.",
        "",
        "[{}]".format(cfg["role"]),
    ]
    fields = []
    if cfg["role"] == "server":
        fields += [("bind_addr", cfg["bind_addr"])]
    else:
        fields += [("remote_addr", cfg["remote_addr"])]
        if cfg.get("edge_ip"):
            fields += [("edge_ip", cfg["edge_ip"])]

    fields += [("transport", cfg["transport"]), ("token", cfg["token"])]

    if cfg["role"] == "server":
        fields += [
            ("accept_udp", cfg["accept_udp"]),
            ("channel_size", cfg["channel_size"]),
            ("heartbeat", cfg["heartbeat"]),
        ]
        if cfg["transport"] in ("wss", "wssmux"):
            if cfg.get("tls_cert"):
                fields.append(("tls_cert", cfg["tls_cert"]))
            if cfg.get("tls_key"):
                fields.append(("tls_key", cfg["tls_key"]))
    else:
        fields += [
            ("connection_pool", cfg["connection_pool"]),
            ("aggressive_pool", cfg["aggressive_pool"]),
            ("dial_timeout", cfg["dial_timeout"]),
            ("retry_interval", cfg["retry_interval"]),
        ]

    fields += [
        ("keepalive_period", cfg["keepalive_period"]),
        ("nodelay", cfg["nodelay"]),
    ]

    for key in (
        "mux_con",
        "mux_version",
        "mux_framesize",
        "mux_receivebuffer",
        "mux_streambuffer",
    ):
        if key in cfg:
            fields.append((key, cfg[key]))

    fields += [("sniffer", cfg["sniffer"])]
    if cfg["sniffer"]:
        fields.append(
            ("sniffer_log", str(config.BACKHAUL_DIR / "{}.json".format(name)))
        )
    if cfg["web_port"]:
        fields.append(("web_port", cfg["web_port"]))
    fields.append(("log_level", cfg["log_level"]))

    for key, value in fields:
        lines.append("{} = {}".format(key, _toml_value(value)))

    if cfg["role"] == "server":
        lines.append("")
        lines.append("ports = [")
        for rule in cfg.get("ports", []):
            lines.append('    "{}",'.format(rule))
        lines.append("]")

    return "\n".join(lines) + "\n"


def config_path(name: str):
    return config.BACKHAUL_DIR / "{}.toml".format(name)


def apply(name: str, cfg: dict) -> None:
    """Write the TOML config and its systemd unit (does not start it)."""
    if not config.BACKHAUL_BIN.exists():
        raise ValidationError(
            "the Backhaul binary is not installed yet - install it from the panel"
        )
    path = config_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_toml(name, cfg), encoding="utf-8")
    os.chmod(path, 0o600)

    unit = systemd.render_unit(
        description="Eris Tunnel :: Backhaul :: {}".format(name),
        exec_start="{} -c {}".format(config.BACKHAUL_BIN, path),
    )
    systemd.write_unit("backhaul", name, unit)


def remove(name: str) -> None:
    try:
        systemd.stop("backhaul", name)
        systemd.disable("backhaul", name)
    except systemd.SystemdError:
        pass
    systemd.remove_unit("backhaul", name)
    path = config_path(name)
    if path.exists():
        path.unlink()


def read_config(name: str) -> str:
    path = config_path(name)
    return path.read_text("utf-8") if path.exists() else ""


def suggest_token() -> str:
    return secrets.token_hex(12)


def binary_present() -> bool:
    return config.BACKHAUL_BIN.exists()
