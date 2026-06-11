"""Authentication and analytics logging.

Backed by Postgres when DATABASE_URL is set, otherwise by a local SQLite file
under DATA_DIR/analytics.db. The same SQL is run on both engines — the
only place we branch is in the connect helper.

Password hashing:
  - New users: bcrypt.
  - Legacy users (sha256 hex): on successful legacy login, the hash is
    transparently upgraded to bcrypt. No data loss.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import secrets
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional, Tuple

import bcrypt

import config as app_config


# --- Connection management ---

def _is_postgres() -> bool:
    return app_config.database_url().startswith(("postgres://", "postgresql://"))


@contextmanager
def _connect() -> Iterator[Any]:
    """Yield a DB-API 2.0 connection. Auto-creates schema on first use."""
    if _is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        url = app_config.database_url()
        # psycopg accepts both postgres:// and postgresql://
        with psycopg.connect(url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                _ensure_schema_pg(cur)
            conn.commit()
            yield conn
    else:
        path = str(app_config.data_dir() / "analytics.db")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            _ensure_schema_sqlite(conn)
            conn.commit()
            yield conn
        finally:
            conn.close()


def _ensure_schema_sqlite(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS process_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            filename TEXT,
            paragraphs_count INTEGER,
            edit_style TEXT,
            ref_style TEXT,
            language TEXT,
            duration_seconds REAL,
            status TEXT,
            error_message TEXT,
            user_id INTEGER,
            redline_path TEXT
        )"""
    )
    # Idempotent column adds (SQLite has no IF NOT EXISTS for columns)
    for col, decl in (("user_id", "INTEGER"), ("redline_path", "TEXT")):
        try:
            c.execute(f"ALTER TABLE process_logs ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    c.execute(
        """CREATE TABLE IF NOT EXISTS login_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )


def _ensure_schema_pg(cur: Any) -> None:
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS process_logs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ DEFAULT now(),
            filename TEXT,
            paragraphs_count INTEGER,
            edit_style TEXT,
            ref_style TEXT,
            language TEXT,
            duration_seconds DOUBLE PRECISION,
            status TEXT,
            error_message TEXT,
            user_id INTEGER,
            redline_path TEXT
        )"""
    )
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS user_id INTEGER")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS redline_path TEXT")
    cur.execute(
        """CREATE TABLE IF NOT EXISTS login_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )"""
    )


# --- Password hashing ---

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _looks_like_sha256(h: str) -> bool:
    return bool(h) and bool(_SHA256_RE.match(h))


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_sha256(pw: str, stored: str) -> bool:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest() == stored


# --- Public API ---

def init_auth() -> None:
    """No-op kept for backwards compatibility. Schema is created lazily."""
    with _connect():
        pass


def register(username: str, pw: str) -> bool:
    if not username or not pw:
        return False
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)"
                if _is_postgres() else
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hash_pw(pw)),
            )
            conn.commit()
        return True
    except Exception:
        # Unique-constraint violation or other DB error.
        return False


def login(username: str, pw: str) -> Optional[int]:
    """Return user id on success, None on failure.

    Performs a transparent bcrypt upgrade for legacy SHA-256 hashes.
    """
    if not username or not pw:
        return None

    with _connect() as conn:
        cur = conn.cursor()
        sel = (
            "SELECT id, password_hash FROM users WHERE username=%s"
            if _is_postgres() else
            "SELECT id, password_hash FROM users WHERE username=?"
        )
        cur.execute(sel, (username,))
        row = cur.fetchone()
        if row is None:
            return None

        user_id = row["id"]
        stored = row["password_hash"] or ""

        if _looks_like_sha256(stored):
            if _verify_sha256(pw, stored):
                _upgrade_hash(cur, user_id, pw)
                conn.commit()
                return user_id
            return None

        try:
            if bcrypt.checkpw(pw.encode("utf-8"), stored.encode("utf-8")):
                return user_id
        except ValueError:
            # Stored hash is malformed
            return None
        return None


def _upgrade_hash(cur: Any, user_id: int, pw: str) -> None:
    upd = (
        "UPDATE users SET password_hash=%s WHERE id=%s"
        if _is_postgres() else
        "UPDATE users SET password_hash=? WHERE id=?"
    )
    cur.execute(upd, (hash_pw(pw), user_id))


# --- Persistent login tokens ---

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_login_token(user_id: int) -> str:
    """Create a persistent login token for browser refreshes."""
    token = secrets.token_urlsafe(32)
    token_hash = _token_hash(token)
    sql = (
        "INSERT INTO login_tokens (token_hash, user_id) VALUES (%s, %s)"
        if _is_postgres() else
        "INSERT INTO login_tokens (token_hash, user_id) VALUES (?, ?)"
    )
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (token_hash, user_id))
        conn.commit()
    return token


def resolve_login_token(token: str) -> Optional[dict]:
    """Look up a login token and return the linked user if valid."""
    if not token:
        return None
    token_hash = _token_hash(token)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT u.id, u.username
               FROM login_tokens lt
               JOIN users u ON u.id = lt.user_id
               WHERE lt.token_hash=%s"""
            if _is_postgres() else
            """SELECT u.id, u.username
               FROM login_tokens lt
               JOIN users u ON u.id = lt.user_id
               WHERE lt.token_hash=?""",
            (token_hash,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"user_id": int(row["id"]), "username": row["username"]}


def revoke_login_token(token: str) -> None:
    """Remove a persistent login token."""
    if not token:
        return
    token_hash = _token_hash(token)
    sql = (
        "DELETE FROM login_tokens WHERE token_hash=%s"
        if _is_postgres() else
        "DELETE FROM login_tokens WHERE token_hash=?"
    )
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (token_hash,))
        conn.commit()


# --- Analytics logging ---

def log_job(
    user_id: Optional[int],
    filename: str,
    paragraphs_count: int,
    edit_style: str,
    ref_style: str,
    language: str,
    duration_seconds: float,
    status: str,
    redline_path: str = "",
    error_message: str = "",
) -> None:
    sql = (
        """INSERT INTO process_logs
           (user_id, filename, paragraphs_count, edit_style, ref_style,
            language, duration_seconds, status, error_message, redline_path)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        if _is_postgres() else
        """INSERT INTO process_logs
           (user_id, filename, paragraphs_count, edit_style, ref_style,
            language, duration_seconds, status, error_message, redline_path)
           VALUES (?,?,?,?,?,?,?,?,?,?)"""
    )
    params: Tuple[Any, ...] = (
        user_id, filename, paragraphs_count, edit_style, ref_style,
        language, duration_seconds, status, error_message, redline_path,
    )
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
    except Exception as e:
        # Logging must never crash the request
        print(f"[auth.log_job] error: {e}")


def fetch_user_history(user_id: int) -> List[dict]:
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT timestamp, filename, edit_style, status, redline_path
               FROM process_logs WHERE user_id=%s ORDER BY timestamp DESC"""
            if _is_postgres() else
            """SELECT timestamp, filename, edit_style, status, redline_path
               FROM process_logs WHERE user_id=? ORDER BY timestamp DESC""",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_global_analytics() -> List[dict]:
    """Aggregated, anonymized platform-wide stats. No per-user rows."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT date_trunc('day', timestamp) AS day,
                       COUNT(*) AS jobs,
                       COALESCE(SUM(paragraphs_count), 0) AS paragraphs,
                       COALESCE(AVG(duration_seconds), 0) AS avg_duration,
                       SUM(CASE WHEN status='Success' THEN 1 ELSE 0 END) AS successes
               FROM process_logs
               GROUP BY day
               ORDER BY day DESC
               LIMIT 90"""
            if _is_postgres() else
            """SELECT substr(timestamp, 1, 10) AS day,
                       COUNT(*) AS jobs,
                       COALESCE(SUM(paragraphs_count), 0) AS paragraphs,
                       COALESCE(AVG(duration_seconds), 0) AS avg_duration,
                       SUM(CASE WHEN status='Success' THEN 1 ELSE 0 END) AS successes
               FROM process_logs
               GROUP BY day
               ORDER BY day DESC
               LIMIT 90"""
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_user_count() -> int:
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM users")
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def fetch_total_jobs() -> int:
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM process_logs")
        row = cur.fetchone()
        return int(row["n"]) if row else 0
