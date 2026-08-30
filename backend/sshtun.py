"""Build, persist and control SSH tunnels backed by systemd units.

Each tunnel becomes one `eris-ssh-<name>.service` running `ssh -N` with the
requested port forwards. systemd's `Restart=always` gives us reconnection for
free, so no autossh dependency is needed.
"""
import os
import re
import shutil
import subprocess
from typing import Optional

from . import config, systemd

HOST_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,255}$")
USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
OPTION_RE = re.compile(r"^[A-Za-z0-9]+=[A-Za-z0-9._/,:@ +-]{1,128}$")

FORWARD_TYPES = ("local", "remote", "dynamic")


class ValidationError(ValueError):
    pass


def _ssh_bin() -> str:
    return shutil.which("ssh") or "/usr/bin/ssh"


def _sshpass_bin() -> Optional[str]:
    return shutil.which("sshpass")


def has_sshpass() -> bool:
    return _sshpass_bin() is not None


def _port(value, field: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValidationError("{} must be a number".format(field))
    if not 1 <= port <= 65535:
        raise ValidationError("{} must be between 1 and 65535".format(field))
    return port


def _bind(value: str, field: str) -> str:
    value = (value or "").strip() or "127.0.0.1"
    if not HOST_RE.match(value):
        raise ValidationError("invalid {}".format(field))
    return value


def key_path(name: str) -> str:
    return str(config.KEY_DIR / name)


def validate(cfg: dict) -> dict:
    """Normalise and validate a tunnel definition coming from the panel."""
    host = (cfg.get("host") or "").strip()
    if not HOST_RE.match(host):
        raise ValidationError("invalid SSH host")
    user = (cfg.get("user") or "root").strip()
    if not USER_RE.match(user):
        raise ValidationError("invalid SSH username")

    auth = cfg.get("auth") or "password"
    if auth not in ("password", "key"):
        raise ValidationError("auth must be 'password' or 'key'")

    forwards = cfg.get("forwards") or []
    if not forwards:
        raise ValidationError("add at least one forward rule")
    clean_forwards = []
    for index, fwd in enumerate(forwards, start=1):
        kind = fwd.get("type")
        if kind not in FORWARD_TYPES:
            raise ValidationError("rule {}: unknown forward type".format(index))
        entry = {
            "type": kind,
            "bind": _bind(fwd.get("bind"), "rule {} bind address".format(index)),
            "listen_port": _port(fwd.get("listen_port"), "rule {} listen port".format(index)),
        }
        if kind != "dynamic":
            dest_host = (fwd.get("dest_host") or "127.0.0.1").strip()
            if not HOST_RE.match(dest_host):
                raise ValidationError("rule {}: invalid destination host".format(index))
            entry["dest_host"] = dest_host
            entry["dest_port"] = _port(
                fwd.get("dest_port"), "rule {} destination port".format(index)
            )
        clean_forwards.append(entry)

    options = []
    for opt in cfg.get("options") or []:
        opt = str(opt).strip()
        if not opt:
            continue
        if not OPTION_RE.match(opt):
            raise ValidationError("invalid ssh option: {}".format(opt))
        options.append(opt)

    return {
        "host": host,
        "port": _port(cfg.get("port") or 22, "SSH port"),
        "user": user,
        "auth": auth,
        "key_name": (cfg.get("key_name") or "").strip(),
        "forwards": clean_forwards,
        "keepalive": max(5, min(int(cfg.get("keepalive") or 30), 300)),
        "compression": bool(cfg.get("compression")),
        "options": options,
        "has_password": bool(cfg.get("has_password")),
        "note": (cfg.get("note") or "")[:200],
    }


def _forward_args(forwards: list) -> list:
    args = []
    for fwd in forwards:
        if fwd["type"] == "local":
            args += ["-L", "{bind}:{listen_port}:{dest_host}:{dest_port}".format(**fwd)]
        elif fwd["type"] == "remote":
            args += ["-R", "{bind}:{listen_port}:{dest_host}:{dest_port}".format(**fwd)]
        else:
            args += ["-D", "{bind}:{listen_port}".format(**fwd)]
    return args


def build_command(cfg: dict) -> str:
    """Render the ExecStart line for a validated tunnel config."""
    args = [
        _ssh_bin(),
        "-N",
        "-T",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval={}".format(cfg["keepalive"]),
        "-o", "ServerAliveCountMax=3",
        "-o", "TCPKeepAlive=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile={}".format(config.KNOWN_HOSTS),
        "-o", "ConnectTimeout=15",
    ]
    if cfg["compression"]:
        args.append("-C")

    if cfg["auth"] == "key":
        if not cfg.get("key_name"):
            raise ValidationError("choose an SSH key")
        args += [
            "-o", "BatchMode=yes",
            "-o", "PreferredAuthentications=publickey",
            "-i", key_path(cfg["key_name"]),
        ]
    else:
        args += [
            "-o", "PubkeyAuthentication=no",
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "NumberOfPasswordPrompts=1",
        ]

    for opt in cfg["options"]:
        args += ["-o", opt]

    args += _forward_args(cfg["forwards"])
    args += ["-p", str(cfg["port"]), "{}@{}".format(cfg["user"], cfg["host"])]

    if cfg["auth"] == "password":
        sshpass = _sshpass_bin()
        if not sshpass:
            raise ValidationError(
                "sshpass is not installed - install it or switch to key auth"
            )
        args = [sshpass, "-e"] + args

    return " ".join(_quote(a) for a in args)


def _quote(arg: str) -> str:
    """systemd unit quoting: wrap in double quotes only when necessary."""
    if re.match(r"^[A-Za-z0-9@%_+=:,./-]+$", arg):
        return arg
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def env_file(name: str):
    return config.ENV_DIR / "ssh-{}.env".format(name)


def write_password(name: str, password: str) -> None:
    path = env_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SSHPASS={}\n".format(password), encoding="utf-8")
    os.chmod(path, 0o600)


def clear_password(name: str) -> None:
    path = env_file(name)
    if path.exists():
        path.unlink()


def apply(name: str, cfg: dict) -> None:
    """Write the systemd unit for a tunnel (does not start it)."""
    exec_start = build_command(cfg)
    unit = systemd.render_unit(
        description="Eris Tunnel :: SSH :: {}".format(name),
        exec_start=exec_start,
        env_file=str(env_file(name)) if cfg["auth"] == "password" else None,
    )
    systemd.write_unit("ssh", name, unit)


def remove(name: str) -> None:
    try:
        systemd.stop("ssh", name)
        systemd.disable("ssh", name)
    except systemd.SystemdError:
        pass
    systemd.remove_unit("ssh", name)
    clear_password(name)


# --- key management --------------------------------------------------------

def generate_key(name: str) -> dict:
    """Create an ed25519 keypair inside the panel's key store."""
    if not systemd.NAME_RE.match(name):
        raise ValidationError("invalid key name")
    path = config.KEY_DIR / name
    if path.exists():
        raise ValidationError("a key with this name already exists")
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise ValidationError("ssh-keygen is not installed")
    subprocess.run(
        [keygen, "-t", "ed25519", "-N", "", "-C", "eris-tunnel:" + name, "-f", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    os.chmod(path, 0o600)
    return read_key(name)


def import_key(name: str, private_key: str) -> dict:
    if not systemd.NAME_RE.match(name):
        raise ValidationError("invalid key name")
    path = config.KEY_DIR / name
    if path.exists():
        raise ValidationError("a key with this name already exists")
    body = private_key.replace("\r\n", "\n").strip() + "\n"
    if "PRIVATE KEY" not in body:
        raise ValidationError("that does not look like an OpenSSH private key")
    path.write_text(body, encoding="utf-8")
    os.chmod(path, 0o600)
    keygen = shutil.which("ssh-keygen")
    if keygen:
        proc = subprocess.run(
            [keygen, "-y", "-f", str(path)], capture_output=True, text=True, timeout=30
        )
        if proc.returncode == 0:
            pub = config.KEY_DIR / (name + ".pub")
            pub.write_text(proc.stdout, encoding="utf-8")
            os.chmod(pub, 0o644)
        else:
            path.unlink()
            raise ValidationError("key is invalid or passphrase protected")
    return read_key(name)


def read_key(name: str) -> dict:
    pub_path = config.KEY_DIR / (name + ".pub")
    public_key = pub_path.read_text("utf-8").strip() if pub_path.exists() else ""
    fingerprint = ""
    keygen = shutil.which("ssh-keygen")
    if keygen and pub_path.exists():
        proc = subprocess.run(
            [keygen, "-lf", str(pub_path)], capture_output=True, text=True, timeout=15
        )
        if proc.returncode == 0:
            fingerprint = proc.stdout.strip()
    return {"name": name, "public_key": public_key, "fingerprint": fingerprint}


def delete_key_files(name: str) -> None:
    for suffix in ("", ".pub"):
        path = config.KEY_DIR / (name + suffix)
        if path.exists():
            path.unlink()


def test_connection(cfg: dict, password: str = "") -> dict:
    """Open a throwaway SSH session to verify credentials and reachability."""
    args = [
        _ssh_bin(),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile={}".format(config.KNOWN_HOSTS),
        "-o", "ConnectTimeout=12",
        "-p", str(cfg["port"]),
    ]
    env = dict(os.environ)
    if cfg["auth"] == "key":
        args += ["-o", "BatchMode=yes", "-i", key_path(cfg["key_name"])]
    else:
        sshpass = _sshpass_bin()
        if not sshpass:
            return {"ok": False, "output": "sshpass is not installed"}
        args += [
            "-o", "PubkeyAuthentication=no",
            "-o", "NumberOfPasswordPrompts=1",
        ]
        args = [sshpass, "-e"] + args
        env["SSHPASS"] = password
    args += ["{}@{}".format(cfg["user"], cfg["host"]), "echo eris-ok"]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=25, env=env, check=False
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "connection timed out"}
    output = (proc.stdout + proc.stderr).strip()
    return {"ok": "eris-ok" in proc.stdout, "output": output[-1500:]}
