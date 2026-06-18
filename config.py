"""Centralized configuration: env vars, data dir, output dir, API key.

Resolution order for secrets:
  1. Environment variable (e.g. GEMINI_API_KEY)
  2. ./config.json (local dev fallback; file is gitignored)

All filesystem paths come from env vars so the container is portable
between local docker-compose and Coolify.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_LLM_SETTINGS: Dict[str, str] = {
    "provider": DEFAULT_LLM_PROVIDER,
    "api_key": "",
    "base_url": "",
    "text_model": "gemini-2.5-pro",
    "embed_model": "text-embedding-004",
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LEGACY_PROVIDER_ALIASES = {
    "ollama": "openrouter",
}

PROVIDER_DEFAULTS: Dict[str, Dict[str, str]] = {
    "gemini": {
        "base_url": "",
        "text_model": "gemini-2.5-pro",
        "embed_model": "text-embedding-004",
    },
    "openrouter": {
        "base_url": OPENROUTER_BASE_URL,
        "text_model": "openai/gpt-4o-mini",
        "embed_model": "openai/text-embedding-3-small",
    },
    "openai-compatible": {
        "base_url": "",
        "text_model": "",
        "embed_model": "",
    },
    "custom": {
        "base_url": "",
        "text_model": "",
        "embed_model": "",
    },
}


# --- Paths ---

def data_dir() -> Path:
    """Where SQLite/journal-embeddings/redlines live. Created on first use."""
    p = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_dir() -> Path:
    """Where generated redline .docx files are stored for the History tab."""
    p = Path(os.environ.get("OUTPUT_DIR", str(data_dir() / "outbound"))).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_retention_days() -> int:
    """Days to keep generated output files (redline/report/JATS) before purging.
    0 disables cleanup (keep forever)."""
    return _env_int("OUTPUT_RETENTION_DAYS", 30, minimum=0)


def purge_old_outputs(ttl_days: Optional[int] = None) -> int:
    """Delete files in the output directory older than the retention window.
    Returns the number of files removed. Never raises (best-effort cleanup)."""
    if ttl_days is None:
        ttl_days = output_retention_days()
    if ttl_days <= 0:
        return 0
    cutoff = time.time() - ttl_days * 86400
    removed = 0
    try:
        for entry in output_dir().iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError as e:
        print(f"[config.purge_old_outputs] error: {e}")
    return removed


def config_path() -> Path:
    env = os.environ.get("CONFIG_FILE", "").strip()
    if env:
        return Path(env)

    local = Path("config.json")
    if local.exists():
        return local

    return data_dir() / "config.json"


def _load_raw_config() -> Dict[str, Any]:
    cfg = config_path()
    if not cfg.exists():
        return {}
    try:
        with cfg.open("r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _provider_key(provider: Optional[str]) -> str:
    value = (provider or DEFAULT_LLM_PROVIDER).strip().lower()
    value = LEGACY_PROVIDER_ALIASES.get(value, value)
    return value if value in PROVIDER_DEFAULTS else DEFAULT_LLM_PROVIDER


def default_settings_for_provider(provider: Optional[str]) -> Dict[str, str]:
    key = _provider_key(provider)
    defaults = dict(DEFAULT_LLM_SETTINGS)
    defaults["provider"] = key
    defaults.update(PROVIDER_DEFAULTS.get(key, {}))
    return defaults


def normalize_llm_settings(data: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    raw = data or {}
    legacy_key = raw.get("gemini_api_key", "") if isinstance(raw, dict) else ""
    env_provider = os.environ.get("LLM_PROVIDER", "").strip()
    env_api_key = os.environ.get("LLM_API_KEY", "").strip()
    env_base_url = os.environ.get("LLM_BASE_URL", "").strip()
    env_text_model = (
        os.environ.get("LLM_TEXT_MODEL", "").strip()
        or os.environ.get("GEMINI_TEXT_MODEL", "").strip()
    )
    env_embed_model = (
        os.environ.get("LLM_EMBED_MODEL", "").strip()
        or os.environ.get("GEMINI_EMBED_MODEL", "").strip()
    )
    provider = _provider_key(
        env_provider or (str(raw.get("provider", DEFAULT_LLM_PROVIDER)) if isinstance(raw, dict) else DEFAULT_LLM_PROVIDER)
    )
    settings = default_settings_for_provider(provider)
    settings["provider"] = provider

    for key in ("api_key", "base_url", "text_model", "embed_model"):
        value = raw.get(key, "") if isinstance(raw, dict) else ""
        if isinstance(value, str) and value.strip():
            settings[key] = value.strip()

    if env_api_key:
        settings["api_key"] = env_api_key
    elif provider == "gemini":
        gemini_env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if gemini_env_key:
            settings["api_key"] = gemini_env_key
    if provider == "openrouter":
        settings["base_url"] = OPENROUTER_BASE_URL
    elif env_base_url and provider in {"openai-compatible", "custom"}:
        settings["base_url"] = env_base_url
    if env_text_model:
        settings["text_model"] = env_text_model
    if env_embed_model:
        settings["embed_model"] = env_embed_model

    if not settings["api_key"] and isinstance(legacy_key, str) and legacy_key.strip():
        settings["api_key"] = legacy_key.strip()

    if not settings["base_url"]:
        settings["base_url"] = default_settings_for_provider(provider)["base_url"]
    if not settings["text_model"]:
        settings["text_model"] = default_settings_for_provider(provider)["text_model"]
    if not settings["embed_model"]:
        settings["embed_model"] = default_settings_for_provider(provider)["embed_model"]
    return settings


def get_llm_settings() -> Dict[str, str]:
    return normalize_llm_settings(_load_raw_config())


def llm_config_locked() -> bool:
    """When true, LLM provider/key config is managed by the deployment only.

    Set LLM_CONFIG_LOCKED=1 in production so users can't overwrite the shared
    global config.json (provider, API key, models) from the in-app sidebar.
    """
    return os.environ.get("LLM_CONFIG_LOCKED", "0").strip().lower() in {"1", "true", "yes"}


def save_llm_settings(settings: Dict[str, Any]) -> None:
    if llm_config_locked():
        raise RuntimeError(
            "LLM settings are locked by the deployment (LLM_CONFIG_LOCKED). "
            "Configure them via environment variables instead."
        )
    cfg = config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_llm_settings(settings)
    payload: Dict[str, Any] = {
        "_comment": "Managed by the app. You can edit this file locally, but it is gitignored.",
        "provider": normalized["provider"],
        "api_key": normalized["api_key"],
        "base_url": normalized["base_url"],
        "text_model": normalized["text_model"],
        "embed_model": normalized["embed_model"],
        "gemini_api_key": normalized["api_key"],
    }
    with cfg.open("w") as f:
        json.dump(payload, f, indent=2)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip().lower()).strip("_")
    return slug or "default"


def journals_embedded_path() -> Path:
    """Embedded journals catalogue. Falls back to repo path in dev."""
    env = os.environ.get("JOURNALS_EMBEDDED_FILE")
    if env:
        return Path(env)
    local = Path("journals_embedded.json")
    if local.exists():
        return local
    return data_dir() / "journals_embedded.json"


def journals_embedded_path_for_settings(settings: Optional[Dict[str, Any]] = None) -> Path:
    env = os.environ.get("JOURNALS_EMBEDDED_FILE")
    if env:
        return Path(env)

    llm = normalize_llm_settings(settings or get_llm_settings())
    provider = llm["provider"]
    embed_model = llm["embed_model"]

    if provider == "gemini" and embed_model == DEFAULT_LLM_SETTINGS["embed_model"]:
        local = Path("journals_embedded.json")
        if local.exists():
            return local

    safe_name = _slugify(f"{provider}_{embed_model}")
    return data_dir() / f"journals_embedded_{safe_name}.json"


def journals_path() -> Path:
    env = os.environ.get("JOURNALS_FILE")
    if env:
        return Path(env)
    return Path("journals.json")


# --- Database ---

def database_url() -> str:
    """Postgres connection string.

    If unset, falls back to a SQLite file under DATA_DIR for local dev.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    sqlite_path = data_dir() / "analytics.db"
    return f"sqlite:///{sqlite_path}"


# --- Secrets ---

def get_gemini_api_key() -> str:
    """Backward-compatible API key accessor."""
    return get_llm_settings()["api_key"]


def save_gemini_api_key(key: str) -> None:
    save_llm_settings({"provider": "gemini", "api_key": key})


# --- App ---

def log_job_to_stdout() -> bool:
    """In production we may want to also tee to stdout for container log shipping."""
    return os.environ.get("LOG_TO_STDOUT", "0") == "1"


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


def login_token_ttl_days() -> int:
    """Persistent login token lifetime in days. 0 disables expiry."""
    return _env_int("LOGIN_TOKEN_TTL_DAYS", 30, minimum=0)


def login_max_attempts() -> int:
    """Failed logins allowed per username within the lockout window. 0 disables."""
    return _env_int("LOGIN_MAX_ATTEMPTS", 10, minimum=0)


def login_lockout_minutes() -> int:
    """Sliding window (minutes) over which failed logins are counted."""
    return _env_int("LOGIN_LOCKOUT_MINUTES", 15, minimum=1)


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def materialize_auth_secrets() -> bool:
    """Streamlit native auth reads Google OAuth config only from
    .streamlit/secrets.toml. To allow pure-env configuration, write that file
    from env vars (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / OAUTH_REDIRECT_URI /
    OAUTH_COOKIE_SECRET) at startup. Returns True if a file was written. A
    manually-provided secrets.toml with an [auth] section is never overwritten."""
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    redirect = os.environ.get("OAUTH_REDIRECT_URI", "").strip()
    cookie = os.environ.get("OAUTH_COOKIE_SECRET", "").strip()
    metadata = os.environ.get(
        "OAUTH_SERVER_METADATA_URL",
        "https://accounts.google.com/.well-known/openid-configuration",
    ).strip()
    if not (cid and csec and redirect and cookie):
        return False

    content = (
        "[auth]\n"
        f'redirect_uri = "{_toml_escape(redirect)}"\n'
        f'cookie_secret = "{_toml_escape(cookie)}"\n\n'
        "[auth.google]\n"
        f'client_id = "{_toml_escape(cid)}"\n'
        f'client_secret = "{_toml_escape(csec)}"\n'
        f'server_metadata_url = "{_toml_escape(metadata)}"\n'
    )
    for target in (Path(".streamlit/secrets.toml"),
                   Path.home() / ".streamlit" / "secrets.toml"):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and "[auth]" in target.read_text(encoding="utf-8"):
                return False  # respect a hand-written secrets file
            target.write_text(content, encoding="utf-8")
            return True
        except OSError as e:
            print(f"[config.materialize_auth_secrets] {target}: {e}")
            continue
    return False


def allowed_login_domains() -> List[str]:
    """Email domains permitted to sign in via Google SSO. Comma-separated env
    override; defaults to the Celnet group domains."""
    raw = os.environ.get("ALLOWED_LOGIN_DOMAINS", "celnet.in,conwiz.in,stmjournals.com")
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def admin_emails() -> List[str]:
    """Emails granted the admin role on login. Comma-separated env override."""
    raw = os.environ.get("ADMIN_EMAILS", "amit.rai@celnet.in")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def email_domain_allowed(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower()
    allowed = allowed_login_domains()
    return (not allowed) or domain in allowed


def is_admin_email(email: str) -> bool:
    return bool(email) and email.strip().lower() in admin_emails()


def seed_admin_credentials() -> Optional[tuple]:
    """Optional break-glass admin from env (SEED_ADMIN_USERNAME +
    SEED_ADMIN_PASSWORD). Returns (username, password) or None."""
    user = os.environ.get("SEED_ADMIN_USERNAME", "").strip()
    pw = os.environ.get("SEED_ADMIN_PASSWORD", "")
    return (user, pw) if user and pw else None


def jats_copyright_holder() -> str:
    """Publisher/copyright holder stamped into JATS <permissions>. Optional."""
    return os.environ.get("JATS_COPYRIGHT_HOLDER", "").strip()


def jats_license_url() -> str:
    """License URL for JATS <license xlink:href=...>, e.g. a CC-BY link. Optional."""
    return os.environ.get("JATS_LICENSE_URL", "").strip()


def jats_license_text() -> str:
    """Human-readable license statement for JATS <license-p>. Optional."""
    return os.environ.get("JATS_LICENSE_TEXT", "").strip()


# --- Gemini client (lazy import to keep import time low) ---


def get_gemini_client(api_key: Optional[str] = None):
    """Return a fresh google.genai.Client configured from env or override.

    We intentionally avoid caching the SDK client globally because Streamlit
    reruns and the Google SDK's own lifecycle can otherwise leave us with a
    closed client object on the next interaction.
    """
    key = api_key or get_gemini_api_key()
    if not key:
        raise RuntimeError(
            "Gemini API key not configured. Set GEMINI_API_KEY env var or "
            "save one via the in-app sidebar (writes to config.json)."
        )

    from google import genai
    return genai.Client(api_key=key)
