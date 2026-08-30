"""SQLite persistence: users, tunnels, SSH keys."""
import json
import sqlite3
import time
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tunnels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    config     TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (kind, name)
);
CREATE TABLE IF NOT EXISTS ssh_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    public_key  TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# --- users -----------------------------------------------------------------

def get_user(username: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def first_user() -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()


def user_count() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username: str, password_hash: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, int(time.time())),
        )


def update_user(old_username: str, username: str, password_hash: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET username = ?, password_hash = ? WHERE username = ?",
            (username, password_hash, old_username),
        )


# --- tunnels ---------------------------------------------------------------

def _row_to_tunnel(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "created_at": row["created_at"],
        **json.loads(row["config"]),
    }


def list_tunnels(kind: str) -> list:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tunnels WHERE kind = ? ORDER BY id", (kind,)
        ).fetchall()
    return [_row_to_tunnel(r) for r in rows]


def get_tunnel(kind: str, tunnel_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM tunnels WHERE kind = ? AND id = ?", (kind, tunnel_id)
        ).fetchone()
    return _row_to_tunnel(row) if row else None


def add_tunnel(kind: str, name: str, cfg: dict) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO tunnels (kind, name, config, created_at) VALUES (?, ?, ?, ?)",
            (kind, name, json.dumps(cfg), int(time.time())),
        )
        return int(cur.lastrowid)


def update_tunnel(kind: str, tunnel_id: int, name: str, cfg: dict) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE tunnels SET name = ?, config = ? WHERE kind = ? AND id = ?",
            (name, json.dumps(cfg), kind, tunnel_id),
        )


def delete_tunnel(kind: str, tunnel_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM tunnels WHERE kind = ? AND id = ?", (kind, tunnel_id))


# --- ssh keys --------------------------------------------------------------

def list_keys() -> list:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM ssh_keys ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_key(key_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM ssh_keys WHERE id = ?", (key_id,)).fetchone()
    return dict(row) if row else None


def get_key_by_name(name: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM ssh_keys WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def add_key(name: str, public_key: str, fingerprint: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO ssh_keys (name, public_key, fingerprint, created_at)"
            " VALUES (?, ?, ?, ?)",
            (name, public_key, fingerprint, int(time.time())),
        )
        return int(cur.lastrowid)


def delete_key(key_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM ssh_keys WHERE id = ?", (key_id,))


# --- misc ------------------------------------------------------------------

def any_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default
