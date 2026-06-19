"""Manuscript processing pipeline + background worker.

`run_pipeline` is the full editing/analysis flow extracted from the Streamlit
button handler so it can run inside a background worker thread. The worker
polls the DB-backed `jobs` queue (auth.py), so processing is non-blocking and
survives the user closing the tab; interrupted jobs are re-queued on startup.
"""
from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional

import config as app_config
import auth
from editor import (
    align_global_citations,
    build_jats_xml,
    build_journal_report,
    enforce_author_limit,
    generate_ai_review,
    generate_cover_letter,
    generate_report,
    generate_redline_docx,
    generate_title_abstract_polish,
    markdown_to_docx,
    process_document_async,
    read_docx,
    recommend_journals,
    validate_jats,
)


def _sanitize_recommended(recommended) -> list:
    """Keep only JSON-serializable, display-relevant fields (drops embeddings;
    casts numpy floats)."""
    out = []
    for j in recommended:
        fit_score = j.get("fit_score")
        out.append({
            "name": j.get("name"),
            "score": float(j.get("score", 0) or 0),
            "fit_score": float(fit_score) if fit_score is not None else None,
            "impact_factor": j.get("impact_factor"),
            "publisher": j.get("publisher", "Unknown"),
            "topics": list(j.get("topics", [])),
            "matched_topics": list(j.get("matched_topics", [])),
            "matched_keywords": list(j.get("matched_keywords", [])),
            "fit_label": j.get("fit_label", ""),
            "fit_verdict": j.get("fit_verdict", ""),
            "confidence": j.get("confidence", ""),
            "risk_factors": list(j.get("risk_factors", [])),
            "rank": j.get("rank"),
            "reason": j.get("reason", ""),
        })
    return out


def run_pipeline(opts: Dict[str, Any], input_path: str,
                 progress_cb: Optional[Callable[[float, str], None]] = None) -> Dict[str, Any]:
    """Run the full manuscript pipeline. `opts` carries non-secret options;
    LLM settings (incl. the API key) are resolved server-side, never stored on
    the job. Returns a JSON-serializable result dict."""
    def progress(frac: float, stage: str) -> None:
        if progress_cb:
            progress_cb(min(max(frac, 0.0), 1.0), stage)

    llm_settings = app_config.get_llm_settings()
    edit_style = opts["edit_style"]
    ref_style = opts["ref_style"]
    lang_type = opts["lang_type"]
    custom_dict = opts.get("custom_dict", "")
    use_crossref = opts.get("use_crossref", True)
    reorder_citations = opts.get("reorder_citations", True)
    enabled_rule_ids = opts.get("enabled_rule_ids")
    custom_rules = opts.get("custom_rules", "")
    ai_review_enabled = opts.get("ai_review_enabled", True)
    user_id = opts["user_id"]
    filename = opts.get("filename", "manuscript.docx")

    start_time = time.time()
    progress(0.02, "Reading document...")
    original_paragraphs = read_docx(input_path)
    paras_count = len(original_paragraphs)
    if not original_paragraphs:
        raise ValueError("Document appears to be empty.")

    # Kick off the AI peer reviewer in parallel with copyediting.
    review_pool = review_future = None
    if ai_review_enabled:
        review_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        review_future = review_pool.submit(
            generate_ai_review, "\n".join(original_paragraphs), llm_settings,
        )

    progress(0.05, "Analyzing and copyediting (parallel chunks)...")

    def chunk_progress(frac: float) -> None:
        progress(0.05 + frac * 0.55, "Copyediting manuscript...")

    edited_paragraphs = process_document_async(
        original_paragraphs, llm_settings, edit_style, ref_style, lang_type,
        custom_dict, use_crossref, chunk_progress, enabled_rule_ids, custom_rules,
    )

    if reorder_citations:
        progress(0.62, "Aligning citations & sorting bibliography...")
        edited_paragraphs = align_global_citations(
            edited_paragraphs, llm_settings, ref_style, enabled_rule_ids,
        )

    edited_paragraphs = enforce_author_limit(edited_paragraphs, enabled_rule_ids)

    progress(0.68, "Generating redline document...")
    out_dir = app_config.output_dir()
    ts = int(time.time())
    redline_path = out_dir / f"user_{user_id}_{ts}_redline.docx"
    generate_redline_docx(input_path, edited_paragraphs, str(redline_path))

    progress(0.74, "Generating editorial report...")
    report = generate_report(
        edit_style, ref_style, lang_type, use_crossref, custom_dict,
        enabled_rule_ids, custom_rules,
    )

    progress(0.78, "Recommending journals...")
    proxy_abstract = " ".join(original_paragraphs[:15])[:1500]
    recommended = recommend_journals(proxy_abstract, llm_settings)
    journal_report_md = build_journal_report(recommended)

    review_report_path = out_dir / f"user_{user_id}_{ts}_review.docx"
    journal_report_path = out_dir / f"user_{user_id}_{ts}_journals.docx"
    markdown_to_docx(report, str(review_report_path))
    markdown_to_docx(journal_report_md, str(journal_report_path))

    progress(0.84, "Generating JATS/XML production file...")
    jats_path = out_dir / f"user_{user_id}_{ts}_jats.xml"
    best_journal_name = recommended[0]["name"] if recommended else None
    today = datetime.date.today()
    jats_metadata = {
        "pub_date": today.isoformat(),
        "copyright_year": today.year,
        "copyright_holder": app_config.jats_copyright_holder() or None,
        "license_url": app_config.jats_license_url() or None,
        "license_text": app_config.jats_license_text() or None,
    }
    jats_xml = build_jats_xml(
        edited_paragraphs, journal_title=best_journal_name, metadata=jats_metadata,
    )
    jats_path.write_text(jats_xml, encoding="utf-8")
    jats_ok, jats_issues = validate_jats(jats_xml)

    ai_review_md = ""
    ai_review_path = ""
    if review_future is not None:
        progress(0.88, "Finalizing AI peer review...")
        try:
            ai_review_md = review_future.result()
        except Exception as review_exc:
            ai_review_md = f"_AI peer review failed: {review_exc}_"
        finally:
            review_pool.shutdown(wait=False)
        ai_review_path = out_dir / f"user_{user_id}_{ts}_aireview.docx"
        markdown_to_docx(ai_review_md, str(ai_review_path))

    progress(0.92, "Generating cover letter...")
    best_journal = recommended[0]["name"] if recommended else "the journal"
    cover_letter = generate_cover_letter(proxy_abstract, best_journal, llm_settings)

    progress(0.96, "Polishing abstract & titles...")
    polished_titles = generate_title_abstract_polish(proxy_abstract, llm_settings)

    duration = time.time() - start_time
    auth.log_job(
        user_id, filename, paras_count, edit_style, ref_style, lang_type,
        duration, "Success", str(redline_path), "",
        journal_report_path=str(journal_report_path),
        review_report_path=str(review_report_path),
        ai_review_path=str(ai_review_path) if ai_review_path else "",
        jats_path=str(jats_path),
    )

    progress(1.0, "Complete")
    return {
        "redline_path": str(redline_path),
        "journal_report_path": str(journal_report_path),
        "review_report_path": str(review_report_path),
        "ai_review_path": str(ai_review_path) if ai_review_path else "",
        "jats_path": str(jats_path),
        "report_md": report,
        "recommended": _sanitize_recommended(recommended),
        "cover_letter": cover_letter,
        "polished_titles": polished_titles,
        "ai_review_md": ai_review_md,
        "best_journal": best_journal,
        "jats_ok": bool(jats_ok),
        "jats_issues": list(jats_issues),
        "edit_style": edit_style,
        "paras_count": paras_count,
        "duration": round(duration, 1),
    }


# --- Background worker (single daemon thread per process) ---

_worker_started = False
_worker_lock = threading.Lock()


def _process_job(job: Dict[str, Any]) -> None:
    job_id = job["id"]
    try:
        opts = json.loads(job["options_json"] or "{}")
    except Exception:
        opts = {}

    def cb(frac: float, stage: str) -> None:
        auth.update_job_progress(job_id, frac, stage)

    try:
        result = run_pipeline(opts, job["input_path"], cb)
        auth.complete_job(job_id, json.dumps(result))
    except Exception as exc:
        traceback.print_exc()
        # Record a failed entry in history too, so the user sees the error there.
        try:
            auth.log_job(
                opts.get("user_id"), opts.get("filename", ""), 0,
                opts.get("edit_style", ""), opts.get("ref_style", ""),
                opts.get("lang_type", ""), 0.0, "Error", "", str(exc),
            )
        except Exception:
            pass
        auth.fail_job(job_id, str(exc))
    finally:
        # The uploaded input file is no longer needed once the job is done.
        path = job.get("input_path")
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _worker_loop() -> None:
    while True:
        try:
            job = auth.claim_next_job()
            if not job:
                time.sleep(2)
                continue
            _process_job(job)
        except Exception as exc:
            print(f"[worker] loop error: {exc}")
            time.sleep(2)


def _worker_count() -> int:
    """How many job-worker threads to run per process. Defaults to 1 (serial);
    set JOB_WORKERS>1 to process several users' jobs in parallel. Safe with
    Postgres because claim_next_job claims each job atomically."""
    try:
        return max(1, int(os.getenv("JOB_WORKERS", "1")))
    except (TypeError, ValueError):
        return 1


def start_worker_once() -> None:
    """Start the job-worker thread pool once per process (JOB_WORKERS threads).
    Re-queues jobs interrupted by a previous crash/restart before they begin."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        try:
            n = auth.requeue_running_jobs()
            if n:
                print(f"[worker] re-queued {n} interrupted job(s)")
        except Exception as exc:
            print(f"[worker] requeue failed: {exc}")
        workers = _worker_count()
        for i in range(workers):
            threading.Thread(
                target=_worker_loop, name=f"job-worker-{i}", daemon=True
            ).start()
        print(f"[worker] started {workers} job worker(s)")
