"""Thin wrapper around systemctl / journalctl for tunnel unit management."""
import os
import re
import shutil
import subprocess
from typing import Optional

from . import config

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


class SystemdError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("systemctl") is not None


def _run(args: list, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def unit_name(kind: str, name: str) -> str:
    """Map a tunnel to its systemd unit, e.g. eris-ssh-tokyo.service."""
    if not NAME_RE.match(name):
        raise SystemdError("invalid tunnel name")
    return "eris-{}-{}.service".format(kind, name)


def unit_path(kind: str, name: str):
    return config.SYSTEMD_DIR / unit_name(kind, name)


def write_unit(kind: str, name: str, content: str) -> None:
    path = unit_path(kind, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o644)
    daemon_reload()


def remove_unit(kind: str, name: str) -> None:
    path = unit_path(kind, name)
    if path.exists():
        path.unlink()
    daemon_reload()


def daemon_reload() -> None:
    if available():
        _run(["systemctl", "daemon-reload"])


def _ctl(action: str, unit: str) -> dict:
    if not available():
        raise SystemdError("systemd is not available on this host")
    proc = _run(["systemctl", action, unit])
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "output": (proc.stdout + proc.stderr).strip(),
    }


def start(kind: str, name: str) -> dict:
    return _ctl("start", unit_name(kind, name))


def stop(kind: str, name: str) -> dict:
    return _ctl("stop", unit_name(kind, name))


def restart(kind: str, name: str) -> dict:
    return _ctl("restart", unit_name(kind, name))


def enable(kind: str, name: str) -> dict:
    return _ctl("enable", unit_name(kind, name))


def disable(kind: str, name: str) -> dict:
    return _ctl("disable", unit_name(kind, name))


def status(kind: str, name: str) -> dict:
    """Return active/enabled state plus uptime and memory for a unit."""
    unit = unit_name(kind, name)
    if not available():
        return {"active": "unknown", "enabled": "unknown", "since": "", "memory": 0}
    props = _run(
        [
            "systemctl",
            "show",
            unit,
            "--no-page",
            "--property=ActiveState",
            "--property=SubState",
            "--property=UnitFileState",
            "--property=ExecMainStartTimestamp",
            "--property=MemoryCurrent",
            "--property=MainPID",
        ]
    )
    data = {}
    for line in props.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            data[key] = value
    memory = data.get("MemoryCurrent", "0")
    return {
        "active": data.get("ActiveState", "unknown"),
        "sub": data.get("SubState", ""),
        "enabled": data.get("UnitFileState", "disabled"),
        "since": data.get("ExecMainStartTimestamp", ""),
        "pid": data.get("MainPID", "0"),
        "memory": int(memory) if memory.isdigit() else 0,
    }


def logs(kind: str, name: str, lines: int = 200) -> str:
    if not shutil.which("journalctl"):
        return "journalctl is not available on this host"
    proc = _run(
        [
            "journalctl",
            "-u",
            unit_name(kind, name),
            "-n",
            str(max(1, min(lines, 2000))),
            "--no-pager",
            "--output=short-iso",
        ],
        timeout=30,
    )
    return (proc.stdout + proc.stderr).strip() or "(no log entries yet)"


def render_unit(
    description: str,
    exec_start: str,
    env_file: Optional[str] = None,
    extra_service: str = "",
) -> str:
    env_line = "EnvironmentFile=-{}\n".format(env_file) if env_file else ""
    return (
        "[Unit]\n"
        "Description={}\n"
        "Documentation=https://github.com/eris4444/eris-tunnel\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "StartLimitIntervalSec=0\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "{}"
        "ExecStart={}\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "KillMode=mixed\n"
        "LimitNOFILE=1048576\n"
        "{}"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    ).format(description, env_line, exec_start, extra_service)
