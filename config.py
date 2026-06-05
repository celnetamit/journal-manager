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
from pathlib import Path
from typing import Optional


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


def config_path() -> Path:
    return Path(os.environ.get("CONFIG_FILE", str(data_dir() / "config.json")))


def journals_embedded_path() -> Path:
    """Embedded journals catalogue. Falls back to repo path in dev."""
    env = os.environ.get("JOURNALS_EMBEDDED_FILE")
    if env:
        return Path(env)
    local = Path("journals_embedded.json")
    if local.exists():
        return local
    return data_dir() / "journals_embedded.json"


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
    """Read the Gemini API key from env first, then config.json."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key

    cfg = config_path()
    if cfg.exists():
        try:
            with cfg.open("r") as f:
                return json.load(f).get("gemini_api_key", "") or ""
        except (OSError, json.JSONDecodeError):
            return ""
    return ""


def save_gemini_api_key(key: str) -> None:
    cfg = config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    with cfg.open("w") as f:
        json.dump({"gemini_api_key": key}, f)


# --- App ---

def log_job_to_stdout() -> bool:
    """In production we may want to also tee to stdout for container log shipping."""
    return os.environ.get("LOG_TO_STDOUT", "0") == "1"


# --- Gemini client (lazy import to keep import time low) ---

_gemini_client = None


def get_gemini_client(api_key: Optional[str] = None):
    """Return a singleton google.genai.Client. Configures from env or override."""
    global _gemini_client
    if _gemini_client is not None and api_key is None:
        return _gemini_client

    key = api_key or get_gemini_api_key()
    if not key:
        raise RuntimeError(
            "Gemini API key not configured. Set GEMINI_API_KEY env var or "
            "save one via the in-app sidebar (writes to config.json)."
        )

    from google import genai
    client = genai.Client(api_key=key)
    if api_key is None:
        _gemini_client = client
    return client
