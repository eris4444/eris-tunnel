"""Eris Tunnel - FastAPI application serving the panel and its REST API."""
import subprocess
import threading
import time
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import auth, backhaul, config, sshtun, sysinfo, systemd, store

SETTINGS = config.load()
store.init()

app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url=None, redoc_url=None)

ACTIONS = ("start", "stop", "restart", "enable", "disable")


# --- helpers ---------------------------------------------------------------

def current_user(request: Request) -> str:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        token = request.cookies.get("eris_token", "")
    username = auth.verify_token(token, SETTINGS["secret"]) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username


def require_name(name: str) -> str:
    name = (name or "").strip()
    if not systemd.NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Name must be 1-32 characters: letters, digits, dash, underscore",
        )
    return name


def with_status(kind: str, tunnels: list) -> list:
    for tunnel in tunnels:
        try:
            tunnel["status"] = systemd.status(kind, tunnel["name"])
        except systemd.SystemdError:
            tunnel["status"] = {"active": "unknown", "enabled": "unknown"}
        tunnel.pop("password", None)
    return tunnels


def fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def try_unit(action: str, kind: str, name: str) -> dict:
    """Run a systemd action, reporting failure instead of raising."""
    try:
        return getattr(systemd, action)(kind, name)
    except systemd.SystemdError as exc:
        return {"ok": False, "output": str(exc)}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# --- auth ------------------------------------------------------------------

@app.post("/api/login")
def login(payload: dict = Body(...)):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    row = store.get_user(username)
    # Constant-ish work whether or not the account exists.
    stored = row["password_hash"] if row else auth.hash_password("placeholder")
    if not row or not auth.verify_password(password, stored):
        time.sleep(1.0)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    token = auth.issue_token(username, SETTINGS["secret"], SETTINGS["session_hours"])
    return {"token": token, "username": username, "expires_in": SETTINGS["session_hours"] * 3600}


@app.get("/api/me")
def me(username: str = Depends(current_user)):
    return {
        "username": username,
        "version": config.VERSION,
        "language": SETTINGS.get("language", "fa"),
    }


@app.post("/api/account")
def update_account(payload: dict = Body(...), username: str = Depends(current_user)):
    current = str(payload.get("current_password", ""))
    row = store.get_user(username)
    if not row or not auth.verify_password(current, row["password_hash"]):
        raise HTTPException(status_code=403, detail="Current password is wrong")

    new_username = str(payload.get("username", "")).strip() or username
    new_password = str(payload.get("new_password", ""))
    if len(new_username) < 3 or len(new_username) > 32:
        raise HTTPException(status_code=400, detail="Username must be 3-32 characters")
    if new_password and len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    password_hash = (
        auth.hash_password(new_password) if new_password else row["password_hash"]
    )
    store.update_user(username, new_username, password_hash)
    token = auth.issue_token(new_username, SETTINGS["secret"], SETTINGS["session_hours"])
    return {"ok": True, "token": token, "username": new_username}


# --- system ----------------------------------------------------------------

@app.get("/api/system")
def system(username: str = Depends(current_user)):
    data = sysinfo.snapshot()
    data["panel"] = {
        "version": config.VERSION,
        "port": SETTINGS["port"],
        "systemd": systemd.available(),
        "sshpass": sshtun.has_sshpass(),
        "backhaul": backhaul.installed_version(),
    }
    return data


@app.get("/api/overview")
def overview(username: str = Depends(current_user)):
    ssh = with_status("ssh", store.list_tunnels("ssh"))
    bh = with_status("backhaul", store.list_tunnels("backhaul"))
    running = sum(1 for t in ssh + bh if t["status"].get("active") == "active")
    return {
        "ssh_total": len(ssh),
        "backhaul_total": len(bh),
        "running": running,
        "stopped": len(ssh) + len(bh) - running,
        "recent": (ssh + bh)[-5:],
    }


# --- ssh tunnels -----------------------------------------------------------

@app.get("/api/ssh")
def ssh_list(username: str = Depends(current_user)):
    return with_status("ssh", store.list_tunnels("ssh"))


@app.post("/api/ssh")
def ssh_create(payload: dict = Body(...), username: str = Depends(current_user)):
    name = require_name(payload.get("name"))
    if any(t["name"] == name for t in store.list_tunnels("ssh")):
        raise HTTPException(status_code=409, detail="A tunnel with this name exists")
    try:
        cfg = sshtun.validate(payload)
        password = str(payload.get("password", ""))
        if cfg["auth"] == "password":
            if not password:
                raise sshtun.ValidationError("password is required")
            sshtun.write_password(name, password)
            cfg["has_password"] = True
        sshtun.apply(name, cfg)
    except (sshtun.ValidationError, systemd.SystemdError) as exc:
        raise fail(exc)
    tunnel_id = store.add_tunnel("ssh", name, cfg)
    started = {}
    if payload.get("autostart", True):
        try_unit("enable", "ssh", name)
        started = try_unit("start", "ssh", name)
    return {"id": tunnel_id, "name": name, "started": started}


@app.put("/api/ssh/{tunnel_id}")
def ssh_update(
    tunnel_id: int, payload: dict = Body(...), username: str = Depends(current_user)
):
    existing = store.get_tunnel("ssh", tunnel_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    name = require_name(payload.get("name") or existing["name"])
    try:
        cfg = sshtun.validate(payload)
        password = str(payload.get("password", ""))
        if name != existing["name"]:
            sshtun.remove(existing["name"])
        if cfg["auth"] == "password":
            if password:
                sshtun.write_password(name, password)
                cfg["has_password"] = True
            elif existing.get("has_password") and existing["auth"] == "password":
                # Carry the stored secret over to the (possibly renamed) unit.
                old = sshtun.env_file(existing["name"])
                if old.exists():
                    sshtun.write_password(name, old.read_text("utf-8").split("=", 1)[1].strip())
                    if existing["name"] != name:
                        old.unlink()
                cfg["has_password"] = True
            else:
                raise sshtun.ValidationError("password is required")
        else:
            sshtun.clear_password(name)
        sshtun.apply(name, cfg)
    except (sshtun.ValidationError, systemd.SystemdError) as exc:
        raise fail(exc)
    store.update_tunnel("ssh", tunnel_id, name, cfg)
    return {"ok": True, "id": tunnel_id, "name": name,
            "restarted": try_unit("restart", "ssh", name)}


@app.delete("/api/ssh/{tunnel_id}")
def ssh_delete(tunnel_id: int, username: str = Depends(current_user)):
    tunnel = store.get_tunnel("ssh", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    sshtun.remove(tunnel["name"])
    store.delete_tunnel("ssh", tunnel_id)
    return {"ok": True}


@app.post("/api/ssh/test")
def ssh_test(payload: dict = Body(...), username: str = Depends(current_user)):
    try:
        cfg = sshtun.validate(payload)
    except sshtun.ValidationError as exc:
        raise fail(exc)
    password = str(payload.get("password", ""))
    if cfg["auth"] == "password" and not password and payload.get("name"):
        path = sshtun.env_file(str(payload["name"]))
        if path.exists():
            password = path.read_text("utf-8").split("=", 1)[1].strip()
    return sshtun.test_connection(cfg, password)


@app.post("/api/ssh/{tunnel_id}/{action}")
def ssh_action(tunnel_id: int, action: str, username: str = Depends(current_user)):
    if action not in ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown action")
    tunnel = store.get_tunnel("ssh", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    try:
        return getattr(systemd, action)("ssh", tunnel["name"])
    except systemd.SystemdError as exc:
        raise fail(exc)


@app.get("/api/ssh/{tunnel_id}/logs")
def ssh_logs(tunnel_id: int, lines: int = 200, username: str = Depends(current_user)):
    tunnel = store.get_tunnel("ssh", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return PlainTextResponse(systemd.logs("ssh", tunnel["name"], lines))


# --- ssh keys --------------------------------------------------------------

@app.get("/api/keys")
def keys_list(username: str = Depends(current_user)):
    keys = []
    for key in store.list_keys():
        keys.append({**key, **sshtun.read_key(key["name"])})
    return keys


@app.post("/api/keys")
def keys_create(payload: dict = Body(...), username: str = Depends(current_user)):
    name = require_name(payload.get("name"))
    if store.get_key_by_name(name):
        raise HTTPException(status_code=409, detail="A key with this name exists")
    try:
        private_key = payload.get("private_key")
        info = (
            sshtun.import_key(name, private_key)
            if private_key
            else sshtun.generate_key(name)
        )
    except sshtun.ValidationError as exc:
        raise fail(exc)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=400, detail=(exc.stderr or "ssh-keygen failed"))
    key_id = store.add_key(name, info["public_key"], info["fingerprint"])
    return {"id": key_id, **info}


@app.delete("/api/keys/{key_id}")
def keys_delete(key_id: int, username: str = Depends(current_user)):
    key = store.get_key(key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    in_use = [t["name"] for t in store.list_tunnels("ssh") if t.get("key_name") == key["name"]]
    if in_use:
        raise HTTPException(
            status_code=409, detail="Key is used by: " + ", ".join(in_use)
        )
    sshtun.delete_key_files(key["name"])
    store.delete_key(key_id)
    return {"ok": True}


# --- backhaul --------------------------------------------------------------

@app.get("/api/backhaul")
def backhaul_list(username: str = Depends(current_user)):
    return with_status("backhaul", store.list_tunnels("backhaul"))


@app.get("/api/backhaul/binary")
def backhaul_binary(username: str = Depends(current_user)):
    return {
        "installed": backhaul.binary_present(),
        "version": backhaul.installed_version(),
        "arch": backhaul.arch_tag(),
        "path": str(config.BACKHAUL_BIN),
    }


@app.post("/api/backhaul/binary")
def backhaul_binary_install(username: str = Depends(current_user)):
    try:
        return backhaul.install_binary()
    except backhaul.ValidationError as exc:
        raise fail(exc)
    except Exception as exc:  # network/archive failures
        raise HTTPException(status_code=502, detail="Download failed: {}".format(exc))


@app.get("/api/backhaul/token")
def backhaul_token(username: str = Depends(current_user)):
    return {"token": backhaul.suggest_token()}


@app.post("/api/backhaul")
def backhaul_create(payload: dict = Body(...), username: str = Depends(current_user)):
    name = require_name(payload.get("name"))
    if any(t["name"] == name for t in store.list_tunnels("backhaul")):
        raise HTTPException(status_code=409, detail="A tunnel with this name exists")
    try:
        cfg = backhaul.validate(payload)
        backhaul.apply(name, cfg)
    except (backhaul.ValidationError, systemd.SystemdError) as exc:
        raise fail(exc)
    tunnel_id = store.add_tunnel("backhaul", name, cfg)
    started = {}
    if payload.get("autostart", True):
        try_unit("enable", "backhaul", name)
        started = try_unit("start", "backhaul", name)
    return {"id": tunnel_id, "name": name, "started": started}


@app.put("/api/backhaul/{tunnel_id}")
def backhaul_update(
    tunnel_id: int, payload: dict = Body(...), username: str = Depends(current_user)
):
    existing = store.get_tunnel("backhaul", tunnel_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    name = require_name(payload.get("name") or existing["name"])
    try:
        cfg = backhaul.validate(payload)
        if name != existing["name"]:
            backhaul.remove(existing["name"])
        backhaul.apply(name, cfg)
    except (backhaul.ValidationError, systemd.SystemdError) as exc:
        raise fail(exc)
    store.update_tunnel("backhaul", tunnel_id, name, cfg)
    return {"ok": True, "id": tunnel_id, "name": name,
            "restarted": try_unit("restart", "backhaul", name)}


@app.delete("/api/backhaul/{tunnel_id}")
def backhaul_delete(tunnel_id: int, username: str = Depends(current_user)):
    tunnel = store.get_tunnel("backhaul", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    backhaul.remove(tunnel["name"])
    store.delete_tunnel("backhaul", tunnel_id)
    return {"ok": True}


@app.post("/api/backhaul/{tunnel_id}/{action}")
def backhaul_action(tunnel_id: int, action: str, username: str = Depends(current_user)):
    if action not in ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown action")
    tunnel = store.get_tunnel("backhaul", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    try:
        return getattr(systemd, action)("backhaul", tunnel["name"])
    except systemd.SystemdError as exc:
        raise fail(exc)


@app.get("/api/backhaul/{tunnel_id}/logs")
def backhaul_logs(tunnel_id: int, lines: int = 200, username: str = Depends(current_user)):
    tunnel = store.get_tunnel("backhaul", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return PlainTextResponse(systemd.logs("backhaul", tunnel["name"], lines))


@app.get("/api/backhaul/{tunnel_id}/config")
def backhaul_config(tunnel_id: int, username: str = Depends(current_user)):
    tunnel = store.get_tunnel("backhaul", tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return PlainTextResponse(backhaul.read_config(tunnel["name"]))


# --- settings --------------------------------------------------------------

@app.get("/api/settings")
def settings_get(username: str = Depends(current_user)):
    return {
        "host": SETTINGS["host"],
        "port": SETTINGS["port"],
        "language": SETTINGS.get("language", "fa"),
        "session_hours": SETTINGS["session_hours"],
    }


@app.post("/api/settings")
def settings_set(payload: dict = Body(...), username: str = Depends(current_user)):
    restart_needed = False
    if "port" in payload:
        try:
            port = int(payload["port"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid port")
        if not 1 <= port <= 65535:
            raise HTTPException(status_code=400, detail="Port must be 1-65535")
        restart_needed = port != SETTINGS["port"]
        SETTINGS["port"] = port
    if payload.get("host") in ("0.0.0.0", "127.0.0.1"):
        restart_needed = restart_needed or payload["host"] != SETTINGS["host"]
        SETTINGS["host"] = payload["host"]
    if payload.get("language") in ("fa", "en"):
        SETTINGS["language"] = payload["language"]
    if "session_hours" in payload:
        SETTINGS["session_hours"] = max(1, min(int(payload["session_hours"]), 720))
    config.save(SETTINGS)
    return {"ok": True, "restart_needed": restart_needed}


@app.post("/api/panel/restart")
def panel_restart(username: str = Depends(current_user)):
    if not systemd.available():
        raise HTTPException(status_code=400, detail="systemd is not available")

    def _restart():
        time.sleep(1)
        subprocess.run(
            ["systemctl", "restart", "eris-tunnel.service"], check=False, timeout=30
        )

    threading.Thread(target=_restart, daemon=True).start()
    return {"ok": True}


# --- static panel ----------------------------------------------------------

if (config.WEB_DIR / "static").exists():
    app.mount(
        "/static", StaticFiles(directory=str(config.WEB_DIR / "static")), name="static"
    )


@app.get("/health")
def health():
    return {"ok": True, "app": config.APP_NAME, "version": config.VERSION}


@app.get("/")
def index():
    return FileResponse(str(config.WEB_DIR / "index.html"))


@app.get("/{path:path}")
def spa(path: str):
    """Any unmatched non-API path falls back to the single-page panel."""
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(config.WEB_DIR / "index.html"))
