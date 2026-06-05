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
)


st.set_page_config(page_title="Manuscript Editor Pro", layout="wide", page_icon="📝")
auth.init_auth()

if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None


# --- Sidebar: API key + style settings ---

with st.sidebar:
    if st.session_state.username:
        st.success(f"Logged in as **{st.session_state.username}**")
        if st.button("Logout"):
            st.session_state.user_id = None
            st.session_state.username = None
            st.rerun()

    st.header("⚙️ Configuration")
    saved_key = app_config.get_gemini_api_key()
    gemini_api_key = st.text_input("Gemini API Key", value=saved_key, type="password",
                                   help="Stored in config.json (gitignored). In production set GEMINI_API_KEY env var instead.")
    if st.button("Save API Key"):
        app_config.save_gemini_api_key(gemini_api_key)
        st.success("API Key saved.")

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


# --- Auth gate ---

if not st.session_state.user_id:
    st.title("🔐 Manuscript Editor Pro - Login")
    st.markdown("Welcome to the AI-powered scientific copyediting and journaling platform.")

    tab_login, tab_reg = st.tabs(["Login", "Register"])
    with tab_login:
        lu = st.text_input("Username", key="lu")
        lp = st.text_input("Password", type="password", key="lp")
        if st.button("Login", type="primary"):
            uid = auth.login(lu, lp)
            if uid:
                st.session_state.user_id = uid
                st.session_state.username = lu
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

tab_editor, tab_history, tab_analytics = st.tabs(["📝 Editor", "📚 My History", "📈 Analytics"])

with tab_editor:
    st.markdown(
        "Upload your `.docx` manuscript. Our engine will proofread it, "
        "generate a redline tracking document, and offer advanced publication tools."
    )

    uploaded_file = st.file_uploader("Upload Manuscript (.docx)", type=["docx"])

    if uploaded_file is not None:
        if st.button("Process Manuscript", type="primary"):
            if not gemini_api_key:
                st.error("Please enter your Gemini API Key in the sidebar to continue.")
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
                        original_paragraphs, gemini_api_key, edit_style,
                        ref_style, lang_type, custom_dict, use_crossref, update_progress,
                    )

                    if reorder_citations:
                        status_text.info("Performing Global Citation Alignment & Bibliography Sorting...")
                        edited_paragraphs = align_global_citations(edited_paragraphs, gemini_api_key, ref_style)

                    status_text.info("Generating Redline tracking document...")

                    out_dir = app_config.output_dir()
                    perm_out_path = out_dir / f"user_{st.session_state.user_id}_{int(time.time())}_redline.docx"
                    generate_redline_docx(tmp_in_path, edited_paragraphs, str(perm_out_path))

                    status_text.info("Generating Editorial Report and Publication Tools...")
                    report = generate_report(edit_style, ref_style, lang_type, use_crossref, custom_dict)

                    proxy_abstract = " ".join(original_paragraphs[:15])[:1500]
                    recommended = recommend_journals(proxy_abstract, gemini_api_key)

                    status_text.info("Generating Cover Letter...")
                    best_journal = recommended[0]["name"] if recommended else "the journal"
                    cover_letter = generate_cover_letter(proxy_abstract, best_journal, gemini_api_key)

                    status_text.info("Polishing Abstract & Titles...")
                    polished_titles = generate_title_abstract_polish(proxy_abstract, gemini_api_key)

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
            st.dataframe(df, use_container_width=True)
            st.caption("Per-user rows are never shown — only daily aggregates.")
        else:
            st.info("No analytics recorded yet.")
    except Exception as e:
        st.error(f"Could not load analytics: {e}")
