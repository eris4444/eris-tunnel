"""Host metrics read straight from /proc and /sys - no third-party deps."""
import os
import platform
import socket
import time
from typing import Optional

_prev_cpu: Optional[tuple] = None
_prev_net: Optional[tuple] = None


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def cpu_percent() -> float:
    """Percentage busy since the previous call (0 on the very first call)."""
    global _prev_cpu
    line = _read("/proc/stat").split("\n")[0]
    if not line.startswith("cpu "):
        return 0.0
    fields = [int(x) for x in line.split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    total = sum(fields)
    if _prev_cpu is None:
        _prev_cpu = (idle, total)
        return 0.0
    d_idle = idle - _prev_cpu[0]
    d_total = total - _prev_cpu[1]
    _prev_cpu = (idle, total)
    if d_total <= 0:
        return 0.0
    return round(100.0 * (1.0 - d_idle / d_total), 1)


def memory() -> dict:
    info = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            info[key] = int(parts[0]) * 1024
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    return {
        "total": total,
        "used": total - available,
        "percent": round(100.0 * (total - available) / total, 1) if total else 0.0,
        "swap_total": swap_total,
        "swap_used": swap_total - swap_free,
    }


def disk(path: str = "/") -> dict:
    try:
        st = os.statvfs(path)
    except (OSError, AttributeError):
        return {"total": 0, "used": 0, "percent": 0.0}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - (st.f_bfree * st.f_frsize)
    return {
        "total": total,
        "used": used,
        "percent": round(100.0 * used / total, 1) if total else 0.0,
        "free": free,
    }


def network() -> dict:
    """Cumulative bytes plus per-second rates across all physical interfaces."""
    global _prev_net
    rx = tx = 0
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        if name == "lo" or name.startswith(("veth", "docker", "br-")):
            continue
        fields = rest.split()
        if len(fields) >= 9:
            rx += int(fields[0])
            tx += int(fields[8])
    now = time.time()
    rx_rate = tx_rate = 0.0
    if _prev_net is not None:
        elapsed = now - _prev_net[2]
        if elapsed > 0:
            rx_rate = max(0.0, (rx - _prev_net[0]) / elapsed)
            tx_rate = max(0.0, (tx - _prev_net[1]) / elapsed)
    _prev_net = (rx, tx, now)
    return {
        "rx": rx,
        "tx": tx,
        "rx_rate": round(rx_rate),
        "tx_rate": round(tx_rate),
    }


def uptime() -> int:
    raw = _read("/proc/uptime").split()
    try:
        return int(float(raw[0]))
    except (IndexError, ValueError):
        return 0


def load_average() -> list:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        return [0.0, 0.0, 0.0]


def connections() -> int:
    """Count established TCP sockets (v4 + v6)."""
    count = 0
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in _read(path).splitlines()[1:]:
            fields = line.split()
            if len(fields) > 3 and fields[3] == "01":  # 01 = ESTABLISHED
                count += 1
    return count


def os_release() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.system() + " " + platform.release()


def snapshot() -> dict:
    return {
        "cpu": cpu_percent(),
        "cores": os.cpu_count() or 1,
        "memory": memory(),
        "disk": disk(),
        "network": network(),
        "uptime": uptime(),
        "load": load_average(),
        "connections": connections(),
        "hostname": socket.gethostname(),
        "os": os_release(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "time": int(time.time()),
    }
