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
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_LLM_SETTINGS: Dict[str, str] = {
    "provider": DEFAULT_LLM_PROVIDER,
    "api_key": "",
    "base_url": "",
    "text_model": "gemini-2.5-pro",
    "embed_model": "text-embedding-004",
}

PROVIDER_DEFAULTS: Dict[str, Dict[str, str]] = {
    "gemini": {
        "base_url": "",
        "text_model": "gemini-2.5-pro",
        "embed_model": "text-embedding-004",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "text_model": "openai/gpt-4o-mini",
        "embed_model": "openai/text-embedding-3-small",
    },
    "ollama": {
        "base_url": "http://localhost:11434/api",
        "text_model": "llama3.2",
        "embed_model": "nomic-embed-text",
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
    if env_base_url:
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


def save_llm_settings(settings: Dict[str, Any]) -> None:
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
