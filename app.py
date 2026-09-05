"""Streamlit entrypoint for Manuscript Editor Pro.

This module wires together:
  - `config.py`   env-var-driven configuration (DB URL, paths, API key)
  - `auth.py`     user auth + analytics (Postgres or SQLite)
  - `editor.py`   document processing pipeline (Gemini 2.5 Pro)
"""
from __future__ import annotations

import importlib
import json
import os
import re
import time
import uuid

import pandas as pd
import streamlit as st


class _InMemoryCookieManager:
    """Minimal in-memory fallback when cookie support is unavailable.

    The app can still launch and authenticate, but the "Remember me"
    option becomes session-only in this runtime.
    """

    def __init__(self, prefix: str = "") -> None:
        self._cookies: dict[str, str] = {}
        self.prefix = prefix

    def ready(self) -> bool:
        return True

    def get(self, key: str, default: str = "") -> str:
        return self._cookies.get(key, default)

    def __getitem__(self, key: str) -> str:
        return self._cookies[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._cookies[key] = value

    def __delitem__(self, key: str) -> None:
        self._cookies.pop(key, None)

    def save(self) -> None:
        pass


def _load_cookie_manager():
    """Import a real CookieManager, tolerating a missing OR broken dependency.

    The cookie stack pulls in `cryptography`, whose native backend may be
    absent or fail to load in the target runtime. Importing it can then raise
    anything from ``ModuleNotFoundError`` to a low-level pyo3
    ``PanicException`` — which subclasses ``BaseException``, not
    ``Exception``. We must not let that abort startup: the app is fully usable
    without persistent cookies (only "Remember me" degrades to session-only),
    so on any import failure we fall back to the in-memory manager.
    """
    for module_name in ("streamlit_cookies_manager", "streamlit_cookies_manager_v2"):
        try:
            module = importlib.import_module(module_name)
            return module.CookieManager, True
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:  # noqa: BLE001 - broken native dep can panic
            continue
    return _InMemoryCookieManager, False


CookieManager, COOKIE_MANAGER_AVAILABLE = _load_cookie_manager()

import auth
import config as app_config
import house_layout
import usage as _usage
import pipeline
from editor import (
    JATS_MIME,
    HOUSE_RULE_GROUPS,
    test_embedding,
    test_text_generation,
)


# Materialize Google OAuth secrets from env (before any st.secrets access) so
# the whole app can be configured purely via environment variables.
app_config.materialize_auth_secrets()

st.set_page_config(page_title="Manuscript Editor Pro", layout="wide", page_icon="📝")

cookies = CookieManager(prefix="manuscript-editor-pro/")
if not cookies.ready():
    st.stop()

auth.init_auth()
auth.ensure_seed_admin()  # optional break-glass admin from env

# Start the background job worker (idempotent — one thread per process).
pipeline.start_worker_once()

# Best-effort retention cleanup of generated output files, once per session.
if not st.session_state.get("_outputs_purged"):
    try:
        app_config.purge_old_outputs()
    except Exception as _purge_exc:  # cleanup must never block the app
        print(f"[startup] output purge skipped: {_purge_exc}")
    st.session_state["_outputs_purged"] = True

if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None
if "login_token" not in st.session_state:
    st.session_state.login_token = ""

def _clear_auth_cookie() -> None:
    try:
        del cookies["auth_token"]
        cookies.save()
    except Exception:
        pass


def _restore_auth_from_cookie() -> None:
    if st.session_state.user_id:
        return
    try:
        token = str(cookies.get("auth_token", "") or "")
    except Exception:
        # Cookie component isn't ready yet (first render, or bare-mode import
        # where st.stop() above is a no-op). Skip restore; it reruns when ready.
        return
    if not token:
        return
    resolved = auth.resolve_login_token(token)
    if not resolved:
        _clear_auth_cookie()
        return
    st.session_state.user_id = resolved["user_id"]
    st.session_state.username = resolved["username"]
    st.session_state.login_token = token


def _google_auth_configured() -> bool:
    """True when Streamlit native OIDC auth is set up in secrets.toml."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def _google_user():
    if not _google_auth_configured():
        return None
    try:
        if st.user.is_logged_in:
            return st.user
    except Exception:
        return None
    return None


def _restore_google_auth() -> None:
    """If signed in via Google, enforce the domain allowlist and map the email
    to a local user record (creating it on first login)."""
    if st.session_state.user_id:
        return
    guser = _google_user()
    if not guser:
        return
    email = getattr(guser, "email", "") or ""
    if not app_config.email_domain_allowed(email):
        st.session_state["_sso_denied_email"] = email
        return
    uid = auth.get_or_create_oauth_user(email, getattr(guser, "name", "") or "")
    if uid:
        st.session_state.user_id = uid
        st.session_state.username = email
        st.session_state.role = auth.get_user_role(uid)
        st.session_state["_sso_denied_email"] = ""


_restore_auth_from_cookie()
_restore_google_auth()
is_authenticated = bool(st.session_state.user_id)

if not is_authenticated:
    st.markdown(
        """
        <style>
          section[data-testid="stSidebar"] {
            display: none !important;
          }
          div[data-testid="stSidebarCollapsedControl"] {
            display: none !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- Sidebar: API key + style settings ---

_PROVIDER_LABELS = {
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "openai-compatible": "OpenAI-compatible",
    "custom": "Custom",
}
_PROVIDER_REQUIREMENTS = {
    "gemini": "Needs an API key. Base URL is not used.",
    "openrouter": "Uses OpenRouter's fixed OpenAI-compatible endpoint and needs an API key.",
    "openai-compatible": "Needs a base URL. API key is optional depending on the endpoint.",
    "custom": "Needs a base URL. API key and models depend on the endpoint.",
}
_API_KEY_PROVIDERS = {"gemini", "openrouter"}
_BASE_URL_PROVIDERS = {"openai-compatible", "custom"}
_OPENROUTER_BASE_URL = app_config.OPENROUTER_BASE_URL
_SIDEBAR_SETTING_KEYS = {
    "provider": "llm_sidebar_provider",
    "api_key": "llm_sidebar_api_key",
    "base_url": "llm_sidebar_base_url",
    "text_model": "llm_sidebar_text_model",
    "embed_model": "llm_sidebar_embed_model",
}
_SIDEBAR_LAST_PROVIDER_KEY = "llm_sidebar_last_provider"
_SIDEBAR_NOTICE_KEY = "llm_sidebar_notice"
_OPENROUTER_SUMMARY_KEY = "llm_openrouter_summary"


def _text_test_prompt_for_provider(provider: str) -> str:
    if provider == "openrouter":
        return (
            "Using the OpenRouter endpoint https://openrouter.ai/api/v1 and the model "
            "openai/gpt-4o-mini, write one short paragraph explaining how an "
            "OpenAI-compatible gateway helps route requests across different models."
        )
    if provider == "gemini":
        return (
            "Write one concise sentence about a scientific manuscript assistant."
        )
    return "Write one short sentence describing a manuscript editing assistant."


def _embed_test_text_for_provider(provider: str) -> str:
    if provider == "openrouter":
        return (
            "OpenRouter endpoint: https://openrouter.ai/api/v1 | Embedding model: "
            "openai/text-embedding-3-small | OpenRouter can route chat and embedding "
            "requests through an OpenAI-compatible API."
        )
    return "Machine learning helps with scientific manuscript recommendations."


def _openrouter_sidebar_settings() -> dict[str, str]:
    defaults = app_config.default_settings_for_provider("openrouter")
    return {
        "provider": "openrouter",
        "api_key": "",
        "base_url": defaults["base_url"],
        "text_model": defaults["text_model"],
        "embed_model": defaults["embed_model"],
    }


def _openrouter_summary_card() -> dict[str, str]:
    settings = _openrouter_sidebar_settings()
    return {
        "title": "OpenRouter setup",
        "provider": "OpenRouter",
        "base_url": settings["base_url"],
        "text_model": settings["text_model"],
        "embed_model": settings["embed_model"],
        "note": "These values were copied into the sidebar draft. Paste your API key, then save.",
    }


def _ensure_sidebar_draft_settings(settings: dict[str, str]) -> None:
    for field, key in _SIDEBAR_SETTING_KEYS.items():
        if key not in st.session_state:
            st.session_state[key] = settings[field]

    if _SIDEBAR_LAST_PROVIDER_KEY not in st.session_state:
        st.session_state[_SIDEBAR_LAST_PROVIDER_KEY] = settings["provider"]


def _sync_sidebar_defaults(provider: str) -> None:
    previous_provider = str(st.session_state.get(_SIDEBAR_LAST_PROVIDER_KEY, "")).strip()
    if previous_provider == provider:
        return

    defaults = app_config.default_settings_for_provider(provider)
    st.session_state[_SIDEBAR_SETTING_KEYS["base_url"]] = defaults["base_url"]
    st.session_state[_SIDEBAR_SETTING_KEYS["text_model"]] = defaults["text_model"]
    st.session_state[_SIDEBAR_SETTING_KEYS["embed_model"]] = defaults["embed_model"]
    st.session_state[_SIDEBAR_LAST_PROVIDER_KEY] = provider


def _apply_openrouter_sidebar_settings() -> None:
    st.session_state.update(_openrouter_sidebar_settings())
    st.session_state[_SIDEBAR_LAST_PROVIDER_KEY] = "openrouter"
    st.session_state[_SIDEBAR_NOTICE_KEY] = (
        "Copied OpenRouter defaults into the sidebar. Paste your API key, then save."
    )
    st.session_state[_OPENROUTER_SUMMARY_KEY] = _openrouter_summary_card()


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider.title())


def _llm_setting_errors(settings: dict[str, str]) -> list[str]:
    provider = settings.get("provider", "gemini")
    errors: list[str] = []
    if provider in _API_KEY_PROVIDERS and not settings.get("api_key", "").strip():
        errors.append(f"{_provider_label(provider)} requires an API key.")
    if provider in _BASE_URL_PROVIDERS and not settings.get("base_url", "").strip():
        errors.append(f"{_provider_label(provider)} requires a base URL.")
    if provider == "openrouter":
        base_url = settings.get("base_url", "").strip().rstrip("/")
        if base_url and base_url != _OPENROUTER_BASE_URL:
            errors.append(
                "OpenRouter should usually use https://openrouter.ai/api/v1. "
                "If you are using a proxy, double-check the endpoint."
            )
    if not settings.get("text_model", "").strip():
        errors.append("Text model cannot be empty.")
    if not settings.get("embed_model", "").strip():
        errors.append("Embedding model cannot be empty.")
    return errors

llm_settings = app_config.get_llm_settings()

if is_authenticated:
    with st.sidebar:
        _role = st.session_state.get("role") or auth.get_user_role(st.session_state.user_id)
        st.session_state.role = _role
        _badge = ""
        if _role == "superadmin":
            _badge = " · 👑 Superadmin"
        elif _role == "admin":
            _badge = " · 🛡️ Admin"
        st.success(f"Logged in as **{st.session_state.username}**{_badge}")
        if st.session_state.get(_SIDEBAR_NOTICE_KEY):
            st.info(st.session_state[_SIDEBAR_NOTICE_KEY])
            del st.session_state[_SIDEBAR_NOTICE_KEY]
        if st.button("Logout"):
            if st.session_state.login_token:
                auth.revoke_login_token(st.session_state.login_token)
            _clear_auth_cookie()
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.login_token = ""
            st.session_state["_sso_denied_email"] = ""
            # Also end the Google session, if any (triggers its own rerun).
            if _google_user():
                try:
                    st.logout()
                except Exception:
                    pass
            st.rerun()

        st.header("⚙️ LLM Settings")
        if app_config.llm_config_locked():
            # Production: provider/key are env-managed. Don't render the editable
            # form (it writes a shared global config.json any user could overwrite).
            st.caption(
                "Model provider and API key are managed by the deployment and "
                "can't be changed here."
            )
            st.markdown(f"**Provider:** {_provider_label(llm_settings['provider'])}")
            if llm_settings.get("base_url"):
                st.caption(f"Endpoint: {llm_settings['base_url']}")
            st.caption(f"Text model: `{llm_settings['text_model']}`")
            st.caption(f"Embedding model: `{llm_settings['embed_model']}`")
        else:
            _ensure_sidebar_draft_settings(llm_settings)
            provider_order = list(_PROVIDER_LABELS.keys())
            current_provider = (
                st.session_state[_SIDEBAR_SETTING_KEYS["provider"]]
                if st.session_state[_SIDEBAR_SETTING_KEYS["provider"]] in _PROVIDER_LABELS
                else "gemini"
            )
            provider_index = provider_order.index(current_provider)

            with st.form("llm_settings_form"):
                provider = st.selectbox(
                    "LLM Provider",
                    provider_order,
                    index=provider_index,
                    format_func=_provider_label,
                    help="Pick the backend that will power editing, citation alignment, journal matching, and cover-letter generation.",
                    key=_SIDEBAR_SETTING_KEYS["provider"],
                )

                defaults = app_config.default_settings_for_provider(provider)
                _sync_sidebar_defaults(provider)
                st.caption(_PROVIDER_REQUIREMENTS.get(provider, "Configure the model settings for this provider."))
                if provider == "openrouter":
                    st.info(
                        "OpenRouter is OpenAI-compatible. Use your OpenRouter API key, the "
                        f"default endpoint `{_OPENROUTER_BASE_URL}`, and OpenRouter model IDs "
                        "such as `openai/gpt-4o-mini`."
                    )

                needs_api_key = provider in {"gemini", "openrouter"}
                needs_base_url = provider in {"openai-compatible", "custom"}
                api_key = st.text_input(
                    "API Key",
                    key=_SIDEBAR_SETTING_KEYS["api_key"],
                    type="password",
                    help=(
                        "Required for Gemini. For OpenRouter, paste your OpenRouter API key "
                        "from https://openrouter.ai/keys."
                        if provider == "openrouter"
                        else "Required for Gemini and OpenRouter. Optional for other providers."
                    ),
                )

                if provider == "openrouter":
                    base_url = _OPENROUTER_BASE_URL
                    st.caption("OpenRouter uses a fixed endpoint: https://openrouter.ai/api/v1")
                elif needs_base_url:
                    base_url = st.text_input(
                        "Base URL",
                        key=_SIDEBAR_SETTING_KEYS["base_url"],
                        help=(
                            "The provider endpoint, for example an OpenAI-compatible proxy."
                        ),
                    )
                else:
                    base_url = ""
                    st.caption("Gemini uses Google-managed endpoints, so no base URL is needed.")

                text_model = st.text_input(
                    "Text model",
                    key=_SIDEBAR_SETTING_KEYS["text_model"],
                    help=(
                        "Starter defaults are provider-specific, but you can change this to any valid model ID."
                        if provider == "openrouter"
                        else "This model will handle editing, citation cleanup, cover letters, and title polish."
                    ),
                )

                embed_model = st.text_input(
                    "Embedding model",
                    key=_SIDEBAR_SETTING_KEYS["embed_model"],
                    help=(
                        "Starter defaults are provider-specific, but you can change this to any valid embedding model ID."
                        if provider == "openrouter"
                        else "This model is used for journal recommendations."
                    ),
                )

                save_llm = st.form_submit_button("Save LLM Settings")

            if save_llm:
                errors = _llm_setting_errors(
                    {
                        "provider": provider,
                        "api_key": api_key,
                        "base_url": base_url,
                        "text_model": text_model,
                        "embed_model": embed_model,
                    }
                )

                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    api_key_to_save = st.session_state[_SIDEBAR_SETTING_KEYS["api_key"]]
                    base_url_to_save = (
                        "" if provider == "gemini" else base_url
                    )
                    app_config.save_llm_settings(
                        {
                            "provider": provider,
                            "api_key": api_key_to_save,
                            "base_url": base_url_to_save,
                            "text_model": st.session_state[_SIDEBAR_SETTING_KEYS["text_model"]],
                            "embed_model": st.session_state[_SIDEBAR_SETTING_KEYS["embed_model"]],
                        }
                    )
                    st.success(f"Saved {_provider_label(provider)} settings.")
                    st.rerun()

        st.divider()
        st.header("🛠️ Style Settings")
        edit_style = st.selectbox(
            "Copyediting Style",
            ["Chicago Manual of Style (CMOS)", "APA", "MLA", "IEEE"],
        )
        ref_style = st.selectbox(
            "Reference Style",
            ["Vancouver", "Harvard", "APA", "Chicago", "IEEE"],
        )
        lang_type = st.selectbox("Language", ["US English", "UK English", "Australian English"])

        st.divider()
        st.header("🚀 Advanced Features")
        reorder_citations = st.checkbox(
            "Auto-Number & Sort Citations", value=True,
            help="Converts author-date citations to [1], [2] and sorts bibliography to match the order of appearance.",
        )
        use_crossref = st.checkbox(
            "Live Crossref DOI Validation", value=True,
            help="Scans bibliography for verified DOIs.",
        )
        _serper_configured = bool(app_config.get_serper_api_key())
        use_serper = st.checkbox(
            "Serper (Google Scholar) DOI Fallback", value=_serper_configured,
            disabled=not _serper_configured,
            help=(
                "Optional. When Crossref can't find a DOI, search Google Scholar via "
                "Serper.dev. Requires a SERPER_API_KEY (env or config.json). "
                + ("Key detected." if _serper_configured
                   else "No key configured — leave off; everything else works as usual.")
            ),
        )
        plagiarism_scan_enabled = st.checkbox(
            "Preliminary Originality Scan (web matches)", value=False,
            disabled=not _serper_configured,
            help=(
                "Optional. Exact-phrase web search (via Serper) on a sample of "
                "sentences to flag verbatim matches on the public web. NOT a real "
                "plagiarism check — it cannot see paywalled journals or paraphrasing "
                "and is not a substitute for iThenticate/Turnitin. Uses Serper quota."
            ),
        )
        ai_review_enabled = st.checkbox(
            "AI Peer Reviewer", value=True,
            help="Runs an expert AI referee in parallel and produces a downloadable "
                 "peer-review report (strengths, concerns, and an accept/revise/reject "
                 "recommendation).",
        )
        custom_dict = st.text_area(
            "Custom Dictionary / Acronyms",
            placeholder="e.g. mTOR, mRNA, do not change capitalization of ABC.",
        )

        st.divider()
        st.header("📋 Publisher / House Rules")
        st.caption(
            "These in-house rules are enforced on every manuscript. "
            "Untick any you want to skip, or add your own below."
        )
        _saved_rules = auth.get_user_house_rules(st.session_state.user_id)
        _disabled = set(_saved_rules["disabled_groups"])

        enabled_rule_ids = []
        for _group in HOUSE_RULE_GROUPS:
            _on = st.checkbox(
                _group["title"],
                value=_group["id"] not in _disabled,
                key=f"rule_{_group['id']}",
                help=_group["summary"],
            )
            if _on:
                enabled_rule_ids.append(_group["id"])
            with st.expander("View rule details", expanded=False):
                st.markdown(f"```\n{_group['body']}\n```")

        custom_rules = st.text_area(
            "Your additional publisher rules",
            value=_saved_rules["custom_rules"],
            key="custom_rules_input",
            placeholder="e.g. Use British spelling for '-ise' verbs. Spell out numbers under 10.",
            help="Free-form rules appended to the editor instructions. Applied on every run.",
        )

        if st.button("💾 Save my rules"):
            _disabled_now = [g["id"] for g in HOUSE_RULE_GROUPS if g["id"] not in enabled_rule_ids]
            auth.save_user_house_rules(
                st.session_state.user_id, _disabled_now, custom_rules,
            )
            st.success("Your publisher rules were saved.")
else:
    st.info("Log in to access LLM settings and manuscript tools.")


# --- Auth gate ---

def _admin_password_login() -> None:
    """Break-glass password sign-in, restricted to admin-role accounts."""
    lu = st.text_input("Admin username", key="alu")
    lp = st.text_input("Password", type="password", key="alp")
    if st.button("Admin sign-in", key="admin_login_btn"):
        if auth.is_locked_out(lu):
            st.error("Too many failed attempts. Please wait a few minutes and try again.")
            return
        uid = auth.login(lu, lp)
        if uid and auth.is_admin(uid):
            st.session_state.user_id = uid
            st.session_state.username = lu
            st.session_state.role = "admin"
            st.rerun()
        elif uid:
            st.error("Password sign-in is restricted to administrators. Please use Google.")
        else:
            st.error("Invalid credentials.")


def _legacy_password_auth() -> None:
    """Full username/password login + registration. Used only when Google SSO
    is not configured (local dev / pre-SSO) so nobody is locked out."""
    tab_login, tab_reg = st.tabs(["Login", "Register"])
    with tab_login:
        lu = st.text_input("Username", key="lu")
        lp = st.text_input("Password", type="password", key="lp")
        remember_help = (
            "Stores a secure browser cookie so you stay signed in after refreshes."
            if COOKIE_MANAGER_AVAILABLE
            else "Cookie support is unavailable in this runtime, so login persists only for the current session."
        )
        remember_me = st.checkbox(
            "Remember me on this device",
            value=COOKIE_MANAGER_AVAILABLE,
            disabled=not COOKIE_MANAGER_AVAILABLE,
            help=remember_help,
        )
        if st.button("Login", type="primary"):
            if auth.is_locked_out(lu):
                st.error("Too many failed login attempts. Please wait a few minutes and try again.")
            else:
                uid = auth.login(lu, lp)
                if uid:
                    st.session_state.user_id = uid
                    st.session_state.username = lu
                    st.session_state.role = auth.get_user_role(uid)
                    if remember_me:
                        st.session_state.login_token = auth.issue_login_token(uid)
                        cookies["auth_token"] = st.session_state.login_token
                        cookies.save()
                    else:
                        st.session_state.login_token = ""
                        _clear_auth_cookie()
                    st.rerun()
                else:
                    st.error("Invalid credentials.")
    with tab_reg:
        ru = st.text_input("Username", key="ru")
        rp = st.text_input("Password", type="password", key="rp")
        if st.button("Create Account"):
            if auth.register(ru, rp):
                st.success("Account created! Please login in the other tab.")
            else:
                st.error("Username already taken or invalid.")


if not st.session_state.user_id:
    st.title("🔐 Manuscript Editor Pro — Sign in")

    if _google_auth_configured():
        _domains = ", ".join(app_config.allowed_login_domains())
        denied = st.session_state.get("_sso_denied_email")
        if denied:
            st.error(
                f"**{denied}** is not permitted. Please use a {_domains} account."
            )
            if st.button("Sign out and try another account"):
                st.session_state["_sso_denied_email"] = ""
                try:
                    st.logout()
                except Exception:
                    st.rerun()
        st.markdown("Sign in with your organization Google account.")
        if st.button("Sign in with Google", type="primary"):
            st.login("google")
        st.caption(f"Allowed domains: {_domains}")
        with st.expander("Administrator sign-in (break-glass)"):
            _admin_password_login()
    else:
        st.warning(
            "Google SSO is not configured (no `[auth]` in secrets). "
            "Falling back to local accounts."
        )
        _legacy_password_auth()
    st.stop()


# --- Main UI ---

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _safe_stem(filename: str) -> str:
    """Manuscript base name (no extension), sanitized for use in download
    filenames so every downloaded file is identifiable by name. Falls back to
    'manuscript'."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0].strip()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
    return stem or "manuscript"


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}


def _render_house_panel(result: dict, kp: str) -> None:
    """House-style and proofreading findings, above the report rather than inside it.

    The report already carries these in prose, and prose is what you read once you
    have decided to. This is the count you decide *from*: an editor opening a job
    wants to know there are sixteen errors before reading a word, and a number buried
    three headings into a markdown blob is a number nobody sees.

    Nothing here is a blocker. Every finding is something a person confirms — the
    tool has never been allowed to change formatting on its own, and this panel is
    the reason it does not need to be.
    """
    # Said first and separately from the findings. Everything else in this panel is
    # something the tool *did*; this is the part it did not do, and an editor needs
    # that before they trust the rest of the page.
    missed = result.get("skipped_paragraphs") or []
    if missed:
        shown = ", ".join(str(i + 1) for i in missed[:15])
        st.error(
            f"**{len(missed)} paragraph(s) were not copyedited** and are unchanged in "
            f"the redline — the model could not be got to answer for them, after a "
            f"retry. They are paragraphs {shown}"
            f"{'…' if len(missed) > 15 else ''}. Everything else in this manuscript "
            f"was processed normally; these need reading by hand."
        )

    house = result.get("house_findings") or []
    proof = result.get("proof_findings") or []
    tables_edited = result.get("tables_edited") or 0
    table_queries = result.get("table_queries") or []

    if not (house or proof or tables_edited or table_queries or missed):
        return

    def count(items, severity):
        return sum(1 for f in items if f.get("severity") == severity)

    errors = count(house, "error") + count(proof, "error")
    warnings_n = count(house, "warning") + count(proof, "warning")
    infos = count(house, "info") + count(proof, "info")

    st.subheader("📐 House Style & Proofreading")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Errors", errors)
    c2.metric("Warnings", warnings_n)
    c3.metric("For review", infos)
    c4.metric("Table cells edited", tables_edited)

    if tables_edited:
        st.caption(
            f"{tables_edited} paragraph(s) inside tables were copyedited. Table text "
            "is not part of the document body, so until now nothing had ever read it."
        )

    def _render_findings(items):
        ordered = sorted(items, key=lambda f: (_SEVERITY_ORDER.get(f.get("severity"), 3),
                                               f.get("rule", "")))
        for f in ordered:
            icon = _SEVERITY_ICON.get(f.get("severity"), "•")
            where = (f"¶{f['paragraph'] + 1}" if isinstance(f.get("paragraph"), int)
                     else "document")
            st.markdown(f"{icon} **{where}** · `{f.get('rule', '')}` — "
                        f"{f.get('message', '')}")
            detail = (f.get("detail") or "").strip()
            if detail:
                st.caption(f"> {detail[:160]}")
            suggestion = (f.get("suggestion") or "").strip()
            if suggestion:
                st.caption(f"Suggested: {suggestion[:160]}")

    for title, items in (("Layout and house style", house), ("Proofreading", proof)):
        if not items:
            continue
        # In summary mode the fourteen findings that are true of nearly every author
        # submission move one expander deeper, so what is specific to *this*
        # manuscript is not buried under what is true of all of them. Nothing is
        # dropped; an editor checking house compliance still needs the list.
        routine, notable = ([], items)
        if title.startswith("Layout") and _house_panel_summary():
            routine, notable = house_layout.split_routine(items)
        with st.expander(f"{title} — {len(items)} item(s)", expanded=bool(errors)):
            _render_findings(notable)
            if routine:
                st.caption(
                    f"{len(routine)} further item(s) are the usual layout differences "
                    "for an author submission — measured on 1,606 manuscripts, each of "
                    "these appears in more than half of them."
                )
                with st.expander(f"Show the routine layout items — {len(routine)}"):
                    _render_findings(routine)

    if table_queries:
        with st.expander(f"Questions about table content — {len(table_queries)}"):
            for q in table_queries:
                st.markdown(f"• {q.get('query', '')}")
                if q.get("suggestion"):
                    st.caption(f"Suggested: {q['suggestion'][:160]}")


def _render_result(result: dict, kp: str) -> None:
    """Render a completed job's reports and downloads. `kp` keys the widgets."""
    for _w in result.get("warnings") or []:
        st.warning(_w)
    _render_house_panel(result, kp)

    res_col1, res_col2 = st.columns([1.5, 1])
    with res_col1:
        st.subheader("📊 Editorial Report")
        st.markdown(result.get("report_md", ""))

        ai_md = result.get("ai_review_md")
        if ai_md:
            st.subheader("🧑‍⚖️ AI Peer Review")
            with st.expander("Read the AI reviewer's report", expanded=True):
                st.markdown(ai_md)

        st.subheader("📚 Journal Recommendations")
        st.caption(
            "A semantic score (vector-embedding similarity to each journal's scope) "
            "shortlists candidates; an AI publishing advisor then ranks the best "
            "fits from that shortlist, with every pick validated against our real "
            "journal catalogue. A higher fit score means a closer match."
        )
        for i, j in enumerate(result.get("recommended", []), 1):
            fit_score = j.get("fit_score")
            score = j.get("score", 0)
            if fit_score is not None:
                match_pct = f"{int(round(fit_score))}/100 Fit"
            elif score > 0:
                match_pct = f"{int(score * 100)}% Match"
            else:
                match_pct = "Recommended"
            fit = j.get("fit_label", "")
            fit_str = f" · {fit}" if fit else ""
            impact_str = f" | Impact Factor: {j.get('impact_factor')}" if j.get("impact_factor") else ""
            with st.expander(f"**{i}. {j['name']}** ({match_pct}{fit_str}{impact_str})", expanded=(i == 1)):
                verdict = j.get("fit_verdict", "")
                if verdict:
                    conf = j.get("confidence", "")
                    st.write(f"**AI Advisor Verdict:** {verdict}" + (f" ({conf} confidence)" if conf else ""))
                elif fit:
                    st.write(f"**Fit:** {fit}")
                st.write(f"**Publisher:** {j.get('publisher', 'Unknown')}")
                topics = j.get("topics", [])
                st.write(f"**Focus Topics:** {', '.join(topics).title()}")
                matched = j.get("matched_topics", [])
                if matched:
                    st.write(f"**Matched Topics:** {', '.join(t.title() for t in matched)}")
                keywords = j.get("matched_keywords", [])
                if keywords:
                    st.write(f"**Matched Terms:** {', '.join(keywords)}")
                reason = j.get("reason", "")
                if reason:
                    st.markdown(f"**Why recommended:** {reason}")
                risks = j.get("risk_factors", [])
                if risks:
                    st.warning("**Cautions:** " + " ".join(risks))

        with st.expander("✉️ Auto-Generated Submission Cover Letter", expanded=False):
            st.info(f"Custom tailored for: **{result.get('best_journal', 'the journal')}**")
            st.markdown(result.get("cover_letter", ""))

        with st.expander("💡 Title & Abstract Polish", expanded=False):
            st.markdown(result.get("polished_titles", ""))

    with res_col2:
        st.subheader("📥 Download Results")
        st.info("Your redline document features native Word Track Changes.")
        stem = _safe_stem(result.get("filename", ""))
        downloads = [
            ("redline_path", "Download Redline Manuscript", f"{stem}_redline.docx", _DOCX_MIME, "primary"),
            ("journal_report_path", "📚 Download Journal Recommendations", f"{stem}_journal_recommendations.docx", _DOCX_MIME, "secondary"),
            ("review_report_path", "📑 Download Review Report", f"{stem}_editorial_report.docx", _DOCX_MIME, "secondary"),
            ("ai_review_path", "🧑‍⚖️ Download AI Peer Review", f"{stem}_ai_peer_review.docx", _DOCX_MIME, "secondary"),
            ("plagiarism_report_path", "🔎 Download Originality Report (preliminary)", f"{stem}_originality_report.docx", _DOCX_MIME, "secondary"),
            ("jats_path", "🏷️ Download JATS/XML (production)", f"{stem}_jats.xml", JATS_MIME, "secondary"),
        ]
        for key, label, fname, mime, btype in downloads:
            path = result.get(key) or ""
            if path and os.path.exists(path):
                with open(path, "rb") as fh:
                    st.download_button(
                        label=label, data=fh, file_name=fname, mime=mime,
                        type=btype, key=f"dl_{key}_{kp}",
                    )
        if result.get("jats_ok"):
            st.caption("✓ Structurally valid JATS")
        elif result.get("jats_issues"):
            st.warning("JATS structural issues:\n- " + "\n- ".join(result["jats_issues"]))


def _house_panel_summary() -> bool:
    """Whether to collapse the routine layout findings.

    Defaults to today's behaviour. Amit had not decided between leaving the panel and
    collapsing it, so this ships as a switch rather than as another rewrite: set
    HOUSE_PANEL_MODE=summary to try it, unset it to go back.
    """
    return os.getenv("HOUSE_PANEL_MODE", "full").strip().lower() == "summary"


def _render_job_usage(job: dict) -> None:
    """One line: what this job spent. Shown on failures too — a job that fell over
    still burned its tokens, and hiding that is how a bill becomes a surprise."""
    calls = int(job.get("llm_calls") or 0)
    if not calls:
        return
    prompt = int(job.get("prompt_tokens") or 0)
    completion = int(job.get("completion_tokens") or 0)
    cached = int(job.get("cached_tokens") or 0)
    parts = [f"{calls} model calls",
             f"{prompt + completion:,} tokens ({prompt:,} in, {completion:,} out)"]
    if cached:
        parts.append(f"{cached:,} reused from cache")
    parts.append(_usage.format_cost(job.get("cost_usd")))
    st.caption(" · ".join(parts))


def _render_job(job: dict) -> None:
    """Render a job's live status (auto-refreshing) or its final result."""
    status = job["status"]
    if status in ("queued", "running"):
        st.info(f"**{job.get('stage', 'Queued')}** — job #{job['id']} · {job['filename']}")
        st.progress(float(job.get("progress") or 0.0))
        st.caption("Processing runs in the background. You can close this tab and come back.")
        time.sleep(2)
        st.rerun()
    elif status == "error":
        st.error(f"Processing failed for **{job['filename']}**: {job.get('error_message')}")
        _render_job_usage(job)
    elif status == "done":
        result = json.loads(job.get("result_json") or "{}")
        st.success(f"✅ Completed in {result.get('duration', '?')}s — {job['filename']}")
        _render_job_usage(job)
        _render_result(result, kp=str(job["id"]))


st.title("📝 Automated Manuscript Copyediting & Proofreading")

_is_superadmin = st.session_state.get("role") == "superadmin"
_tab_labels = ["📝 Editor", "🧪 Model Test", "📚 My History", "📈 Analytics"]
if _is_superadmin:
    _tab_labels.append("👑 Superadmin")
_tabs = st.tabs(_tab_labels)
tab_editor, tab_test, tab_history, tab_analytics = _tabs[:4]
tab_superadmin = _tabs[4] if _is_superadmin else None

with tab_editor:
    st.markdown(
        "Upload your `.docx` manuscript. Our engine will proofread it, "
        "generate a redline tracking document, and offer advanced publication tools."
    )

    uploaded_file = st.file_uploader("Upload Manuscript (.docx)", type=["docx"])

    if uploaded_file is not None and st.button("Process Manuscript", type="primary"):
        provider = llm_settings["provider"]
        if provider in _API_KEY_PROVIDERS and not llm_settings["api_key"].strip():
            st.error("Please enter an API key for the selected provider in the sidebar to continue.")
            st.stop()
        if provider in _BASE_URL_PROVIDERS and not llm_settings["base_url"].strip():
            st.error("Please enter a base URL for the selected provider in the sidebar to continue.")
            st.stop()
        if not llm_settings["text_model"].strip():
            st.error("Please enter a text model in the sidebar to continue.")
            st.stop()
        if not llm_settings["embed_model"].strip():
            st.error("Please enter an embedding model in the sidebar to continue.")
            st.stop()

        # The quota gate, before the upload is written and before a job row exists.
        # `st.stop()` on its own line, not folded into a helper that returns a
        # message: a gate whose refusal is only a returned value is a gate that can
        # be walked past when a caller forgets to check it.
        _quota = auth.quota_check(st.session_state.user_id)
        if not _quota["allowed"]:
            st.error(_quota["message"])
            st.stop()

        out_dir = app_config.output_dir()
        # Unique token (not int(time.time()), which only has 1s resolution) so a
        # double-click or concurrent upload never overwrites another job's input.
        input_path = out_dir / f"user_{st.session_state.user_id}_{uuid.uuid4().hex[:12]}_input.docx"
        input_path.write_bytes(uploaded_file.getvalue())
        options = {
            "user_id": st.session_state.user_id,
            "filename": uploaded_file.name,
            "edit_style": edit_style,
            "ref_style": ref_style,
            "lang_type": lang_type,
            "custom_dict": custom_dict,
            "use_crossref": use_crossref,
            "use_serper": use_serper,
            "plagiarism_scan_enabled": plagiarism_scan_enabled,
            "reorder_citations": reorder_citations,
            "enabled_rule_ids": enabled_rule_ids,
            "custom_rules": custom_rules,
            "ai_review_enabled": ai_review_enabled,
        }
        job_id = auth.create_job(
            st.session_state.user_id, uploaded_file.name, str(input_path),
            json.dumps(options),
        )
        st.session_state.active_job_id = job_id
        st.success(f"Queued for processing (job #{job_id}). It runs in the background — "
                   "you can close this tab and come back.")
        st.rerun()

    st.divider()
    # Where the user stands this month, shown before they hit the wall rather than
    # only at the moment they are refused.
    _month = auth.month_usage(st.session_state.user_id)
    _cap = auth.token_cap_for(st.session_state.user_id)
    _spent = f"{_month['jobs']} jobs · {_month['total_tokens']:,} tokens"
    if _month["cached_tokens"]:
        _spent += f" ({_month['cached_tokens']:,} reused from cache)"
    if _month["cost_usd"] is not None:
        _spent += f" · {_usage.format_cost(_month['cost_usd'])}"
    if _cap:
        _left = max(0, _cap - _month["total_tokens"])
        st.caption(f"This month: {_spent} — {_left:,} of {_cap:,} tokens left.")
    else:
        st.caption(f"This month: {_spent}.")

    _jobs = auth.fetch_user_jobs(st.session_state.user_id, limit=15)
    if not _jobs:
        st.info(
            "Upload a manuscript and click **Process**. Jobs run in the background, "
            "so you can close the tab and return — your results wait for you here."
        )
    else:
        _ids = [j["id"] for j in _jobs]
        _labels = {
            j["id"]: f"#{j['id']} · {j['filename']} · {j['status']}"
            for j in _jobs
        }
        _active = st.session_state.get("active_job_id")
        _default = _ids.index(_active) if _active in _ids else 0
        _selected = st.selectbox(
            "Processing jobs", _ids, index=_default,
            format_func=lambda i: _labels.get(i, f"#{i}"),
        )
        st.session_state.active_job_id = _selected
        _job = auth.get_job(_selected)
        if _job:
            _render_job(_job)


with tab_test:
    st.subheader("🧪 LLM and Embedding Test")
    st.markdown(
        "Use this panel to verify the currently selected provider, text model, and embedding model "
        "before you process a manuscript."
    )

    current_settings = app_config.get_llm_settings()
    st.info(
        f"Current provider: **{_provider_label(current_settings['provider'])}** | "
        f"Text model: `{current_settings['text_model']}` | "
        f"Embedding model: `{current_settings['embed_model']}`"
    )

    for warning in _llm_setting_errors(current_settings):
        st.warning(f"Saved settings issue: {warning} Save a valid configuration in the sidebar before testing.")

    if "llm_text_test_prompt" not in st.session_state:
        st.session_state.llm_text_test_prompt = _text_test_prompt_for_provider(
            current_settings["provider"]
        )
    if "llm_embed_test_text" not in st.session_state:
        st.session_state.llm_embed_test_text = _embed_test_text_for_provider(
            current_settings["provider"]
        )

    if current_settings["provider"] == "openrouter":
        summary = st.session_state.get(_OPENROUTER_SUMMARY_KEY)
        if isinstance(summary, dict):
            st.markdown(
                f"""
                <div style="padding: 0.9rem 1rem; border: 1px solid rgba(49, 51, 63, 0.18);
                border-radius: 0.75rem; background: rgba(250, 250, 252, 0.96);">
                  <strong>{summary['title']}</strong><br>
                  Provider: {summary['provider']}<br>
                  Base URL: <code>{summary['base_url']}</code><br>
                  Text model: <code>{summary['text_model']}</code><br>
                  Embedding model: <code>{summary['embed_model']}</code><br>
                  <span style="opacity: 0.78;">{summary['note']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.info(
            "OpenRouter setup: use `https://openrouter.ai/api/v1`, an OpenRouter API key, "
            "and model IDs such as `openai/gpt-4o-mini` before running the test."
        )

    st.markdown("**One-click prompt presets**")
    preset_col1, preset_col2, preset_col3 = st.columns(3)
    with preset_col1:
        if st.button("Gemini preset", width="stretch"):
            st.session_state.llm_text_test_prompt = _text_test_prompt_for_provider("gemini")
    with preset_col2:
        if st.button("OpenRouter preset", width="stretch"):
            st.session_state.llm_text_test_prompt = _text_test_prompt_for_provider("openrouter")
            st.session_state.llm_embed_test_text = _embed_test_text_for_provider("openrouter")
    with preset_col3:
        if st.button("Copy OpenRouter settings", width="stretch"):
            _apply_openrouter_sidebar_settings()
            st.rerun()

    col_left, col_right = st.columns(2)
    with col_left:
        text_probe = st.text_area(
            "Text generation prompt",
            key="llm_text_test_prompt",
            height=140,
        )
        run_text_test = st.button("Run text model test", type="primary")

    with col_right:
        embedding_probe = st.text_area(
            "Embedding test text",
            key="llm_embed_test_text",
            height=140,
        )
        run_embed_test = st.button("Run embedding test")

    if run_text_test:
        try:
            started = time.perf_counter()
            with st.spinner("Testing text model..."):
                result = test_text_generation(text_probe, current_settings)
            duration = time.perf_counter() - started
            st.session_state["llm_text_test_result"] = result
            st.session_state["llm_text_test_latency"] = duration
            st.session_state["llm_text_test_error"] = ""
        except Exception as e:
            st.session_state["llm_text_test_error"] = str(e)
            st.session_state["llm_text_test_result"] = ""
            st.session_state["llm_text_test_latency"] = None

    if run_embed_test:
        try:
            started = time.perf_counter()
            with st.spinner("Testing embedding model..."):
                vector = test_embedding(embedding_probe, current_settings)
            duration = time.perf_counter() - started
            st.session_state["llm_embed_test_result"] = vector
            st.session_state["llm_embed_test_latency"] = duration
            st.session_state["llm_embed_test_error"] = ""
        except Exception as e:
            st.session_state["llm_embed_test_error"] = str(e)
            st.session_state["llm_embed_test_result"] = []
            st.session_state["llm_embed_test_latency"] = None

    st.divider()
    st.subheader("Results")
    text_error = st.session_state.get("llm_text_test_error", "")
    text_result = st.session_state.get("llm_text_test_result", "")
    text_latency = st.session_state.get("llm_text_test_latency")
    if text_error:
        st.error(f"Text model test failed: {text_error}")
    elif text_result:
        left, right = st.columns(2)
        left.success("Text model test succeeded.")
        if text_latency is not None:
            right.metric("Latency", f"{text_latency:.2f}s")
        st.write(text_result)
    else:
        st.caption("No text-model test run yet.")

    embed_error = st.session_state.get("llm_embed_test_error", "")
    embed_result = st.session_state.get("llm_embed_test_result", [])
    embed_latency = st.session_state.get("llm_embed_test_latency")
    if embed_error:
        st.error(f"Embedding test failed: {embed_error}")
    elif embed_result:
        left, right = st.columns(2)
        left.success(f"Embedding test succeeded. Vector length: {len(embed_result)}")
        if embed_latency is not None:
            right.metric("Latency", f"{embed_latency:.2f}s")
        st.write(embed_result[:12])
        if len(embed_result) > 12:
            st.caption("Showing the first 12 values only.")
    else:
        st.caption("No embedding test run yet.")


with tab_history:
    st.subheader("📚 Your Document History")
    rows = auth.fetch_user_history(st.session_state.user_id)
    if not rows:
        st.info("No documents processed yet. Your history will appear here.")
    else:
        for idx, row in enumerate(rows):
            with st.container():
                cols = st.columns([2, 1, 1])
                cols[0].write(f"**{row['filename']}** ({row['timestamp']})")
                cols[1].write(row["edit_style"])
                cols[2].write(row["status"])

                if row["status"] == "Success":
                    stem = _safe_stem(row.get("filename", ""))
                    dl_cols = st.columns(6)
                    rp = row.get("redline_path") or ""
                    if rp and os.path.exists(rp):
                        with open(rp, "rb") as rf:
                            dl_cols[0].download_button(
                                "📝 Redline", data=rf,
                                file_name=f"{stem}_redline.docx",
                                key=f"dl_redline_{idx}",
                            )
                    _docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    jp = row.get("journal_report_path") or ""
                    if jp and os.path.exists(jp):
                        with open(jp, "rb") as jf:
                            dl_cols[1].download_button(
                                "📚 Journals", data=jf,
                                file_name=f"{stem}_journal_recommendations.docx",
                                mime=_docx_mime,
                                key=f"dl_journals_{idx}",
                            )
                    vp = row.get("review_report_path") or ""
                    if vp and os.path.exists(vp):
                        with open(vp, "rb") as vf:
                            dl_cols[2].download_button(
                                "📑 Review", data=vf,
                                file_name=f"{stem}_editorial_report.docx",
                                mime=_docx_mime,
                                key=f"dl_review_{idx}",
                            )
                    ap = row.get("ai_review_path") or ""
                    if ap and os.path.exists(ap):
                        with open(ap, "rb") as af:
                            dl_cols[3].download_button(
                                "🧑‍⚖️ AI Review", data=af,
                                file_name=f"{stem}_ai_peer_review.docx",
                                mime=_docx_mime,
                                key=f"dl_aireview_{idx}",
                            )
                    xp = row.get("jats_path") or ""
                    if xp and os.path.exists(xp):
                        with open(xp, "rb") as xf:
                            dl_cols[4].download_button(
                                "🏷️ JATS XML", data=xf,
                                file_name=f"{stem}_jats.xml",
                                mime=JATS_MIME,
                                key=f"dl_jats_{idx}",
                            )
                    pp = row.get("plagiarism_report_path") or ""
                    if pp and os.path.exists(pp):
                        with open(pp, "rb") as pf:
                            dl_cols[5].download_button(
                                "🔎 Originality", data=pf,
                                file_name=f"{stem}_originality_report.docx",
                                mime=_docx_mime,
                                key=f"dl_plag_{idx}",
                            )
                st.divider()


with tab_analytics:
    st.subheader("📈 Platform Analytics (anonymized, last 90 days)")
    try:
        rows = auth.fetch_global_analytics()
        total_users = auth.fetch_user_count()
        total_jobs = auth.fetch_total_jobs()

        c1, c2, c3 = st.columns(3)
        c1.metric("Total users", total_users)
        c2.metric("Total jobs (all time)", total_jobs)
        c3.metric("Days with activity", len(rows))

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, width="stretch")
            st.caption("Per-user rows are never shown — only daily aggregates.")
        else:
            st.info("No analytics recorded yet.")
    except Exception as e:
        st.error(f"Could not load analytics: {e}")


if tab_superadmin is not None:
    with tab_superadmin:
        # Defense in depth: never trust the session flag alone for a privileged
        # surface — re-verify the role against the database on every render.
        if not auth.is_superadmin(st.session_state.get("user_id")):
            st.error("This area is restricted to superadmins.")
            st.stop()

        st.subheader("👑 Superadmin Control Center")
        st.caption(
            "Platform-wide tracing and management. Data here is non-anonymized — "
            "handle responsibly. Superadmins are designated via the SUPERADMIN_EMAILS "
            "environment allowlist."
        )

        sa_overview, sa_users, sa_jobs, sa_audit = st.tabs(
            ["🩺 Overview & Health", "👥 Users & Roles", "⚙️ Jobs", "🔍 Audit & Security"]
        )

        # ---- Overview & system health -------------------------------------
        with sa_overview:
            try:
                roles = auth.role_counts()
                queue = auth.job_queue_stats()
                tables = auth.db_table_counts()

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Users", auth.fetch_user_count())
                m2.metric("Superadmins", roles.get("superadmin", 0))
                m3.metric("Admins", roles.get("admin", 0))
                m4.metric("Processed manuscripts", auth.fetch_total_jobs())

                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Jobs queued", queue.get("queued", 0))
                q2.metric("Jobs running", queue.get("running", 0))
                q3.metric("Jobs done", queue.get("done", 0))
                q4.metric("Jobs errored", queue.get("error", 0))

                st.markdown("**Database tables**")
                st.dataframe(
                    pd.DataFrame([{"table": k, "rows": v} for k, v in tables.items()]),
                    width="stretch", hide_index=True,
                )

                st.markdown("**Runtime configuration**")
                cfg = {
                    "LLM provider": llm_settings.get("provider", ""),
                    "LLM config locked (env)": app_config.llm_config_locked(),
                    "Output retention (days)": app_config.output_retention_days(),
                    "Login max attempts": app_config.login_max_attempts(),
                    "Lockout window (min)": app_config.login_lockout_minutes(),
                    "Postgres backend": "DATABASE_URL" in os.environ and bool(app_config.database_url()),
                    "Superadmin allowlist size": len(app_config.superadmin_emails()),
                    "Admin allowlist size": len(app_config.admin_emails()),
                }
                st.dataframe(
                    pd.DataFrame([{"setting": k, "value": str(v)} for k, v in cfg.items()]),
                    width="stretch", hide_index=True,
                )
            except Exception as e:
                st.error(f"Could not load overview: {e}")

        # ---- Users & roles ------------------------------------------------
        with sa_users:
            try:
                users = auth.fetch_all_users()
                if not users:
                    st.info("No users registered yet.")
                else:
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "id": u["id"], "username": u.get("username"),
                                "email": u.get("email"), "role": u.get("role") or "member",
                                "auth": u.get("auth_provider"), "jobs": u.get("job_count", 0),
                                "manuscripts this month": (
                                    lambda used, cap: f"{used} / "
                                    + ("unlimited" if cap == 0 else str(cap))
                                )(auth.month_job_count(u["id"]), auth.job_cap_for(u["id"])),
                                "tokens this month": f"{auth.month_usage(u['id'])['total_tokens']:,}",
                                "token cap": (lambda c: "no limit" if c == 0 else f"{c:,}")(
                                    auth.token_cap_for(u["id"])),
                                "last_active": u.get("last_active") or "—",
                            }
                            for u in users
                        ]),
                        width="stretch", hide_index=True,
                    )

                    st.markdown("**Set a user's monthly manuscript allowance**")
                    st.caption(
                        f"New accounts get {auth.default_job_cap()} manuscripts a month. "
                        "Raise it for a particular user, or grant unlimited access. "
                        "Admins and superadmins are never capped."
                    )
                    _cap_by_label = {
                        f'{u["username"]} (id {u["id"]})': u for u in users
                    }
                    # Three named choices rather than a bare number field. 0 means
                    # "unlimited" in the database, and asking an administrator to type
                    # 0 to *remove* a limit is the kind of interface that eventually
                    # blocks someone by accident.
                    _CHOICE_DEFAULT = f"Deployment default ({auth.default_job_cap()} a month)"
                    _CHOICE_SET = "A set number of manuscripts"
                    _CHOICE_UNLIMITED = "Unlimited"
                    with st.form("sa_job_cap_form"):
                        _cap_sel = st.selectbox("User ", list(_cap_by_label.keys()),
                                                key="sa_cap_user")
                        _cap_mode = st.radio(
                            "Allowance",
                            [_CHOICE_DEFAULT, _CHOICE_SET, _CHOICE_UNLIMITED],
                            key="sa_cap_mode",
                        )
                        _cap_n = st.number_input(
                            "Manuscripts a month", min_value=1, max_value=10000,
                            value=auth.default_job_cap(), step=1, key="sa_cap_n",
                            help=f"Used only with '{_CHOICE_SET}'.",
                        )
                        _cap_go = st.form_submit_button("Apply allowance")
                    if _cap_go:
                        _target = _cap_by_label[_cap_sel]
                        if _cap_mode == _CHOICE_DEFAULT:
                            auth.set_job_cap(_target["id"], None)
                            st.success(
                                f'{_target["username"]} now uses the deployment default '
                                f"({auth.default_job_cap()} manuscripts a month)."
                            )
                        elif _cap_mode == _CHOICE_UNLIMITED:
                            auth.set_job_cap(_target["id"], 0)
                            st.success(f'{_target["username"]}: unlimited manuscripts.')
                        else:
                            auth.set_job_cap(_target["id"], int(_cap_n))
                            st.success(
                                f'{_target["username"]}: {int(_cap_n)} manuscripts a month.'
                            )

                    with st.expander("Monthly token cap (safety net)"):
                        st.caption(
                            "Separate from the manuscript allowance and rarely needed. A "
                            "manuscript has ranged from 102k to 926k tokens across real "
                            "jobs, so this guards against one very large document rather "
                            "than counting work. Blank restores the deployment default "
                            f"({auth.default_token_cap():,}; 0 means no limit)."
                        )
                        with st.form("sa_cap_form"):
                            _tok_sel = st.selectbox("User", list(_cap_by_label.keys()),
                                                    key="sa_tok_user")
                            _cap_val = st.text_input(
                                "Monthly token cap", value="",
                                placeholder="leave blank for the default")
                            _tok_go = st.form_submit_button("Apply token cap")
                        if _tok_go:
                            _target = _cap_by_label[_tok_sel]
                            _raw = _cap_val.strip().replace(",", "")
                            if not _raw:
                                auth.set_token_cap(_target["id"], None)
                                st.success(
                                    f'{_target["username"]} now uses the deployment default.')
                            elif _raw.isdigit():
                                auth.set_token_cap(_target["id"], int(_raw))
                                st.success(
                                    f'{_target["username"]}: '
                                    + ("no limit." if int(_raw) == 0
                                       else f"{int(_raw):,} tokens a month.")
                                )
                            else:
                                # Named rather than silently ignored: a cap that looks
                                # applied but was not is the worst of the three outcomes.
                                st.error(f"'{_cap_val}' is not a number. Nothing was changed.")

                    st.markdown("**Change a user's role**")
                    by_label = {
                        f'{u["username"]} (id {u["id"]}, {u.get("role") or "member"})': u
                        for u in users
                    }
                    with st.form("sa_role_form"):
                        sel = st.selectbox("User", list(by_label.keys()))
                        new_role = st.selectbox("New role", ["member", "admin", "superadmin"])
                        submitted = st.form_submit_button("Apply role change")
                    if submitted:
                        target = by_label[sel]
                        cur_role = target.get("role") or "member"
                        # Guard: never demote the last remaining superadmin.
                        if cur_role == "superadmin" and new_role != "superadmin" \
                                and auth.count_superadmins() <= 1:
                            st.error("Cannot demote the last remaining superadmin.")
                        elif new_role == cur_role:
                            st.info("Role unchanged.")
                        else:
                            auth.set_user_role(target["id"], new_role)
                            if target["id"] == st.session_state.get("user_id"):
                                st.session_state.role = new_role  # keep session in sync
                            st.success(
                                f"{target['username']} is now **{new_role}** (was {cur_role})."
                            )
                            st.rerun()
            except Exception as e:
                st.error(f"Could not load users: {e}")

        # ---- Jobs (trace + control) ---------------------------------------
        with sa_jobs:
            try:
                colf, coln = st.columns([2, 1])
                status_filter = colf.selectbox(
                    "Filter by status", ["(all)", "queued", "running", "done", "error"],
                    key="sa_job_status",
                )
                limit = coln.number_input("Max rows", 10, 1000, 100, step=10, key="sa_job_limit")
                jobs = auth.fetch_all_jobs(
                    limit=int(limit),
                    status=None if status_filter == "(all)" else status_filter,
                )
                if not jobs:
                    st.info("No jobs match this filter.")
                else:
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "id": j["id"], "user": j.get("username") or j.get("user_id"),
                                "file": j.get("filename"), "status": j.get("status"),
                                "stage": j.get("stage"),
                                "progress": f'{int((j.get("progress") or 0) * 100)}%',
                                "created": j.get("created_at"), "finished": j.get("finished_at"),
                                "error": (j.get("error_message") or "")[:80],
                            }
                            for j in jobs
                        ]),
                        width="stretch", hide_index=True,
                    )

                    st.markdown("**Control a job**")
                    job_ids = [j["id"] for j in jobs]
                    cj1, cj2, cj3 = st.columns([2, 1, 1])
                    job_id = cj1.selectbox("Job id", job_ids, key="sa_job_pick")
                    if cj2.button("♻️ Requeue", key="sa_job_requeue"):
                        if auth.requeue_job(int(job_id)):
                            st.success(f"Job {job_id} re-queued.")
                            st.rerun()
                        else:
                            st.error("Requeue failed.")
                    if cj3.button("🛑 Cancel", key="sa_job_cancel"):
                        if auth.cancel_job(int(job_id)):
                            st.success(f"Job {job_id} cancelled.")
                            st.rerun()
                        else:
                            st.warning("Only queued/running jobs can be cancelled.")

                    detail = auth.get_job(int(job_id))
                    if detail and detail.get("error_message"):
                        with st.expander(f"Error detail for job {job_id}"):
                            st.code(detail["error_message"])
            except Exception as e:
                st.error(f"Could not load jobs: {e}")

        # ---- Audit log & security -----------------------------------------
        with sa_audit:
            try:
                st.markdown("**Processing audit log** (non-anonymized)")
                fa, fb, fc = st.columns([1, 1, 2])
                a_status = fa.selectbox(
                    "Status", ["(all)", "Success", "Failed"], key="sa_audit_status"
                )
                a_limit = fb.number_input("Max rows", 10, 2000, 200, step=10, key="sa_audit_limit")
                a_search = fc.text_input("Filename contains", key="sa_audit_search")
                logs = auth.fetch_process_logs(
                    limit=int(a_limit),
                    status=None if a_status == "(all)" else a_status,
                    search=a_search,
                )
                if logs:
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "time": l.get("timestamp"),
                                "user": l.get("username") or l.get("user_id"),
                                "file": l.get("filename"), "status": l.get("status"),
                                "paras": l.get("paragraphs_count"),
                                "edit": l.get("edit_style"), "ref": l.get("ref_style"),
                                "secs": round(l.get("duration_seconds") or 0, 1),
                                "error": (l.get("error_message") or "")[:80],
                            }
                            for l in logs
                        ]),
                        width="stretch", hide_index=True,
                    )
                else:
                    st.info("No audit records match this filter.")

                st.divider()
                st.markdown("**Security — failed logins & lockouts**")
                locked = auth.locked_out_usernames()
                if locked:
                    st.warning("Currently locked out: " + ", ".join(locked))
                    lc1, lc2 = st.columns([2, 1])
                    who = lc1.selectbox("Clear lockout for", locked, key="sa_unlock_pick")
                    if lc2.button("🔓 Clear lockout", key="sa_unlock_btn"):
                        auth.clear_login_lockout(who)
                        st.success(f"Lockout cleared for {who}.")
                        st.rerun()
                else:
                    st.success("No accounts are currently locked out.")

                attempts = auth.fetch_recent_login_attempts(100)
                if attempts:
                    with st.expander(f"Recent failed-login attempts ({len(attempts)})"):
                        st.dataframe(pd.DataFrame(attempts), width="stretch", hide_index=True)
            except Exception as e:
                st.error(f"Could not load audit/security data: {e}")
