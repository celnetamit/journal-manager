"""Streamlit entrypoint for Manuscript Editor Pro.

This module wires together:
  - `config.py`   env-var-driven configuration (DB URL, paths, API key)
  - `auth.py`     user auth + analytics (Postgres or SQLite)
  - `editor.py`   document processing pipeline (Gemini 2.5 Pro)
"""
from __future__ import annotations

import os
import tempfile
import time

import pandas as pd
import streamlit as st

try:
    from streamlit_cookies_manager import CookieManager  # type: ignore
    COOKIE_MANAGER_AVAILABLE = True
except ModuleNotFoundError:
    try:
        from streamlit_cookies_manager_v2 import CookieManager  # type: ignore
        COOKIE_MANAGER_AVAILABLE = True
    except ModuleNotFoundError:
        COOKIE_MANAGER_AVAILABLE = False

        class CookieManager:  # type: ignore[no-redef]
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

import auth
import config as app_config
from editor import (
    align_global_citations,
    generate_cover_letter,
    generate_redline_docx,
    generate_report,
    generate_title_abstract_polish,
    process_document_async,
    read_docx,
    recommend_journals,
    test_embedding,
    test_text_generation,
)


st.set_page_config(page_title="Manuscript Editor Pro", layout="wide", page_icon="📝")

cookies = CookieManager(prefix="manuscript-editor-pro/")
if not cookies.ready():
    st.stop()

auth.init_auth()

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
    token = str(cookies.get("auth_token", "") or "")
    if not token:
        return
    resolved = auth.resolve_login_token(token)
    if not resolved:
        _clear_auth_cookie()
        return
    st.session_state.user_id = resolved["user_id"]
    st.session_state.username = resolved["username"]
    st.session_state.login_token = token


_restore_auth_from_cookie()
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
    "ollama": "Ollama",
    "openai-compatible": "OpenAI-compatible",
    "custom": "Custom",
}
_PROVIDER_REQUIREMENTS = {
    "gemini": "Needs an API key. Base URL is not used.",
    "openrouter": "Needs an API key and base URL.",
    "ollama": "Needs a base URL. API key is usually not required.",
    "openai-compatible": "Needs a base URL. API key is optional depending on the endpoint.",
    "custom": "Needs a base URL. API key and models depend on the endpoint.",
}
_API_KEY_PROVIDERS = {"gemini", "openrouter"}
_BASE_URL_PROVIDERS = {"openrouter", "ollama", "openai-compatible", "custom"}


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider.title())


def _llm_setting_errors(settings: dict[str, str]) -> list[str]:
    provider = settings.get("provider", "gemini")
    errors: list[str] = []
    if provider in _API_KEY_PROVIDERS and not settings.get("api_key", "").strip():
        errors.append(f"{_provider_label(provider)} requires an API key.")
    if provider in _BASE_URL_PROVIDERS and not settings.get("base_url", "").strip():
        errors.append(f"{_provider_label(provider)} requires a base URL.")
    if not settings.get("text_model", "").strip():
        errors.append("Text model cannot be empty.")
    if not settings.get("embed_model", "").strip():
        errors.append("Embedding model cannot be empty.")
    return errors

llm_settings = app_config.get_llm_settings()

if is_authenticated:
    with st.sidebar:
        st.success(f"Logged in as **{st.session_state.username}**")
        if st.button("Logout"):
            if st.session_state.login_token:
                auth.revoke_login_token(st.session_state.login_token)
            _clear_auth_cookie()
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.login_token = ""
            st.rerun()

        st.header("⚙️ LLM Settings")
        provider_order = list(_PROVIDER_LABELS.keys())
        current_provider = llm_settings["provider"] if llm_settings["provider"] in _PROVIDER_LABELS else "gemini"
        provider_index = provider_order.index(current_provider)

        with st.form("llm_settings_form"):
            provider = st.selectbox(
                "LLM Provider",
                provider_order,
                index=provider_index,
                format_func=_provider_label,
                help="Pick the backend that will power editing, citation alignment, journal matching, and cover-letter generation.",
            )

            defaults = app_config.default_settings_for_provider(provider)
            st.caption(_PROVIDER_REQUIREMENTS.get(provider, "Configure the model settings for this provider."))

            needs_api_key = provider in {"gemini", "openrouter"}
            needs_base_url = provider in {"openrouter", "ollama", "openai-compatible", "custom"}
            api_key = st.text_input(
                "API Key",
                value=llm_settings["api_key"],
                type="password",
                help="Required for Gemini and OpenRouter. Optional for other providers.",
            )

            if needs_base_url:
                base_url = st.text_input(
                    "Base URL",
                    value=llm_settings["base_url"] or defaults["base_url"],
                    help="The provider endpoint, for example OpenRouter or a local Ollama URL.",
                )
            else:
                base_url = ""
                st.caption("Gemini uses Google-managed endpoints, so no base URL is needed.")

            text_model = st.text_input(
                "Text model",
                value=llm_settings["text_model"] or defaults["text_model"],
                help="This model will handle editing, citation cleanup, cover letters, and title polish.",
            )

            embed_model = st.text_input(
                "Embedding model",
                value=llm_settings["embed_model"] or defaults["embed_model"],
                help="This model is used for journal recommendations.",
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
                app_config.save_llm_settings(
                    {
                        "provider": provider,
                        "api_key": api_key,
                        "base_url": "" if provider == "gemini" else base_url,
                        "text_model": text_model,
                        "embed_model": embed_model,
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
        custom_dict = st.text_area(
            "Custom Dictionary / Acronyms",
            placeholder="e.g. mTOR, mRNA, do not change capitalization of ABC.",
        )
else:
    st.info("Log in to access LLM settings and manuscript tools.")


# --- Auth gate ---

if not st.session_state.user_id:
    st.title("🔐 Manuscript Editor Pro - Login")
    st.markdown("Welcome to the AI-powered scientific copyediting and journaling platform.")

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
            uid = auth.login(lu, lp)
            if uid:
                st.session_state.user_id = uid
                st.session_state.username = lu
                if remember_me:
                    st.session_state.login_token = auth.issue_login_token(uid)
                    cookies["auth_token"] = st.session_state.login_token
                    cookies.save()
                else:
                    st.session_state.login_token = ""
                    _clear_auth_cookie()
                st.rerun()
            st.error("Invalid credentials.")
    with tab_reg:
        ru = st.text_input("Username", key="ru")
        rp = st.text_input("Password", type="password", key="rp")
        if st.button("Create Account"):
            if auth.register(ru, rp):
                st.success("Account created! Please login in the other tab.")
            else:
                st.error("Username already taken or invalid.")
    st.stop()


# --- Main UI ---

st.title("📝 Automated Manuscript Copyediting & Proofreading")

tab_editor, tab_test, tab_history, tab_analytics = st.tabs(
    ["📝 Editor", "🧪 Model Test", "📚 My History", "📈 Analytics"]
)

with tab_editor:
    st.markdown(
        "Upload your `.docx` manuscript. Our engine will proofread it, "
        "generate a redline tracking document, and offer advanced publication tools."
    )

    uploaded_file = st.file_uploader("Upload Manuscript (.docx)", type=["docx"])

    if uploaded_file is not None:
        if st.button("Process Manuscript", type="primary"):
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

            status_text = st.empty()
            progress_bar = st.progress(0)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_in:
                tmp_in.write(uploaded_file.read())
                tmp_in_path = tmp_in.name

            start_time = time.time()
            status_val = "Success"
            err_msg = ""
            paras_count = 0

            try:
                status_text.info("Reading document...")
                original_paragraphs = read_docx(tmp_in_path)
                paras_count = len(original_paragraphs)

                if not original_paragraphs:
                    st.error("Document appears to be empty.")
                else:
                    status_text.info("Analyzing and Copyediting manuscript... (parallel chunks)")

                    def update_progress(fraction: float) -> None:
                        progress_bar.progress(min(max(fraction, 0.0), 1.0))

                    edited_paragraphs = process_document_async(
                        original_paragraphs, llm_settings, edit_style,
                        ref_style, lang_type, custom_dict, use_crossref, update_progress,
                    )

                    if reorder_citations:
                        status_text.info("Performing Global Citation Alignment & Bibliography Sorting...")
                        edited_paragraphs = align_global_citations(edited_paragraphs, llm_settings, ref_style)

                    status_text.info("Generating Redline tracking document...")

                    out_dir = app_config.output_dir()
                    perm_out_path = out_dir / f"user_{st.session_state.user_id}_{int(time.time())}_redline.docx"
                    generate_redline_docx(tmp_in_path, edited_paragraphs, str(perm_out_path))

                    status_text.info("Generating Editorial Report and Publication Tools...")
                    report = generate_report(edit_style, ref_style, lang_type, use_crossref, custom_dict)

                    proxy_abstract = " ".join(original_paragraphs[:15])[:1500]
                    recommended = recommend_journals(proxy_abstract, llm_settings)

                    status_text.info("Generating Cover Letter...")
                    best_journal = recommended[0]["name"] if recommended else "the journal"
                    cover_letter = generate_cover_letter(proxy_abstract, best_journal, llm_settings)

                    status_text.info("Polishing Abstract & Titles...")
                    polished_titles = generate_title_abstract_polish(proxy_abstract, llm_settings)

                    status_text.empty()
                    progress_bar.empty()
                    st.success("Manuscript processing complete!")

                    duration = time.time() - start_time
                    auth.log_job(
                        st.session_state.user_id, uploaded_file.name, paras_count,
                        edit_style, ref_style, lang_type, duration, status_val,
                        str(perm_out_path), err_msg,
                    )

                    res_col1, res_col2 = st.columns([1.5, 1])
                    with res_col1:
                        st.subheader("📊 Editorial Report")
                        st.markdown(report)

                        st.subheader("📚 Semantic Journal Recommendations")
                        for i, j in enumerate(recommended, 1):
                            score = j.get("score", 0)
                            match_pct = f"{int(score * 100)}% Match" if score > 0 else "Recommended"
                            impact_str = f" | Impact Factor: {j.get('impact_factor')}" if j.get("impact_factor") else ""
                            with st.expander(f"**{i}. {j['name']}** ({match_pct}{impact_str})", expanded=(i == 1)):
                                st.write(f"**Publisher:** {j.get('publisher', 'Unknown')}")
                                topics = j.get("topics", [])
                                st.write(f"**Focus Topics:** {', '.join(topics).title()}")

                        with st.expander("✉️ Auto-Generated Submission Cover Letter", expanded=False):
                            st.info(f"Custom tailored for: **{best_journal}**")
                            st.markdown(cover_letter)

                        with st.expander("💡 Title & Abstract Polish", expanded=False):
                            st.markdown(polished_titles)

                    with res_col2:
                        st.subheader("📥 Download Results")
                        st.info("Your redline document features native Word Track Changes.")
                        with open(perm_out_path, "rb") as f:
                            st.download_button(
                                label="Download Redline Manuscript",
                                data=f,
                                file_name=f"manuscript_{edit_style[:4]}_redline.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                type="primary",
                            )
            except Exception as e:
                status_val = "Error"
                err_msg = str(e)
                st.error(f"Processing error: {err_msg}")
                duration = time.time() - start_time
                auth.log_job(
                    st.session_state.user_id, uploaded_file.name, paras_count,
                    edit_style, ref_style, lang_type, duration, status_val, "", err_msg,
                )
            finally:
                if os.path.exists(tmp_in_path):
                    os.remove(tmp_in_path)


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
        st.session_state.llm_text_test_prompt = (
            "Write one short sentence describing a manuscript editing assistant."
        )
    if "llm_embed_test_text" not in st.session_state:
        st.session_state.llm_embed_test_text = (
            "Machine learning helps with scientific manuscript recommendations."
        )

    st.markdown("**One-click prompt presets**")
    preset_col1, preset_col2, preset_col3 = st.columns(3)
    with preset_col1:
        if st.button("Gemini preset", width="stretch"):
            st.session_state.llm_text_test_prompt = (
                "Write one concise sentence about a scientific manuscript assistant."
            )
    with preset_col2:
        if st.button("OpenRouter preset", width="stretch"):
            st.session_state.llm_text_test_prompt = (
                "Return valid JSON with keys provider, model, and status, each as a short string."
            )
    with preset_col3:
        if st.button("Ollama preset", width="stretch"):
            st.session_state.llm_text_test_prompt = (
                "Write a short paragraph explaining why local LLMs are useful for private document editing."
            )

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
        df_hist = pd.DataFrame(rows)
        for idx, row in df_hist.iterrows():
            with st.container():
                cols = st.columns([2, 1, 1, 1])
                cols[0].write(f"**{row['filename']}** ({row['timestamp']})")
                cols[1].write(row["edit_style"])
                cols[2].write(row["status"])
                rp = row.get("redline_path") or ""
                if row["status"] == "Success" and rp and os.path.exists(rp):
                    with open(rp, "rb") as rf:
                        cols[3].download_button(
                            "Download", data=rf,
                            file_name=f"historical_redline_{idx}.docx",
                            key=f"dl_{idx}",
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
