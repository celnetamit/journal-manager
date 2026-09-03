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
import uuid
import zipfile

from docx.opc.exceptions import PackageNotFoundError
from typing import Any, Callable, Dict, Optional

import config as app_config
import auth
from docxmodel import read_structure
from house_layout import check_all as house_check
from science_format import check_all as science_format_check
from proofread import proofread as run_proofread
from edit_guards import (
    fix_trailing_citations,
    orphaned_formula_queries,
    restore_protected_text,
)
from science_format import (
    enforce_all_formula_subscripts,
    enforce_language_variant,
    enforce_science_symbols,
)
from editor import (
    align_global_citations,
    build_jats_xml,
    build_journal_report,
    build_plagiarism_report,
    collect_table_texts,
    enforce_author_limit,
    enforce_drop_redundant_paren_citation,
    enforce_element_citation_brackets,
    enforce_keywords_format,
    enforce_reference_year_only,
    enforce_temperature_spacing,
    generate_ai_review,
    generate_cover_letter,
    generate_report,
    generate_redline_docx,
    generate_title_abstract_polish,
    markdown_to_docx,
    plagiarism_scan,
    process_document_async,
    read_docx,
    _generate_text,
    recommend_journals,
    validate_jats,
    verify_serper_key,
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


def skip_reason(exc: BaseException) -> str:
    """Why a check was skipped, in words, always.

    `str(exc)` is empty for several exception classes — `NotImplementedError` among
    them — so "House-style layout check was skipped: " reached the editor with nothing
    after the colon on 8% of real manuscripts. There is no way to tell that from a
    document that genuinely had no layout to check.
    """
    return str(exc) or type(exc).__name__


def run_pipeline(opts: Dict[str, Any], input_path: str,
                 progress_cb: Optional[Callable[[float, str], None]] = None,
                 job_id: Optional[Any] = None) -> Dict[str, Any]:
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

    warnings: list = []

    start_time = time.time()
    progress(0.02, "Reading document...")
    try:
        original_paragraphs = read_docx(input_path)
    except (zipfile.BadZipFile, PackageNotFoundError, KeyError) as open_exc:
        # A .docx is a zip. Three of 400 real manuscripts had a corrupt embedded
        # image, and the author got the raw "Bad CRC-32 for file 'word/media/
        # image1.png'" — true, and meaningless to the person who has to act on it.
        raise ValueError(
            "This .docx could not be opened — the file appears to be damaged "
            f"({open_exc}). Open it in Word and use File > Save As to write a fresh "
            "copy, then upload that."
        ) from open_exc
    paras_count = len(original_paragraphs)

    # Everything the plain text reader drops — formatting, headings, list markers,
    # tables, page geometry. Parsed once here and reused; a failure to parse the
    # structure must not stop the copyedit, which is what the author is waiting for.
    structure = None
    layout_findings: list = []
    try:
        structure = read_structure(input_path)
        layout_findings = house_check(structure)
        # Species italics and on-the-line sub/superscripts. Same panel:
        # to an editor these are house style, not a separate category.
        layout_findings += science_format_check(structure)
    except Exception as struct_exc:                              # noqa: BLE001
        warnings.append(
            f"House-style layout check was skipped: {skip_reason(struct_exc)}")
    if not original_paragraphs:
        raise ValueError("Document appears to be empty.")

    # OPTIONAL Serper (Google Scholar) DOI fallback. Only active when a key is
    # configured AND the toggle is on. Validated once up front: if the token is
    # bad/expired we notify the user (via warnings) and proceed with Serper off,
    # so the run still behaves exactly as it does without Serper.
    use_serper = False
    serper_key = app_config.get_serper_api_key()
    if opts.get("use_serper", True) and serper_key:
        ok, msg = verify_serper_key(serper_key)
        if ok:
            use_serper = True
        else:
            warnings.append(f"Serper DOI fallback was disabled: {msg}")

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

    edited_paragraphs, editor_queries, skipped_chunks = process_document_async(
        original_paragraphs, llm_settings, edit_style, ref_style, lang_type,
        custom_dict, use_crossref, chunk_progress, enabled_rule_ids, custom_rules,
        use_serper=use_serper, serper_key=serper_key,
    )
    # Said out loud. A chunk the model could not answer for comes back untouched,
    # and an untouched paragraph is indistinguishable from one that needed no
    # changes — so without this the author is handed a manuscript with a hole in it
    # and nothing anywhere admits to the hole.
    skipped_paragraphs = sorted(i for c in skipped_chunks for i in c["indices"])
    if skipped_paragraphs:
        reasons = sorted({c["reason"] for c in skipped_chunks})
        warnings.append(
            f"{len(skipped_paragraphs)} of {paras_count} paragraphs could not be "
            f"copyedited and are unchanged (paragraphs "
            f"{', '.join(str(i + 1) for i in skipped_paragraphs[:12])}"
            f"{'…' if len(skipped_paragraphs) > 12 else ''}). "
            f"Reason: {reasons[0]}"
        )

    # The 11.3%. Table cells are not in `doc.paragraphs`, so nothing has ever
    # copyedited them. Sent through the same pass as the body, then written back by
    # address rather than by position — a table edit must not be able to shift the
    # body list `generate_redline_docx` pairs by index.
    table_edits: dict = {}
    table_queries: list = []
    if structure is not None and opts.get("edit_tables", True):
        try:
            table_items = collect_table_texts(structure)
            if table_items:
                progress(0.60, "Copyediting tables...")
                addresses = [addr for addr, _ in table_items]
                originals = [text for _, text in table_items]
                edited_cells, cell_queries, cell_skipped = process_document_async(
                    originals, llm_settings, edit_style, ref_style, lang_type,
                    custom_dict, use_crossref, lambda _f: None, enabled_rule_ids,
                    custom_rules, use_serper=use_serper, serper_key=serper_key,
                )
                for addr, before, after in zip(addresses, originals, edited_cells):
                    if after and after.strip() != before.strip():
                        table_edits[addr] = after
                # Deliberately NOT merged into `editor_queries`. Their `index` counts
                # into the table list, and `generate_redline_docx` reads `index` as a
                # body paragraph — merging them would anchor every table query onto an
                # unrelated paragraph, silently and in a file that still opens.
                for q in cell_queries:
                    i = q.get("index")
                    if isinstance(i, int) and 0 <= i < len(addresses):
                        t, r, c, _ = addresses[i]
                        table_queries.append(dict(
                            q, index=None,
                            query=f"[Table {t + 1}, row {r + 1}, column {c + 1}] "
                                  f"{q.get('query', '')}"))
                if cell_skipped:
                    n = sum(len(c["indices"]) for c in cell_skipped)
                    warnings.append(
                        f"{n} table cell(s) could not be copyedited and are unchanged."
                    )
        except Exception as table_exc:                           # noqa: BLE001
            warnings.append(f"Table copyediting was skipped: {table_exc}")

    if reorder_citations:
        progress(0.62, "Aligning citations & sorting bibliography...")
        edited_paragraphs = align_global_citations(
            edited_paragraphs, llm_settings, ref_style, enabled_rule_ids,
        )

    edited_paragraphs = enforce_author_limit(edited_paragraphs, enabled_rule_ids)
    edited_paragraphs = enforce_reference_year_only(edited_paragraphs, enabled_rule_ids)
    edited_paragraphs = enforce_drop_redundant_paren_citation(edited_paragraphs, enabled_rule_ids)
    edited_paragraphs = enforce_keywords_format(edited_paragraphs, enabled_rule_ids)
    edited_paragraphs = enforce_element_citation_brackets(
        edited_paragraphs, enabled_rule_ids)
    edited_paragraphs = enforce_temperature_spacing(edited_paragraphs)
    edited_paragraphs = enforce_all_formula_subscripts(edited_paragraphs)
    edited_paragraphs = enforce_science_symbols(edited_paragraphs)
    # Before `run_proofread`, so the spelling-consistency check sees the text as
    # it will be published. Reporting a clash the enforcement has just resolved
    # would put a finding in the report about text that no longer exists.
    edited_paragraphs = enforce_language_variant(edited_paragraphs, lang_type)
    edited_paragraphs = fix_trailing_citations(edited_paragraphs)

    # Edits the copyedit is not allowed to make, undone against the original — a date
    # line that lost its day and month, an algorithm step that lost its number. Each
    # restoration raises its own query: a guard that quietly overrules the copyedit is
    # the same failure as a copyedit that quietly overrules the author.
    edited_paragraphs, guard_queries = restore_protected_text(
        original_paragraphs, edited_paragraphs)
    guard_queries += orphaned_formula_queries(
        original_paragraphs, edited_paragraphs)
    editor_queries = list(editor_queries) + guard_queries

    # The proofreading pass. Deliberately after every edit and enforcement, over the
    # text as it will actually be published — proofreading the author's draft would
    # report things the copyedit has already fixed. The mechanical half needs no
    # model; the judgement half is given one when the run has it.
    progress(0.66, "Proofreading...")
    proof_findings: list = []
    try:
        proof_findings = run_proofread(
            edited_paragraphs,
            generate=_generate_text if ai_review_enabled else None,
            settings=llm_settings,
            use_llm=ai_review_enabled,
            # The copyedit has always been told the variant; the proofreader never
            # was, so it defaulted to American and reported "low centre of gravity"
            # in a London paper as a spelling error needing "center".
            lang_type=lang_type,
        )
        # Anchored in the redline as Word comments, next to the copyeditor's own
        # queries. A finding with no paragraph (a manuscript-wide inconsistency) has
        # nowhere to sit and stays in the report only.
        editor_queries = list(editor_queries) + [
            f.as_query() for f in proof_findings if f.paragraph is not None
        ]
    except Exception as proof_exc:                               # noqa: BLE001
        warnings.append(f"Proofreading pass failed: {proof_exc}")

    # OPTIONAL preliminary originality scan (web verbatim matches via Serper).
    # Only runs when Serper is active AND the user enabled it. Scans the author's
    # ORIGINAL text, not our edited version. Never blocks the run on failure.
    plagiarism = None
    if use_serper and opts.get("plagiarism_scan_enabled", False):
        progress(0.64, "Preliminary originality scan...")
        try:
            plagiarism = plagiarism_scan(original_paragraphs, serper_key)
        except Exception as scan_exc:
            warnings.append(f"Originality scan failed: {scan_exc}")

    progress(0.68, "Generating redline document...")
    out_dir = app_config.output_dir()
    # Unique per-job token so concurrent jobs never overwrite each other's
    # output files (int(time.time()) only has 1-second resolution). Prefer the
    # unique job_id; fall back to a random token when run outside the worker.
    ts = job_id if job_id is not None else uuid.uuid4().hex[:8]
    redline_path = out_dir / f"user_{user_id}_{ts}_redline.docx"
    generate_redline_docx(
        input_path, edited_paragraphs, str(redline_path), queries=editor_queries,
        table_edits=table_edits,
    )

    progress(0.74, "Generating editorial report...")
    report = generate_report(
        edit_style, ref_style, lang_type, use_crossref, custom_dict,
        enabled_rule_ids, custom_rules, queries=editor_queries, warnings=warnings,
        plagiarism=plagiarism,
    )
    report += _house_style_section(layout_findings, proof_findings)

    progress(0.78, "Recommending journals...")
    proxy_abstract = " ".join(original_paragraphs[:15])[:1500]
    recommended = recommend_journals(proxy_abstract, llm_settings, warnings=warnings)
    journal_report_md = build_journal_report(recommended)

    review_report_path = out_dir / f"user_{user_id}_{ts}_review.docx"
    journal_report_path = out_dir / f"user_{user_id}_{ts}_journals.docx"
    markdown_to_docx(report, str(review_report_path))
    markdown_to_docx(journal_report_md, str(journal_report_path))

    # Standalone, detailed originality report — only written when the scan ran.
    plagiarism_report_path = ""
    plagiarism_md = build_plagiarism_report(plagiarism)
    if plagiarism_md:
        _pp = out_dir / f"user_{user_id}_{ts}_originality.docx"
        markdown_to_docx(plagiarism_md, str(_pp))
        plagiarism_report_path = str(_pp)

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
        plagiarism_report_path=plagiarism_report_path,
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
        "filename": filename,
        "paras_count": paras_count,
        "duration": round(duration, 1),
        "warnings": warnings,
        "plagiarism": plagiarism,
        "plagiarism_report_path": plagiarism_report_path,
        # Structured as well as in the report markdown. The markdown is for reading;
        # these are for the panel that has to say "16 errors" before anyone decides
        # whether to read anything.
        "house_findings": [
            {"rule": f.rule, "severity": f.severity, "paragraph": f.paragraph,
             "message": f.message, "detail": f.detail}
            for f in layout_findings
        ],
        "proof_findings": [
            {"rule": f.rule, "severity": f.severity, "paragraph": f.paragraph,
             "message": f.message, "detail": f.fragment,
             "suggestion": f.suggestion}
            for f in proof_findings
        ],
        "tables_edited": len(table_edits),
        "skipped_paragraphs": skipped_paragraphs,
        "table_queries": table_queries,
    }


# --- Background worker (single daemon thread per process) ---

_worker_started = False
_worker_lock = threading.Lock()


class JobCancelled(Exception):
    """Raised cooperatively when a job is cancelled mid-run so the worker stops
    spending on it. Carries no error semantics — the cancelled DB state stands."""


def _process_job(job: Dict[str, Any]) -> None:
    job_id = job["id"]
    try:
        opts = json.loads(job["options_json"] or "{}")
    except Exception:
        opts = {}

    def cb(frac: float, stage: str) -> None:
        # Cooperative cancellation: bail before doing more LLM work if the job
        # was cancelled out from under us.
        if auth.job_is_cancelled(job_id):
            raise JobCancelled()
        auth.update_job_progress(job_id, frac, stage)

    try:
        result = run_pipeline(opts, job["input_path"], cb, job_id=job_id)
        auth.complete_job(job_id, json.dumps(result))
    except JobCancelled:
        print(f"[worker] job {job_id} cancelled; stopping work")
    except Exception as exc:
        traceback.print_exc()
        # `skip_reason`, not `str(exc)`. This message is rendered straight into
        # "Processing failed for **paper.docx**: {error_message}", and `str()` is
        # empty for several exception classes — `NotImplementedError` among them,
        # which is what python-docx raises on a document that has never contained a
        # list. The user was shown a failure with nothing after the colon, and the
        # history row was blank too, so there was no second place to look.
        reason = skip_reason(exc)
        try:
            auth.log_job(
                opts.get("user_id"), opts.get("filename", ""), 0,
                opts.get("edit_style", ""), opts.get("ref_style", ""),
                opts.get("lang_type", ""), 0.0, "Error", "", reason,
            )
        except Exception:
            pass
        auth.fail_job(job_id, reason)
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


def _house_style_section(layout_findings, proof_findings) -> str:
    """The layout and proofreading findings, appended to the editorial report.

    Written into the report rather than only anchored in the redline because most of
    these are about the document as a whole — a heading level that is skipped, a
    spelling used two ways, a table nobody cites. There is no single paragraph to put
    a comment on, and a finding with nowhere to sit is one nobody ever reads.

    Grouped by rule and capped: 21 identical "number range uses a hyphen" lines tell
    an editor nothing that one line and a count does not.
    """
    if not layout_findings and not proof_findings:
        return ("\n\n---\n\n## House Style & Proofreading\n\n"
                "No house-style or proofreading issues were found.\n")

    lines = ["", "", "---", "", "## House Style & Proofreading", ""]

    for title, findings in (("Layout and house style", layout_findings),
                            ("Proofreading", proof_findings)):
        if not findings:
            continue
        errors = sum(1 for f in findings if f.severity == "error")
        lines.append(f"### {title} — {len(findings)} item(s), {errors} error(s)")
        lines.append("")

        by_rule = {}
        for f in findings:
            by_rule.setdefault(f.rule, []).append(f)

        for rule, group in sorted(by_rule.items(),
                                  key=lambda kv: (-len(kv[1]), kv[0])):
            head = group[0]
            where = ""
            if head.paragraph is not None:
                where = f" (first at paragraph {head.paragraph + 1})"
            lines.append(f"- **{rule}** — {len(group)} item(s){where}")
            for f in group[:5]:
                loc = f"¶{f.paragraph + 1}" if f.paragraph is not None else "document"
                lines.append(f"    - {loc}: {f.message}")
                fragment = getattr(f, "fragment", "") or getattr(f, "detail", "")
                if fragment:
                    lines.append(f"      > {fragment[:110]}")
                if getattr(f, "suggestion", None):
                    lines.append(f"      Suggested: {f.suggestion[:110]}")
            if len(group) > 5:
                lines.append(f"    - …and {len(group) - 5} more")
            lines.append("")

    return "\n".join(lines) + "\n"
