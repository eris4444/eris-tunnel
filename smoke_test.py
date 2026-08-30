"""Local smoke test: exercises the API end to end with TestClient."""
import json
import os
import shutil
import sys
import tempfile

DEV_HOME = tempfile.mkdtemp(prefix="eris-smoke-")
os.environ["ERIS_HOME"] = DEV_HOME
os.environ["ERIS_SYSTEMD_DIR"] = os.path.join(DEV_HOME, "systemd")

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth, backhaul, cli, config, sshtun, store  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label + (" :: " + str(detail) if detail and not condition else ""))
    if not condition:
        failures.append(label)


print("ERIS_HOME =", DEV_HOME)

# --- bootstrap -------------------------------------------------------------
cli.main(["setup", "--username", "admin", "--password", "test-password", "--port", "8686"])
check("admin account created", store.user_count() == 1)

from backend import main as app_main  # noqa: E402

client = TestClient(app_main.app)

# --- auth ------------------------------------------------------------------
check("health endpoint", client.get("/health").json()["ok"] is True)
check("api requires auth", client.get("/api/system").status_code == 401)
check("bad password rejected",
      client.post("/api/login", json={"username": "admin", "password": "nope"}).status_code == 401)

login = client.post("/api/login", json={"username": "admin", "password": "test-password"})
check("login succeeds", login.status_code == 200, login.text)
token = login.json()["token"]
client.headers.update({"Authorization": "Bearer " + token})

check("tampered token rejected",
      auth.verify_token(token[:-3] + "aaa", config.load()["secret"]) is None)
check("me endpoint", client.get("/api/me").json()["username"] == "admin")

# --- system ----------------------------------------------------------------
system = client.get("/api/system")
check("system snapshot", system.status_code == 200, system.text)
check("overview", client.get("/api/overview").status_code == 200)

# --- ssh keys --------------------------------------------------------------
if shutil.which("ssh-keygen"):
    created = client.post("/api/keys", json={"name": "test-key"})
    check("generate ssh key", created.status_code == 200, created.text)
    check("public key returned", "ssh-ed25519" in created.json().get("public_key", ""))
    check("duplicate key rejected",
          client.post("/api/keys", json={"name": "test-key"}).status_code == 409)
    check("key list", len(client.get("/api/keys").json()) == 1)
else:
    print("  SKIP  ssh-keygen not available")

# --- ssh tunnel validation -------------------------------------------------
valid = {
    "name": "tokyo",
    "host": "203.0.113.10",
    "port": 22,
    "user": "root",
    "auth": "key",
    "key_name": "test-key",
    "forwards": [
        {"type": "local", "bind": "0.0.0.0", "listen_port": 8080,
         "dest_host": "127.0.0.1", "dest_port": 80},
        {"type": "remote", "bind": "0.0.0.0", "listen_port": 2053,
         "dest_host": "127.0.0.1", "dest_port": 443},
        {"type": "dynamic", "bind": "127.0.0.1", "listen_port": 1080},
    ],
    "keepalive": 30,
    "options": ["GatewayPorts=yes"],
}
cfg = sshtun.validate(valid)
command = sshtun.build_command(cfg)
print("  ExecStart:", command)
check("-L rendered", "-L 0.0.0.0:8080:127.0.0.1:80" in command)
check("-R rendered", "-R 0.0.0.0:2053:127.0.0.1:443" in command)
check("-D rendered", "-D 127.0.0.1:1080" in command)
check("key auth uses BatchMode", "BatchMode=yes" in command)
check("extra option rendered", "-o GatewayPorts=yes" in command)

for bad, label in [
    ({**valid, "host": "1.2.3.4; rm -rf /"}, "rejects host injection"),
    ({**valid, "user": "root$(id)"}, "rejects user injection"),
    ({**valid, "options": ["X=y; touch /tmp/pwn"]}, "rejects option injection"),
    ({**valid, "forwards": []}, "rejects empty forwards"),
    ({**valid, "forwards": [{"type": "local", "listen_port": 99999,
                             "dest_host": "a", "dest_port": 80}]}, "rejects bad port"),
]:
    try:
        sshtun.validate(bad)
        check(label, False, "validation passed when it should not")
    except sshtun.ValidationError:
        check(label, True)

# --- ssh tunnel API --------------------------------------------------------
created = client.post("/api/ssh", json={**valid, "autostart": False})
check("create ssh tunnel", created.status_code == 200, created.text)
tunnel_id = created.json().get("id")
check("duplicate name rejected",
      client.post("/api/ssh", json={**valid, "autostart": False}).status_code == 409)

listed = client.get("/api/ssh").json()
check("ssh tunnel listed", len(listed) == 1 and listed[0]["name"] == "tokyo")
check("no password field exposed", all("password" not in item for item in listed))
check("only the has_password flag is stored",
      isinstance(listed[0].get("has_password"), bool))
check("stored config never carries a secret",
      "password" not in store.list_tunnels("ssh")[0]
      or store.list_tunnels("ssh")[0].get("password") is None)

updated = client.put("/api/ssh/" + str(tunnel_id), json={**valid, "keepalive": 60})
check("update ssh tunnel", updated.status_code == 200, updated.text)
check("keepalive persisted", client.get("/api/ssh").json()[0]["keepalive"] == 60)

# --- backhaul config rendering --------------------------------------------
server_cfg = backhaul.validate({
    "role": "server", "transport": "tcpmux", "token": "s3cret-token",
    "bind_addr": "0.0.0.0:3080", "ports": ["443", "8080=80", "2000-2100"],
    "accept_udp": True, "web_port": 2060, "mux_con": 12,
})
toml = backhaul.render_toml("main", server_cfg)
print("---- backhaul server toml ----")
print(toml)
check("server section", toml.startswith("# Generated by Eris Tunnel - main"))
check("bind_addr rendered", 'bind_addr = "0.0.0.0:3080"' in toml)
check("ports rendered", '"8080=80",' in toml)
check("mux rendered", "mux_con = 12" in toml)
check("bool rendered unquoted", "accept_udp = true" in toml)

client_cfg = backhaul.validate({
    "role": "client", "transport": "wss", "token": "s3cret-token",
    "remote_addr": "203.0.113.10:3080", "connection_pool": 16,
})
client_toml = backhaul.render_toml("edge", client_cfg)
check("client section", "[client]" in client_toml)
check("remote_addr rendered", 'remote_addr = "203.0.113.10:3080"' in client_toml)
check("no mux for wss", "mux_con" not in client_toml)

for bad, label in [
    ({"role": "server", "token": "t", "bind_addr": "nope"}, "rejects bad bind addr"),
    ({"role": "server", "token": "a b; rm", "bind_addr": "0.0.0.0:80"}, "rejects bad token"),
    ({"role": "client", "token": "t", "remote_addr": ""}, "rejects empty remote addr"),
    ({"role": "server", "token": "t", "bind_addr": "0.0.0.0:80",
      "ports": ["443; rm -rf /"]}, "rejects bad port rule"),
    ({"role": "bogus", "token": "t"}, "rejects bad role"),
]:
    try:
        backhaul.validate(bad)
        check(label, False, "validation passed when it should not")
    except backhaul.ValidationError:
        check(label, True)

check("backhaul create blocked without binary",
      client.post("/api/backhaul", json={
          "name": "main", "role": "server", "token": "abc",
          "bind_addr": "0.0.0.0:3080", "autostart": False}).status_code == 400)

# --- settings & account ----------------------------------------------------
check("settings read", client.get("/api/settings").json()["port"] == 8686)
check("settings write", client.post("/api/settings", json={"port": 9090}).json()["restart_needed"] is True)
check("bad port rejected", client.post("/api/settings", json={"port": 0}).status_code == 400)

check("wrong current password rejected",
      client.post("/api/account", json={"current_password": "wrong",
                                        "new_password": "another-one"}).status_code == 403)
changed = client.post("/api/account", json={"current_password": "test-password",
                                            "new_password": "brand-new-pass"})
check("password change", changed.status_code == 200, changed.text)
check("old password no longer works",
      client.post("/api/login", json={"username": "admin", "password": "test-password"}).status_code == 401)
check("new password works",
      client.post("/api/login", json={"username": "admin", "password": "brand-new-pass"}).status_code == 200)

# --- cleanup ---------------------------------------------------------------
check("delete ssh tunnel", client.delete("/api/ssh/" + str(tunnel_id)).status_code == 200)
check("tunnel gone", client.get("/api/ssh").json() == [])

# --- file permissions ------------------------------------------------------
if os.name != "nt":
    mode = oct(os.stat(config.CONFIG_FILE).st_mode & 0o777)
    check("config.json is 0600", mode == "0o600", mode)

print()
if failures:
    print("FAILED:", len(failures))
    for item in failures:
        print("  -", item)
    sys.exit(1)
print("all checks passed")
shutil.rmtree(DEV_HOME, ignore_errors=True)
