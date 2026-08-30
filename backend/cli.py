"""Command line helpers used by install.sh and the `eris` shell wrapper."""
import argparse
import json
import secrets
import string
import sys

from . import auth, config, store


def random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def cmd_setup(args) -> int:
    """Create the first admin account, generating anything not supplied."""
    store.init()
    cfg = config.load()
    if args.port:
        cfg["port"] = args.port
    if args.language:
        cfg["language"] = args.language
    config.save(cfg)

    username = args.username or "admin"
    password = args.password or random_password()

    if store.user_count() == 0:
        store.create_user(username, auth.hash_password(password))
        created = True
    else:
        created = False
        row = store.first_user()
        username = row["username"]
        password = ""

    print(
        json.dumps(
            {
                "created": created,
                "username": username,
                "password": password,
                "port": cfg["port"],
            }
        )
    )
    return 0


def cmd_reset(args) -> int:
    """Reset the admin credentials (used by `eris reset`)."""
    store.init()
    row = store.first_user()
    username = args.username or (row["username"] if row else "admin")
    password = args.password or random_password()
    if row:
        store.update_user(row["username"], username, auth.hash_password(password))
    else:
        store.create_user(username, auth.hash_password(password))
    print(json.dumps({"username": username, "password": password}))
    return 0


def cmd_info(args) -> int:
    cfg = config.load()
    row = store.first_user()
    print(
        json.dumps(
            {
                "version": config.VERSION,
                "port": cfg["port"],
                "host": cfg["host"],
                "language": cfg.get("language", "fa"),
                "username": row["username"] if row else None,
                "ssh_tunnels": len(store.list_tunnels("ssh")),
                "backhaul_tunnels": len(store.list_tunnels("backhaul")),
            },
            indent=2,
        )
    )
    return 0


def cmd_set_port(args) -> int:
    cfg = config.load()
    cfg["port"] = args.port
    config.save(cfg)
    print(json.dumps({"port": cfg["port"]}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eris-tunnel")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="create the first admin account")
    setup.add_argument("--username")
    setup.add_argument("--password")
    setup.add_argument("--port", type=int)
    setup.add_argument("--language", choices=["fa", "en"])
    setup.set_defaults(func=cmd_setup)

    reset = sub.add_parser("reset", help="reset admin credentials")
    reset.add_argument("--username")
    reset.add_argument("--password")
    reset.set_defaults(func=cmd_reset)

    info = sub.add_parser("info", help="print panel configuration")
    info.set_defaults(func=cmd_info)

    port = sub.add_parser("set-port", help="change the panel port")
    port.add_argument("port", type=int)
    port.set_defaults(func=cmd_set_port)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
