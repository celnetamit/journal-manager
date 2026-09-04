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
import json
import re
import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

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
            password_hash TEXT,
            email TEXT,
            role TEXT DEFAULT 'member',
            auth_provider TEXT DEFAULT 'password'
        )"""
    )
    for col, decl in (
        ("email", "TEXT"),
        ("role", "TEXT DEFAULT 'member'"),
        ("auth_provider", "TEXT DEFAULT 'password'"),
        # NULL means "use the deployment default". 0 means "no limit" — an explicit
        # exemption, distinguishable from "nobody has set this yet".
        ("monthly_token_cap", "INTEGER"),
    ):
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
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
            redline_path TEXT,
            journal_report_path TEXT,
            review_report_path TEXT,
            ai_review_path TEXT,
            jats_path TEXT,
            plagiarism_report_path TEXT
        )"""
    )
    # Idempotent column adds (SQLite has no IF NOT EXISTS for columns)
    for col, decl in (
        ("user_id", "INTEGER"),
        ("redline_path", "TEXT"),
        ("journal_report_path", "TEXT"),
        ("review_report_path", "TEXT"),
        ("ai_review_path", "TEXT"),
        ("jats_path", "TEXT"),
        ("plagiarism_report_path", "TEXT"),
    ):
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
    c.execute(
        """CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            attempted_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS user_house_rules (
            user_id INTEGER PRIMARY KEY,
            disabled_groups TEXT DEFAULT '[]',
            custom_rules TEXT DEFAULT ''
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT,
            input_path TEXT,
            options_json TEXT,
            status TEXT DEFAULT 'queued',
            progress REAL DEFAULT 0,
            stage TEXT DEFAULT 'Queued',
            result_json TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            finished_at TEXT
        )"""
    )
    for col, decl in (
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("cached_tokens", "INTEGER DEFAULT 0"),
        ("llm_calls", "INTEGER DEFAULT 0"),
        # REAL and nullable. NULL means the provider did not price the call, which
        # is not the same as zero and must never be shown as "free".
        ("cost_usd", "REAL"),
        ("usage_json", "TEXT"),
    ):
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass


def _ensure_schema_pg(cur: Any) -> None:
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'member',
            auth_provider TEXT DEFAULT 'password'
        )"""
    )
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'member'")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider TEXT DEFAULT 'password'")
    # NULL = use the deployment default; 0 = explicitly unlimited.
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_token_cap INTEGER")
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
            redline_path TEXT,
            journal_report_path TEXT,
            review_report_path TEXT,
            ai_review_path TEXT,
            jats_path TEXT,
            plagiarism_report_path TEXT
        )"""
    )
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS user_id INTEGER")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS redline_path TEXT")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS journal_report_path TEXT")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS review_report_path TEXT")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS ai_review_path TEXT")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS jats_path TEXT")
    cur.execute("ALTER TABLE process_logs ADD COLUMN IF NOT EXISTS plagiarism_report_path TEXT")
    cur.execute(
        """CREATE TABLE IF NOT EXISTS login_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS login_attempts (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            attempted_at TIMESTAMPTZ DEFAULT now()
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS user_house_rules (
            user_id INTEGER PRIMARY KEY,
            disabled_groups TEXT DEFAULT '[]',
            custom_rules TEXT DEFAULT ''
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            filename TEXT,
            input_path TEXT,
            options_json TEXT,
            status TEXT DEFAULT 'queued',
            progress DOUBLE PRECISION DEFAULT 0,
            stage TEXT DEFAULT 'Queued',
            result_json TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )"""
    )
    for col, decl in (
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("cached_tokens", "INTEGER DEFAULT 0"),
        ("llm_calls", "INTEGER DEFAULT 0"),
        # Nullable on purpose: NULL is "the provider reported no cost", not zero.
        ("cost_usd", "DOUBLE PRECISION"),
        ("usage_json", "TEXT"),
    ):
        cur.execute(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {col} {decl}")


# --- Password hashing ---

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _looks_like_sha256(h: str) -> bool:
    return bool(h) and bool(_SHA256_RE.match(h))


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_sha256(pw: str, stored: str) -> bool:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest() == stored


# --- Time helpers (cross-engine) ---

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ts_param(dt: datetime) -> Any:
    """Bind a cutoff timestamp the way each engine stores it.

    Postgres columns are TIMESTAMPTZ (accept a tz-aware datetime); SQLite
    stores datetime('now') as a UTC 'YYYY-MM-DD HH:MM:SS' string, which
    compares lexicographically in the same format.
    """
    if _is_postgres():
        return dt
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --- Login throttling (brute-force resistance) ---

def _record_failed_login(cur: Any, username: str) -> None:
    cur.execute(
        "INSERT INTO login_attempts (username) VALUES (%s)"
        if _is_postgres() else
        "INSERT INTO login_attempts (username) VALUES (?)",
        (username,),
    )


def _clear_login_attempts(cur: Any, username: str) -> None:
    cur.execute(
        "DELETE FROM login_attempts WHERE username=%s"
        if _is_postgres() else
        "DELETE FROM login_attempts WHERE username=?",
        (username,),
    )


def is_locked_out(username: str) -> bool:
    """True if too many failed logins for this username inside the window."""
    max_attempts = app_config.login_max_attempts()
    if not username or max_attempts <= 0:
        return False
    cutoff = _ts_param(_now_utc() - timedelta(minutes=app_config.login_lockout_minutes()))
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n FROM login_attempts "
            "WHERE username=%s AND attempted_at > %s"
            if _is_postgres() else
            "SELECT COUNT(*) AS n FROM login_attempts "
            "WHERE username=? AND attempted_at > ?",
            (username, cutoff),
        )
        row = cur.fetchone()
        return bool(row) and int(row["n"]) >= max_attempts


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

    if is_locked_out(username):
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

        def _fail() -> None:
            _record_failed_login(cur, username)
            conn.commit()

        if row is None:
            _fail()
            return None

        user_id = row["id"]
        stored = row["password_hash"] or ""

        if _looks_like_sha256(stored):
            if _verify_sha256(pw, stored):
                _upgrade_hash(cur, user_id, pw)
                _clear_login_attempts(cur, username)
                conn.commit()
                return user_id
            _fail()
            return None

        try:
            if bcrypt.checkpw(pw.encode("utf-8"), stored.encode("utf-8")):
                _clear_login_attempts(cur, username)
                conn.commit()
                return user_id
        except ValueError:
            # Stored hash is malformed
            _fail()
            return None
        _fail()
        return None


def _upgrade_hash(cur: Any, user_id: int, pw: str) -> None:
    upd = (
        "UPDATE users SET password_hash=%s WHERE id=%s"
        if _is_postgres() else
        "UPDATE users SET password_hash=? WHERE id=?"
    )
    cur.execute(upd, (hash_pw(pw), user_id))


# --- Google SSO / roles ---

# Role hierarchy: a higher rank includes every power of the ranks below it.
ROLE_RANK = {"member": 0, "admin": 1, "superadmin": 2}


def _max_role(*roles: Optional[str]) -> str:
    """Return the highest-privilege role among the inputs (never downgrades)."""
    best = "member"
    for r in roles:
        if r and ROLE_RANK.get(r, 0) > ROLE_RANK.get(best, 0):
            best = r
    return best


def _config_role(email: str) -> Optional[str]:
    """Role granted purely by the env allowlists (superadmin outranks admin)."""
    if app_config.is_superadmin_email(email):
        return "superadmin"
    if app_config.is_admin_email(email):
        return "admin"
    return None


def get_or_create_oauth_user(email: str, name: str = "") -> Optional[int]:
    """Map a verified SSO email to a users row (creating it on first login).
    The username is the email; admins/superadmins (per config allowlists) are
    promoted automatically, and an existing higher role is never downgraded."""
    email = (email or "").strip().lower()
    if not email:
        return None
    cfg_role = _config_role(email)
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT id, role FROM users WHERE username={ph}", (email,))
        row = cur.fetchone()
        if row:
            r = dict(row)
            uid = r["id"]
            new_role = _max_role(cfg_role, r.get("role"))
            cur.execute(
                f"UPDATE users SET email={ph}, auth_provider='google', role={ph} WHERE id={ph}",
                (email, new_role, uid),
            )
            conn.commit()
            return uid
        cur.execute(
            f"""INSERT INTO users (username, password_hash, email, role, auth_provider)
                VALUES ({ph},{ph},{ph},{ph},'google')""",
            (email, "", email, cfg_role or "member"),
        )
        conn.commit()
        cur.execute(f"SELECT id FROM users WHERE username={ph}", (email,))
        return dict(cur.fetchone())["id"]


def get_user_role(user_id: Optional[int]) -> str:
    if user_id is None:
        return "member"
    ph = "%s" if _is_postgres() else "?"
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT role FROM users WHERE id={ph}", (user_id,))
            row = cur.fetchone()
            return (dict(row).get("role") if row else None) or "member"
    except Exception:
        return "member"


def is_admin(user_id: Optional[int]) -> bool:
    """True for both admins and superadmins (superadmin includes admin powers)."""
    return get_user_role(user_id) in {"admin", "superadmin"}


def is_superadmin(user_id: Optional[int]) -> bool:
    return get_user_role(user_id) == "superadmin"


def set_user_role(user_id: int, role: str) -> None:
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET role={ph} WHERE id={ph}", (role, user_id))
        conn.commit()


def ensure_seed_admin() -> None:
    """If SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD are set, upsert a break-glass
    password admin. Safe to call on every startup."""
    creds = app_config.seed_admin_credentials()
    if not creds:
        return
    username, pw = creds
    ph = "%s" if _is_postgres() else "?"
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT id FROM users WHERE username={ph}", (username,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    f"""UPDATE users SET password_hash={ph}, role='admin',
                        auth_provider='password' WHERE id={ph}""",
                    (hash_pw(pw), dict(row)["id"]),
                )
            else:
                cur.execute(
                    f"""INSERT INTO users (username, password_hash, role, auth_provider)
                        VALUES ({ph},{ph},'admin','password')""",
                    (username, hash_pw(pw)),
                )
            conn.commit()
    except Exception as e:
        print(f"[auth.ensure_seed_admin] error: {e}")


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
        _purge_expired_tokens(cur)
        conn.commit()
    return token


def _purge_expired_tokens(cur: Any) -> None:
    """Best-effort cleanup so expired tokens don't accumulate."""
    ttl_days = app_config.login_token_ttl_days()
    if ttl_days <= 0:
        return
    cutoff = _ts_param(_now_utc() - timedelta(days=ttl_days))
    cur.execute(
        "DELETE FROM login_tokens WHERE created_at <= %s"
        if _is_postgres() else
        "DELETE FROM login_tokens WHERE created_at <= ?",
        (cutoff,),
    )


def resolve_login_token(token: str) -> Optional[dict]:
    """Look up a login token and return the linked user if valid."""
    if not token:
        return None
    token_hash = _token_hash(token)
    ttl_days = app_config.login_token_ttl_days()
    cutoff = _ts_param(_now_utc() - timedelta(days=ttl_days)) if ttl_days > 0 else None
    with _connect() as conn:
        cur = conn.cursor()
        if cutoff is None:
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
        else:
            cur.execute(
                """SELECT u.id, u.username
                   FROM login_tokens lt
                   JOIN users u ON u.id = lt.user_id
                   WHERE lt.token_hash=%s AND lt.created_at > %s"""
                if _is_postgres() else
                """SELECT u.id, u.username
                   FROM login_tokens lt
                   JOIN users u ON u.id = lt.user_id
                   WHERE lt.token_hash=? AND lt.created_at > ?""",
                (token_hash, cutoff),
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
    journal_report_path: str = "",
    review_report_path: str = "",
    ai_review_path: str = "",
    jats_path: str = "",
    plagiarism_report_path: str = "",
) -> None:
    sql = (
        """INSERT INTO process_logs
           (user_id, filename, paragraphs_count, edit_style, ref_style,
            language, duration_seconds, status, error_message, redline_path,
            journal_report_path, review_report_path, ai_review_path, jats_path,
            plagiarism_report_path)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        if _is_postgres() else
        """INSERT INTO process_logs
           (user_id, filename, paragraphs_count, edit_style, ref_style,
            language, duration_seconds, status, error_message, redline_path,
            journal_report_path, review_report_path, ai_review_path, jats_path,
            plagiarism_report_path)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    )
    params: Tuple[Any, ...] = (
        user_id, filename, paragraphs_count, edit_style, ref_style,
        language, duration_seconds, status, error_message, redline_path,
        journal_report_path, review_report_path, ai_review_path, jats_path,
        plagiarism_report_path,
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
            """SELECT timestamp, filename, edit_style, status, redline_path,
                      journal_report_path, review_report_path, ai_review_path, jats_path,
                      plagiarism_report_path
               FROM process_logs WHERE user_id=%s ORDER BY timestamp DESC"""
            if _is_postgres() else
            """SELECT timestamp, filename, edit_style, status, redline_path,
                      journal_report_path, review_report_path, ai_review_path, jats_path,
                      plagiarism_report_path
               FROM process_logs WHERE user_id=? ORDER BY timestamp DESC""",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# --- Background job queue ---

def _now_sql() -> str:
    return "now()" if _is_postgres() else "datetime('now')"


def create_job(user_id: int, filename: str, input_path: str, options_json: str) -> int:
    """Enqueue a processing job. Returns the new job id."""
    with _connect() as conn:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                """INSERT INTO jobs (user_id, filename, input_path, options_json, status, stage)
                   VALUES (%s,%s,%s,%s,'queued','Queued') RETURNING id""",
                (user_id, filename, input_path, options_json),
            )
            job_id = cur.fetchone()["id"]
        else:
            cur.execute(
                """INSERT INTO jobs (user_id, filename, input_path, options_json, status, stage)
                   VALUES (?,?,?,?,'queued','Queued')""",
                (user_id, filename, input_path, options_json),
            )
            job_id = cur.lastrowid
        conn.commit()
        return job_id


def claim_next_job() -> Optional[dict]:
    """Atomically move the oldest queued job to 'running' and return it.

    Safe for multiple concurrent workers. On Postgres we use a single
    UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED) statement so two
    workers never grab the same row and never block each other. On SQLite
    (single writer) the select-then-conditional-update is sufficient."""
    with _connect() as conn:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                f"""UPDATE jobs SET status='running', stage='Starting',
                        started_at={_now_sql()}
                    WHERE id = (
                        SELECT id FROM jobs WHERE status='queued'
                        ORDER BY created_at, id
                        FOR UPDATE SKIP LOCKED LIMIT 1
                    )
                    RETURNING id"""
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return None
            return get_job(dict(row)["id"])

        cur.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at, id LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        jid = dict(row)["id"]
        cur.execute(
            "UPDATE jobs SET status='running', stage='Starting', "
            "started_at=datetime('now') WHERE id=? AND status='queued'",
            (jid,),
        )
        claimed = cur.rowcount
        conn.commit()
        if not claimed:
            return None
    return get_job(jid)


def update_job_progress(job_id: int, progress: float, stage: str) -> None:
    # Only a still-running job gets progress updates — never resurrect the stage
    # of a job that was cancelled (status flipped away from 'running').
    ph = "%s" if _is_postgres() else "?"
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE jobs SET progress={ph}, stage={ph} "
                f"WHERE id={ph} AND status='running'",
                (float(progress), stage, job_id),
            )
            conn.commit()
    except Exception as e:
        print(f"[auth.update_job_progress] error: {e}")


def job_is_cancelled(job_id: int) -> bool:
    """True if the job is no longer in the 'running' state — i.e. it was
    cancelled (or otherwise terminated) out from under the worker. Used by the
    worker to stop cooperatively. On a DB error we return False so a transient
    glitch never aborts a healthy job."""
    ph = "%s" if _is_postgres() else "?"
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT status FROM jobs WHERE id={ph}", (job_id,))
            row = cur.fetchone()
            if not row:
                return True  # row vanished -> nothing to keep working on
            return dict(row)["status"] != "running"
    except Exception as e:
        print(f"[auth.job_is_cancelled] error: {e}")
        return False


def complete_job(job_id: int, result_json: str) -> None:
    # Guard on status='running' so a job cancelled while the worker was finishing
    # is NOT overwritten back to 'done'.
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE jobs SET status='done', progress=1.0, stage='Complete',
                result_json={ph}, finished_at={_now_sql()}
                WHERE id={ph} AND status='running'""",
            (result_json, job_id),
        )
        conn.commit()


def fail_job(job_id: int, error_message: str) -> None:
    # Guard on status='running' so a cancelled job keeps its 'Cancelled' state
    # rather than being overwritten with a generic error.
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE jobs SET status='error', stage='Error', error_message={ph},
                finished_at={_now_sql()} WHERE id={ph} AND status='running'""",
            (error_message, job_id),
        )
        conn.commit()


def record_job_usage(job_id: int, snapshot: Dict[str, Any]) -> None:
    """Store what a job spent. Called on every path — done, failed or cancelled.

    Not guarded on status, unlike `complete_job` and `fail_job`: those two guard on
    `running` so a cancelled job is not resurrected, but a cancelled job still spent
    whatever it spent before it stopped, and that has to be on the record.
    """
    if not snapshot:
        return
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE jobs SET prompt_tokens={ph}, completion_tokens={ph},
                cached_tokens={ph}, llm_calls={ph}, cost_usd={ph}, usage_json={ph}
                WHERE id={ph}""",
            (int(snapshot.get("prompt_tokens") or 0),
             int(snapshot.get("completion_tokens") or 0),
             int(snapshot.get("cached_tokens") or 0),
             int(snapshot.get("calls") or 0),
             snapshot.get("cost_usd"),           # None stays None, never 0
             json.dumps(snapshot),
             job_id),
        )
        conn.commit()


def month_usage(user_id: int, month: Optional[str] = None) -> Dict[str, Any]:
    """This user's totals for a calendar month (default: the current one).

    Counts every job the user started that month, whatever its status. A job that
    failed still spent its tokens, and a quota that only counted successes could be
    walked straight past by submitting work that fails.
    """
    ph = "%s" if _is_postgres() else "?"
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    with _connect() as conn:
        cur = conn.cursor()
        if _is_postgres():
            where = f"user_id={ph} AND to_char(created_at, 'YYYY-MM')={ph}"
        else:
            where = f"user_id={ph} AND substr(created_at, 1, 7)={ph}"
        cur.execute(
            f"""SELECT COUNT(*) AS jobs,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                       SUM(cost_usd) AS cost_usd
                FROM jobs WHERE {where}""",
            (user_id, month),
        )
        row = cur.fetchone() or {}
        row = dict(row)
    prompt = int(row.get("prompt_tokens") or 0)
    completion = int(row.get("completion_tokens") or 0)
    return {
        "month": month,
        "jobs": int(row.get("jobs") or 0),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens": int(row.get("cached_tokens") or 0),
        "total_tokens": prompt + completion,
        # SUM over all-NULL is NULL, which is the honest answer: nothing was priced.
        "cost_usd": row.get("cost_usd"),
    }


def get_job(job_id: int) -> Optional[dict]:
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM jobs WHERE id={ph}", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_user_jobs(user_id: int, limit: int = 15) -> List[dict]:
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT id, filename, status, progress, stage, created_at, finished_at
                FROM jobs WHERE user_id={ph} ORDER BY created_at DESC, id DESC LIMIT {ph}""",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def requeue_running_jobs() -> int:
    """On startup, return jobs left 'running' by a crashed/restarted process back
    to 'queued' so the worker can pick them up again. Returns count requeued."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE jobs SET status='queued', stage='Re-queued', progress=0, started_at=NULL "
                "WHERE status='running'"
            )
            n = cur.rowcount
            conn.commit()
            return n or 0
    except Exception as e:
        print(f"[auth.requeue_running_jobs] error: {e}")
        return 0


# --- Per-user publisher / house rules ---

def get_user_house_rules(user_id: Optional[int]) -> dict:
    """Return {'disabled_groups': [...], 'custom_rules': '...'} for the user.
    Defaults to all built-in rules enabled and no custom rules."""
    default = {"disabled_groups": [], "custom_rules": ""}
    if user_id is None:
        return default
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT disabled_groups, custom_rules FROM user_house_rules WHERE user_id=%s"
                if _is_postgres() else
                "SELECT disabled_groups, custom_rules FROM user_house_rules WHERE user_id=?",
                (user_id,),
            )
            row = cur.fetchone()
    except Exception as e:
        print(f"[auth.get_user_house_rules] error: {e}")
        return default
    if not row:
        return default
    row = dict(row)
    try:
        disabled = json.loads(row.get("disabled_groups") or "[]")
        if not isinstance(disabled, list):
            disabled = []
    except Exception:
        disabled = []
    return {"disabled_groups": disabled, "custom_rules": row.get("custom_rules") or ""}


def save_user_house_rules(
    user_id: int, disabled_groups: List[str], custom_rules: str,
) -> None:
    payload = json.dumps(list(disabled_groups or []))
    custom_rules = custom_rules or ""
    sql = (
        """INSERT INTO user_house_rules (user_id, disabled_groups, custom_rules)
           VALUES (%s,%s,%s)
           ON CONFLICT (user_id) DO UPDATE
           SET disabled_groups=EXCLUDED.disabled_groups,
               custom_rules=EXCLUDED.custom_rules"""
        if _is_postgres() else
        """INSERT INTO user_house_rules (user_id, disabled_groups, custom_rules)
           VALUES (?,?,?)
           ON CONFLICT(user_id) DO UPDATE
           SET disabled_groups=excluded.disabled_groups,
               custom_rules=excluded.custom_rules"""
    )
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, (user_id, payload, custom_rules))
            conn.commit()
    except Exception as e:
        print(f"[auth.save_user_house_rules] error: {e}")


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


# --- Superadmin: platform-wide tracing & management ---------------------------
#
# These helpers expose non-anonymized, cross-user data and mutating controls.
# They are only ever reached from the superadmin-gated dashboard in app.py.

def fetch_all_users() -> List[dict]:
    """Every user with role/provider plus derived activity (job count + last
    seen), newest activity first. Used by the superadmin user-management view."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT u.id, u.username, u.email, u.role, u.auth_provider,
                      COUNT(p.id) AS job_count, MAX(p.timestamp) AS last_active
               FROM users u
               LEFT JOIN process_logs p ON p.user_id = u.id
               GROUP BY u.id, u.username, u.email, u.role, u.auth_provider
               ORDER BY (MAX(p.timestamp) IS NULL), MAX(p.timestamp) DESC, u.id DESC"""
        )
        return [dict(r) for r in cur.fetchall()]


def count_superadmins() -> int:
    """Number of superadmin accounts (used to block demoting the last one)."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role='superadmin'")
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def role_counts() -> Dict[str, int]:
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT role, COUNT(*) AS n FROM users GROUP BY role")
        return {(dict(r)["role"] or "member"): int(dict(r)["n"]) for r in cur.fetchall()}


def fetch_all_jobs(limit: int = 100, status: Optional[str] = None) -> List[dict]:
    """Every queue job across all users (optionally filtered by status), with the
    owning username joined in. Newest first."""
    ph = "%s" if _is_postgres() else "?"
    clause = f" WHERE j.status={ph}" if status else ""
    params: Tuple[Any, ...] = (status, limit) if status else (limit,)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT j.id, j.user_id, u.username, j.filename, j.status, j.progress,
                       j.stage, j.created_at, j.started_at, j.finished_at, j.error_message
                FROM jobs j LEFT JOIN users u ON u.id = j.user_id
                {clause}
                ORDER BY j.created_at DESC, j.id DESC LIMIT {ph}""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def job_queue_stats() -> Dict[str, int]:
    """Counts of jobs grouped by status (queued / running / done / error / ...)."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {dict(r)["status"]: int(dict(r)["n"]) for r in cur.fetchall()}


def requeue_job(job_id: int) -> bool:
    """Send any job back to 'queued' so the worker re-runs it. Returns success."""
    ph = "%s" if _is_postgres() else "?"
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""UPDATE jobs SET status='queued', stage='Re-queued', progress=0,
                    started_at=NULL, finished_at=NULL, error_message=NULL WHERE id={ph}""",
                (job_id,),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        print(f"[auth.requeue_job] error: {e}")
        return False


def cancel_job(job_id: int) -> bool:
    """Mark a queued/running job as cancelled so it stops being processed."""
    ph = "%s" if _is_postgres() else "?"
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""UPDATE jobs SET status='error', stage='Cancelled',
                    error_message='Cancelled by superadmin', finished_at={_now_sql()}
                    WHERE id={ph} AND status IN ('queued','running')""",
                (job_id,),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        print(f"[auth.cancel_job] error: {e}")
        return False


def fetch_process_logs(limit: int = 200, user_id: Optional[int] = None,
                       status: Optional[str] = None, search: str = "") -> List[dict]:
    """Full (non-anonymized) audit trail across users, with owning username and
    optional filters by user, status, or filename substring. Newest first."""
    ph = "%s" if _is_postgres() else "?"
    where: List[str] = []
    params: List[Any] = []
    if user_id is not None:
        where.append(f"p.user_id={ph}")
        params.append(user_id)
    if status:
        where.append(f"p.status={ph}")
        params.append(status)
    if search:
        where.append(f"LOWER(p.filename) LIKE {ph}")
        params.append(f"%{search.strip().lower()}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.id, p.timestamp, p.user_id, u.username, p.filename,
                       p.paragraphs_count, p.edit_style, p.ref_style, p.language,
                       p.duration_seconds, p.status, p.error_message
                FROM process_logs p LEFT JOIN users u ON u.id = p.user_id
                {clause}
                ORDER BY p.timestamp DESC, p.id DESC LIMIT {ph}""",
            tuple(params),
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_recent_login_attempts(limit: int = 100) -> List[dict]:
    """Recent failed-login records (used for the security view)."""
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT username, attempted_at FROM login_attempts
                ORDER BY attempted_at DESC LIMIT {ph}""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def locked_out_usernames() -> List[str]:
    """Usernames currently locked out under the failed-login policy."""
    max_attempts = app_config.login_max_attempts()
    if max_attempts <= 0:
        return []
    cutoff = _ts_param(_now_utc() - timedelta(minutes=app_config.login_lockout_minutes()))
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT username, COUNT(*) AS n FROM login_attempts
                WHERE attempted_at > {ph}
                GROUP BY username HAVING COUNT(*) >= {max_attempts}""",
            (cutoff,),
        )
        return [dict(r)["username"] for r in cur.fetchall()]


def clear_login_lockout(username: str) -> None:
    """Superadmin override: clear the failed-login record for a username."""
    if not username:
        return
    with _connect() as conn:
        cur = conn.cursor()
        _clear_login_attempts(cur, username)
        conn.commit()


def db_table_counts() -> Dict[str, int]:
    """Row counts per table for the system-health view."""
    out: Dict[str, int] = {}
    with _connect() as conn:
        cur = conn.cursor()
        for table in ("users", "process_logs", "jobs", "login_tokens", "login_attempts"):
            try:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                row = cur.fetchone()
                out[table] = int(row["n"]) if row else 0
            except Exception:
                out[table] = -1
    return out


# --- Monthly usage quota -------------------------------------------------------
#
# Named as the launch blocker: nothing stopped one user submitting a 500-page file
# twenty times. The cap is measured in tokens, not in money, because tokens are always
# reported and a cost is not — a limit that silently stops being enforced whenever the
# provider omits a price is not a limit.

def default_token_cap() -> int:
    """Deployment-wide monthly cap. 0 disables the quota entirely."""
    try:
        return max(0, int(os.getenv("MONTHLY_TOKEN_CAP", "0")))
    except (TypeError, ValueError):
        return 0


def token_cap_for(user_id: Optional[int]) -> int:
    """This user's monthly cap. 0 means no limit.

    Admins are exempt. That is 3.4 of the plan and not a convenience: the person who
    has to clear a stuck queue at midnight must never be the person locked out by
    their own quota.
    """
    if user_id is None:
        return 0
    if is_admin(user_id) or is_superadmin(user_id):
        return 0
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT monthly_token_cap FROM users WHERE id={ph}", (user_id,))
        row = cur.fetchone()
    if row is not None:
        value = dict(row).get("monthly_token_cap")
        if value is not None:              # 0 here is a deliberate exemption
            return max(0, int(value))
    return default_token_cap()


def set_token_cap(user_id: int, cap: Optional[int]) -> None:
    """Set or clear one user's cap. `None` restores the deployment default."""
    ph = "%s" if _is_postgres() else "?"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET monthly_token_cap={ph} WHERE id={ph}",
                    (None if cap is None else max(0, int(cap)), user_id))
        conn.commit()


def quota_check(user_id: Optional[int]) -> Dict[str, Any]:
    """Whether this user may start another job, and the numbers behind the answer.

    Returns `allowed`, plus `used`, `cap` and a `message`. The message is the point:
    a refusal that just says no leaves the user with nothing to do about it, so it
    names the number, the limit and when it resets.
    """
    cap = token_cap_for(user_id)
    used = month_usage(user_id)["total_tokens"] if user_id is not None else 0
    if cap <= 0:
        return {"allowed": True, "used": used, "cap": 0, "message": ""}
    if used < cap:
        return {"allowed": True, "used": used, "cap": cap, "message": ""}
    now = datetime.now(timezone.utc)
    resets = f"{now.year + (now.month == 12)}-{(now.month % 12) + 1:02d}-01"
    return {
        "allowed": False, "used": used, "cap": cap,
        "message": (
            f"You have used {used:,} of your {cap:,} tokens for {now.strftime('%B')}. "
            f"The allowance resets on {resets}. Ask an administrator if you need more."
        ),
    }
