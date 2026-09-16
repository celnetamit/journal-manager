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
import sys
import threading
import time
import traceback
import uuid
import zipfile

from docx.opc.exceptions import PackageNotFoundError
from typing import Any, Callable, Dict, List, Optional

import config as app_config
import losscheck as _losscheck
import token_census as _token_census
import usage as _usage
import auth
# Only for the progress reports a platform job sends back while it runs. `mng_bridge`
# imports `auth` and `config` and nothing from here, so there is no cycle — and an
# unconfigured bridge simply hands back no reporter.
import mng_bridge
from docxmodel import read_structure
from house_layout import check_all as house_check
from science_format import check_all as science_format_check
from image_check import check_images
from reference_check import check_references, complete_verified_references
from proofread import proofread as run_proofread
from edit_guards import (
    _REF_URL,
    _reference_identity,
    _references_start,
    fix_trailing_citations,
    follow_the_author_on_invisible_twins,
    keep_caption_values,
    keep_closed_compounds,
    keep_every_equation,
    keep_subscript_markers,
    orphaned_formula_queries,
    enforce_abbreviation_first_use,
    preserve_author_hyphenation,
    refuse_invented_expansions,
    restore_front_matter_names,
    restore_protected_text,
    restore_reference_numbering,
    verify_reference_block,
    restore_reference_urls,
    undo_broken_subscripts,
    verify_cell_edits,
)
from science_format import (
    collapse_duplicated_symbols,
    detect_language_variant,
    enforce_all_formula_subscripts,
    enforce_language_variant,
    enforce_science_symbols,
    enforce_unit_case,
)
from editor import (
    _generate_text,
    align_global_citations,
    build_jats_xml,
    build_journal_report,
    build_plagiarism_report,
    collect_table_texts,
    collect_table_texts_for_proofing,
    enforce_author_limit,
    enforce_drop_redundant_paren_citation,
    enforce_element_citation_brackets,
    enforce_keywords_format,
    enforce_reference_year_only,
    enforce_temperature_spacing,
    fetch_crossref_record,
    for_display,
    generate_ai_review,
    generate_cover_letter,
    generate_redline_docx,
    generate_report,
    generate_title_abstract_polish,
    markdown_to_docx,
    plagiarism_scan,
    process_document_async,
    read_docx,
    recommend_journals,
    recurring_changes,
    validate_jats,
    verify_serper_key,
    word_spans,
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


#: What a file says it is, in its first bytes. A `.docx` is a zip whose first two
#: bytes are `PK`; everything else here is a file that was given a `.docx` name.
_SIGNATURES = [
    (b"%PDF", "a PDF"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "an old Word 97–2003 .doc"),
    (b"{\\rtf", "an RTF"),
    (b"<?xml", "an XML file"),
    (b"<html", "an HTML page"),
    (b"<!DOCTYPE", "an HTML page"),
]


def describe_unopenable(path: str) -> str:
    """Why this file could not be opened as a .docx — the actual reason, in words.

    `python-docx` raises one exception, with one wording, for at least six different
    causes. Measured in the running container, `Package not found at '<path>'` is what
    comes back for a file that is not there, for a PDF, for a Word 97 `.doc`, for RTF,
    for HTML and for a truncated zip. We picked one of those causes and told the author
    it as fact — "the file appears to be damaged, open it in Word and use Save As".

    Jobs #76, #77 and #78 are the same person acting on that advice three times in
    twenty minutes. #76 was a PDF (`…Formatted (2).docx.pdf`), and no amount of
    re-saving a PDF in Word produces a `.docx`. Advice that cannot work reads exactly
    like advice that has not been followed.
    """
    if not os.path.exists(path):
        return ("the uploaded file did not arrive on the server. Please upload it "
                "again.")
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError as e:
        return f"the file could not be read on the server ({e})."
    if size == 0:
        return "the uploaded file is empty (0 bytes). Please upload it again."
    for magic, what in _SIGNATURES:
        if head.startswith(magic):
            if magic == b"%PDF":
                # Job #76 was a PDF export of a manuscript that exists as a .docx
                # somewhere. Asking for the original is the short road; converting the
                # PDF is the long one, and it loses the tracked-changes the redline
                # needs anyway.
                return ("this is a PDF, not a Word .docx. Please upload the Word "
                        "original — a PDF cannot carry the tracked changes the "
                        "redline is written in.")
            return (f"this is {what}, not a Word .docx. Open it in Word and use "
                    f"File > Save As with 'Word Document (.docx)', then upload that.")
    if not head.startswith(b"PK"):
        return ("this is not a Word .docx — it does not begin like one. Open it in "
                "Word and use File > Save As with 'Word Document (.docx)'.")
    # It is a zip. Which kind, and is it whole?
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
    except (zipfile.BadZipFile, OSError):
        return ("the file is a damaged Word document — it did not finish "
                "downloading or was truncated. Please upload it again, or open it "
                "in Word and use File > Save As to write a fresh copy.")
    if "word/document.xml" not in names:
        for prefix, what in (("ppt/", "a PowerPoint file"), ("xl/", "an Excel file")):
            if any(n.startswith(prefix) for n in names):
                return (f"this is {what}, not a Word .docx.")
        return "this is an Office file but not a Word document."
    return ("the file is a Word document whose contents could not be read. Open it "
            "in Word and use File > Save As to write a fresh copy, then upload that.")


#: How long a paused job waits with nobody touching it before it decides for itself.
#: Amit, 15 Sep 2026: "30 sec wait krega, jawab na milne par automatic AI decision le
#: lega." Measured from the **last decision**, not from the start — 30 seconds is long
#: enough to answer a paragraph and far too short to review twenty, so a hard deadline
#: would take the panel away from the one person actually using it. Answer anything and
#: the clock restarts; walk away and the job finishes on its own.
REVIEW_IDLE_SECONDS = 30
#: The ceiling on the whole gate, however busy the reviewer is. The worker thread is
#: held for this long and other people's jobs queue behind it, so "as long as you like"
#: is not on offer. Ten minutes is far past any real review of one manuscript.
REVIEW_MAX_SECONDS = 600
#: Paragraph text carried into the question, per paragraph. Same cap as the live feed:
#: this row is read every couple of seconds.
REVIEW_TEXT_LIMIT = 700


def _remote_review(reporter, stage: str, *, force: bool = False, **fields) -> Dict[str, str]:
    """Show the question on the platform, and take whatever has been decided there.

    Every part of this is optional decoration over a pass that is already running, so it
    is swallowed whole: a platform that has gone away during a review must cost the
    manuscript nothing. What it cannot do is invent a decision — a failure here returns
    no answers, and no answers means the change is applied as proposed, which is the
    same thing that happens when nobody is watching.
    """
    if reporter is None:
        return {}
    try:
        reporter.update_ask(**fields)
        reporter.send(0.60, stage, [], force=force)
        return reporter.take_answers()
    except Exception as exc:  # noqa: BLE001
        print(f"[bridge] review report raised, ignored: {exc}", flush=True)
        return {}


def review_gate(job_id, originals, edited, progress=None, *,
                idle_seconds: float = REVIEW_IDLE_SECONDS,
                max_seconds: float = REVIEW_MAX_SECONDS,
                auth_mod=None, sleep=time.sleep,
                clock=time.monotonic, reporter=None) -> tuple:
    """Manual mode: show every proposed change and let a person refuse any of them.

    Returns `(paragraphs, summary)`. A rejected paragraph is put back to exactly what
    the author wrote, which is the only honest meaning of "no" here — the later stages
    then treat it as a paragraph the copyedit did not touch, and the redline shows no
    change for it.

    The waiting rule is the whole design: **the job never blocks on a human.** It waits
    `idle_seconds` from the last decision, and whatever is still undecided when the
    clock runs out is applied as proposed. That is the same outcome as auto mode, so
    the worst case of nobody watching is simply the default behaviour arriving late.

    Deliberately one gate after the copyedit rather than a pause per paragraph: the
    chunks run several at a time in a thread pool, so a pause inside that pool would
    mean four questions at once, each holding a worker. Here the work is done, nothing
    has been written, and the reviewer sees the whole manuscript's changes together —
    which is also the only way to spot the one wrong change among forty right ones.
    """
    auth_mod = auth_mod if auth_mod is not None else auth
    edited = list(edited)
    changed = [i for i, (a, b) in enumerate(zip(originals, edited))
               if (b or "").strip() and (b or "").strip() != (a or "").strip()]
    summary = {"asked": len(changed), "accepted": 0, "rejected": 0,
               "decided_by": "nobody", "waited_seconds": 0.0}
    if not changed:
        return edited, summary

    ask = {
        "kind": "review_changes",
        "idle_seconds": idle_seconds,
        "asked": len(changed),
        "decided": 0,
        "seconds_left": int(idle_seconds),
        "paragraphs": [
            {"index": i, "para": i + 1,
             "spans": word_spans(for_display(originals[i]), for_display(edited[i]),
                                 limit=REVIEW_TEXT_LIMIT)}
            for i in changed
        ],
    }
    auth_mod.ask_job(job_id, ask)
    if reporter is not None:
        # Asked on the platform too, and asked there *first*: the manuscript arrived from
        # it, so that is where the person who can answer is sitting. ce4's own panel stays
        # exactly as it was — the same question, in two places, answered into one row.
        reporter.set_ask(ask)
        _remote_review(reporter, f"Your review — 0 of {len(changed)} decided", force=True)

    started = clock()
    last_activity = started
    answers: Dict[str, str] = {}
    try:
        while True:
            if auth_mod.job_is_cancelled(job_id):
                raise JobCancelled()
            fresh = auth_mod.read_job_answer(job_id)
            # None is "could not read", which is not the same as "taken back" — a
            # transient error must neither reset the clock nor drop a decision.
            if fresh is not None and fresh != answers:
                answers = fresh
                last_activity = clock()
            if len(answers) >= len(changed):
                summary["decided_by"] = "reviewer"
                break
            idle = clock() - last_activity
            if idle >= idle_seconds:
                summary["decided_by"] = "timeout" if not answers else "partly reviewed"
                break
            if clock() - started >= max_seconds:
                summary["decided_by"] = "time limit"
                break
            # Rounded up, never up-a-whole-second: at the moment of asking this said
            # "31s" for a thirty-second wait, and a countdown that starts a second past
            # what was promised is the first thing a reviewer notices.
            left = max(0, -int(-(idle_seconds - idle) // 1))
            stage = (f"Your review — {len(answers)} of {len(changed)} decided · "
                     f"applying the rest in {left}s")
            if progress:
                progress(0.60, stage)
            # Decisions taken on the platform, written into the same row ce4's own panel
            # writes to. They are not merged into `answers` here: the next pass round the
            # loop reads the row, and one source of truth for "what has been decided"
            # is worth the second it costs.
            remote = _remote_review(reporter, stage, decided=len(answers),
                                    seconds_left=left)
            if remote:
                try:
                    auth_mod.answer_job(job_id, remote)
                except Exception as exc:  # noqa: BLE001
                    print(f"[review] could not record a platform decision: {exc}",
                          flush=True)
            sleep(1)
    finally:
        auth_mod.clear_job_ask(job_id)
        if reporter is not None:
            # Taken off the platform's screen whatever happened — including the cancelled
            # path. A question still standing under a job that has moved on is the one
            # way this panel could ask for a decision that can no longer be applied.
            reporter.set_ask(None)
            _remote_review(reporter, "Applying your decisions...", force=True)

    for i in changed:
        if answers.get(str(i)) == "reject":
            edited[i] = originals[i]
            summary["rejected"] += 1
        else:
            summary["accepted"] += 1
    summary["waited_seconds"] = round(clock() - started, 1)
    return edited, summary


def run_pipeline(opts: Dict[str, Any], input_path: str,
                 progress_cb: Optional[Callable[[float, str], None]] = None,
                 job_id: Optional[Any] = None,
                 meter: Optional[_usage.Meter] = None,
                 reporter: Optional[Any] = None) -> Dict[str, Any]:
    """Run the full manuscript pipeline. `opts` carries non-secret options;
    LLM settings (incl. the API key) are resolved server-side, never stored on
    the job. Returns a JSON-serializable result dict.

    `reporter` is the manuscript-ngine progress channel, when this job came from there.
    It is passed rather than rebuilt because manual review needs to *ask on it* and read
    the answer — the progress callback only carries text one way."""
    def progress(frac: float, stage: str, events: Optional[list] = None) -> None:
        if not progress_cb:
            return
        frac = min(max(frac, 0.0), 1.0)
        # `events` is the live feed — what the copyedit just changed. It is passed
        # separately from the stage text because a caller that only wants a bar should
        # not have to parse one, and an older caller should not break for want of it.
        try:
            progress_cb(frac, stage, events)
        except TypeError:
            progress_cb(frac, stage)

    # One meter per job. It rides in the settings dict — which is built fresh here
    # and already threaded through every call — because three jobs can run at once
    # and a module-level counter would blend them into one confident wrong number.
    # The caller may own the meter. A job that fails still spent its tokens — often
    # more than one that succeeds, because a chunk that burns its whole budget
    # reasoning and returns nothing is a common failure — and a meter created here
    # dies with the exception. Then failed jobs record zero, and a user could exhaust
    # the budget on jobs that never count against their quota.
    meter = meter if meter is not None else _usage.Meter()
    llm_settings = _usage.attach(app_config.get_llm_settings(), meter)
    edit_style = opts["edit_style"]
    ref_style = opts["ref_style"]
    lang_type = opts["lang_type"]
    lang_auto = "auto" in (lang_type or "").lower()
    custom_dict = opts.get("custom_dict", "")
    use_crossref = opts.get("use_crossref", True)
    use_crossref_refs = use_crossref
    reorder_citations = opts.get("reorder_citations", True)
    enabled_rule_ids = opts.get("enabled_rule_ids")
    custom_rules = opts.get("custom_rules", "")
    ai_review_enabled = opts.get("ai_review_enabled", True)
    # Each is one model call. Measured: journals 11.6s, cover letter 8.9s, polish
    # 12.4s — together about a third of a minute and ~5% of a job's cost, so these
    # are switches for time and clutter rather than for money. `polish_enabled`
    # defaults to False because its output is a REWRITE that will not match the
    # redline, and an editor comparing the two took it for the copyedit.
    journals_enabled = opts.get("journals_enabled", True)
    cover_letter_enabled = opts.get("cover_letter_enabled", True)
    polish_enabled = opts.get("polish_enabled", False)
    # "auto" unless asked for: a mode that waits for a person has to be chosen by the
    # person who intends to wait. `.get` with a default also keeps every job queued
    # before this existed — and every bridge job — running exactly as it did.
    review_mode = (opts.get("review_mode") or "auto").strip().lower()
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
        # The replacement was meaningful and, for most of these, wrong: see
        # `describe_unopenable`, which asks the file what it is instead.
        raise ValueError(
            f"This file could not be opened: {describe_unopenable(input_path)}"
        ) from open_exc
    paras_count = len(original_paragraphs)

    if lang_auto:
        # The editorial team's rule: follow what the author mostly wrote, counted over
        # the whole manuscript rather than sampled from the abstract — which is the one
        # section most likely to have been rewritten by someone else.
        detected, _counts = detect_language_variant(original_paragraphs)
        if detected:
            lang_type = detected
            warnings.append(
                f"Language was set to follow the manuscript: {detected} "
                f"({_counts['uk']} UK-only, {_counts['us']} US-only spellings found).")
        else:
            # Not enough evidence, or a genuinely mixed manuscript. Enforcing a side on
            # one word's margin would rewrite half the paper on the strength of it.
            lang_type = ""
            warnings.append(
                f"Language variant was left alone: the manuscript does not clearly "
                f"follow one ({_counts['uk']} UK-only, {_counts['us']} US-only "
                f"spellings). Choose US or UK explicitly to enforce one.")

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
        # Print resolution. Arithmetic, not a heuristic: Word stores the picture's
        # pixel size and the frame's size in inches, and their ratio is the effective
        # DPI at the size it will actually be printed.
        import docx as _docx
        layout_findings += check_images(_docx.Document(input_path))
        # What a reference is missing. Reported at info level and never rewritten:
        # a bibliography entry is the author's claim about someone else's work, and a
        # wrong DOI attached to it propagates into Crossref and the citation graph.
        # Crossref supplies a complete entry as a *suggestion* where the title matches
        # confidently, which the editor accepts or ignores.
        from house_layout import find_references as _find_refs
        layout_findings += check_references(
            _find_refs(structure),
            fetch=fetch_crossref_record if use_crossref_refs else None)
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

    def chunk_progress(frac: float, info: Optional[dict] = None) -> None:
        # "Copyediting manuscript…" for the whole 55% of the run told the reader nothing
        # except that it had not finished. The counts come from the chunk pool, so the
        # stage line now says which paragraph the work has reached.
        if info:
            stage = (f"Copyediting — paragraph {info.get('paras_done', 0)} "
                     f"of {info.get('paras_total', 0)}")
            events = info.get("edits") or []
        else:
            stage, events = "Copyediting manuscript...", []
        progress(0.05 + frac * 0.55, stage, events)

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

    # Manual mode: nothing is written yet, so this is the last moment a person can
    # still say no to a change cheaply. Auto is the default and skips this entirely.
    # A job from manuscript-ngine may ask for it too — the question then appears on the
    # manuscript's own screen over there, because that is where the editor is; nobody is
    # sitting in front of ce4 when one lands.
    review_summary = None
    if review_mode == "manual" and job_id is not None:
        progress(0.60, "Waiting for your review of the proposed changes...")
        edited_paragraphs, review_summary = review_gate(
            job_id, original_paragraphs, edited_paragraphs, progress, reporter=reporter)
        if review_summary["rejected"]:
            warnings.append(
                f"{review_summary['rejected']} of {review_summary['asked']} proposed "
                f"changes were rejected in review and those paragraphs are unchanged.")

    # The 11.3%. Table cells are not in `doc.paragraphs`, so nothing has ever
    # copyedited them. Sent through the same pass as the body, then written back by
    # address rather than by position — a table edit must not be able to shift the
    # body list `generate_redline_docx` pairs by index.
    table_edits: dict = {}
    table_queries: list = []
    # Kept beyond the block below so the document-wide repairs can reach table cells
    # too. A rule that fires on the body and not on the tables leaves the document
    # disagreeing with itself, which is worse than not firing at all.
    table_cell_addresses: list = []
    table_cell_originals: list = []
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
                # Position alone is not proof the edit belongs to this cell. On job 46
                # the model returned a table's cells in a different order; every string
                # came back and every one landed in the wrong place.
                edited_cells, alignment_queries = verify_cell_edits(
                    originals, edited_cells)
                table_cell_addresses = list(addresses)
                table_cell_originals = list(originals)
                for addr, before, after in zip(addresses, originals, edited_cells):
                    if after and after.strip() != before.strip():
                        table_edits[addr] = after
                for q in alignment_queries:
                    t, r, c, _ = addresses[q["index"]]
                    table_queries.append(dict(
                        q, index=None,
                        query=f"[Table {t + 1}, row {r + 1}, column {c + 1}] "
                              f"{q['query']}"))
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

    # Filled by every guard from here to the redline. Declared before the first of
    # them rather than at the first assignment, so a guard added earlier in the chain
    # has somewhere to put its queries.
    guard_queries: List[Dict[str, object]] = []

    if reorder_citations:
        # Ask before the re-sort, not only after it.
        #
        # Jobs #71 and #72 each lost a reference and the re-sort's own gate said
        # nothing, correctly: that gate compares what it was handed with what it
        # produced, and by the time it ran the copyedit had already replaced an entry
        # with a copy of another. Both sides were equally wrong, so it passed.
        #
        # The end-of-pipeline guard then caught it and restored the author's list — but
        # by then the in-text citations had been renumbered to match a re-sorted order
        # the restored list does not have, which is why those two reports say the
        # numbering needs a human eye. Restoring here means the re-sort is handed the
        # author's own list and the numbering it produces still matches it.
        #
        # It costs nothing when the copyedit is clean: the guard is idempotent and
        # says nothing on a bibliography that still holds every work it started with.
        edited_paragraphs, _pre_sort_queries = verify_reference_block(
            original_paragraphs, edited_paragraphs)
        guard_queries.extend(_pre_sort_queries)
        progress(0.62, "Aligning citations & sorting bibliography...")
        edited_paragraphs = align_global_citations(
            edited_paragraphs, llm_settings, ref_style, enabled_rule_ids,
            warnings=warnings,
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
    edited_paragraphs = enforce_unit_case(edited_paragraphs)

    # Before `run_proofread`, so the spelling-consistency check sees the text as
    # it will be published. Reporting a clash the enforcement has just resolved
    # would put a finding in the report about text that no longer exists.
    edited_paragraphs = enforce_language_variant(edited_paragraphs, lang_type)
    edited_paragraphs = fix_trailing_citations(edited_paragraphs)

    # Edits the copyedit is not allowed to make, undone against the original — a date
    # line that lost its day and month, an algorithm step that lost its number. Each
    # restoration raises its own query: a guard that quietly overrules the copyedit is
    # the same failure as a copyedit that quietly overrules the author.
    # First of the guards, so everything after it is comparing the author's paragraph
    # with an edit of that paragraph rather than with a sentence the copyedit invented
    # around a missing equation.
    edited_paragraphs, _equation_queries = keep_every_equation(
        original_paragraphs, edited_paragraphs)
    guard_queries += _equation_queries

    edited_paragraphs, _protected_queries = restore_protected_text(
        original_paragraphs, edited_paragraphs)
    guard_queries += _protected_queries
    guard_queries += orphaned_formula_queries(
        original_paragraphs, edited_paragraphs)

    # Runs after the language-variant pass, so a re-spelling cannot re-close a hyphen
    # this just kept.
    edited_paragraphs, _hyphen_queries = preserve_author_hyphenation(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_hyphen_queries)

    # The same question about the other shape a compound comes in. Beside the hyphen
    # guard deliberately: one decides whether the author's hyphen survives, the other
    # whether their closed word does, and an editor reading the queries should find
    # them together.
    edited_paragraphs, _compound_queries = keep_closed_compounds(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_compound_queries)

    # After the science passes, so a subscript this pipeline legitimately converted to
    # `H₂O` is not read as a marker that went missing.
    edited_paragraphs, _marker_queries = keep_subscript_markers(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_marker_queries)

    # A caption's values name the data the figure shows. Everything else in it — the
    # spelling, the capitalisation, the stop at the end — is the copyedit's to fix.
    edited_paragraphs, _caption_queries = keep_caption_values(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_caption_queries)

    # Body and table cells in ONE call, deliberately. The rule renders a superscript
    # only where the document gives evidence for it, and that evidence is document-wide:
    # a table header reading `Damage R2R2` should follow the `R²` the body already uses.
    # Split into two calls, the table would be judged on its own few words and reach a
    # different answer — which is exactly the failure this rule exists to repair.
    _cells_now = [table_edits.get(a, o) for a, o
                  in zip(table_cell_addresses, table_cell_originals)]
    _n_body = len(edited_paragraphs)
    _repaired, _dup_queries = collapse_duplicated_symbols(edited_paragraphs + _cells_now)
    edited_paragraphs = _repaired[:_n_body]
    for _addr, _was, _now in zip(table_cell_addresses, table_cell_originals,
                                 _repaired[_n_body:]):
        if _now != table_edits.get(_addr, _was):
            table_edits[_addr] = _now
    # Full form once with the short form in brackets, the short form after. Only a
    # whole-document pass knows which mention is the first; the 84 separate model
    # calls cannot, and on job 46 the expansion appeared 34 times carrying its
    # abbreviation 4 times. Pairs are learned from the author's own definitions.
    # The authors' names, and the numbers the in-text citations point at. Both were
    # correct on the previous model and wrong on this one, so neither can rest on the
    # model getting it right.
    edited_paragraphs, _name_queries = restore_front_matter_names(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_name_queries)
    # Before the numbering guard, because restoring the author's list makes its
    # numbering question moot — and after it there would be nothing left to check.
    edited_paragraphs, _refblock_queries = verify_reference_block(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_refblock_queries)
    edited_paragraphs, _refnum_queries = restore_reference_numbering(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_refnum_queries)
    # After the block guard: if the whole list was restored there is no lost link left
    # to put back, and this is a no-op rather than a second opinion on the same entry.
    edited_paragraphs, _refurl_queries = restore_reference_urls(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_refurl_queries)

    # An incomplete reference is the one defect an editor cannot fix from the
    # manuscript — the volume number is simply not on the page. Where Crossref has the
    # record for the same work, and the surname, the year and the title all agree, the
    # entry is completed rather than only queried. Every completion is a tracked change
    # quoting the original, so it is accepted or rejected in Word like any other edit.
    if use_crossref_refs:
        try:
            edited_paragraphs, _reffill_queries = complete_verified_references(
                edited_paragraphs, fetch_crossref_record)
            guard_queries.extend(_reffill_queries)
        except Exception as fill_exc:                            # noqa: BLE001
            warnings.append(f"Reference completion was skipped: {skip_reason(fill_exc)}")

    # Before the first-use rule, not after: that rule moves the author's own expansion
    # about, and it should never be handed one the author did not write.
    edited_paragraphs, _invented_queries = refuse_invented_expansions(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_invented_queries)

    edited_paragraphs, _abbr_queries = enforce_abbreviation_first_use(
        original_paragraphs, edited_paragraphs)
    for _q in _abbr_queries:
        guard_queries.append(dict(_q, snippet=edited_paragraphs[_q["index"]][:200]))

    for _q in _dup_queries:
        _i = _q["index"]
        if _i < _n_body:
            guard_queries.append({
                "index": _i, "snippet": edited_paragraphs[_i][:200],
                "query": _q["message"], "suggestion": None,
            })
        else:
            # Table queries carry no body index — `generate_redline_docx` reads
            # `index` as a body paragraph, so anchoring one there points the note at
            # unrelated text in a file that still opens.
            _t, _r, _c, _ = table_cell_addresses[_i - _n_body]
            table_queries.append({
                "index": None,
                "query": f"[Table {_t + 1}, row {_r + 1}, column {_c + 1}] "
                         f"{_q['message']}",
                "suggestion": None,
            })

    # Last, so nothing after it can re-introduce one: a tracked change from `μm` to
    # `µm`, which is the same sign written twice. Body and table cells judged on the
    # author's usage across both, since it is one document and one decision.
    _n_body = len(edited_paragraphs)
    _cells_now = [table_edits.get(a, o) for a, o
                  in zip(table_cell_addresses, table_cell_originals)]
    _twinned, _n_twins = follow_the_author_on_invisible_twins(
        original_paragraphs + list(table_cell_originals),
        edited_paragraphs + _cells_now)
    edited_paragraphs = _twinned[:_n_body]
    for _addr, _was, _now in zip(table_cell_addresses, table_cell_originals,
                                 _twinned[_n_body:]):
        if _now != table_edits.get(_addr, _was):
            table_edits[_addr] = _now
    if _n_twins:
        print(f"invisible twins folded to the author's spelling: {_n_twins}",
              file=sys.stderr)

    # A subscript set in characters that cannot carry a decimal point. Body text only:
    # the two real cases were both in prose, and a table query cannot point at the
    # paragraph this one needs to quote.
    edited_paragraphs, _subscript_queries = undo_broken_subscripts(
        original_paragraphs, edited_paragraphs)
    guard_queries.extend(_subscript_queries)

    # Did the copyedit lose something the author wrote? Only the two checks that
    # survived measurement: a paragraph returned empty, and a negation dropped — the one
    # that can reverse a claim while reading perfectly. A third check on lost numbers was
    # written, measured on 182 real paragraphs, and removed: 26 of its 27 findings were
    # correct edits (citations renumbering, Vancouver conversion, figure numbering), and
    # a guard that fires on correct work hides the one case that is not.
    _loss = _losscheck.check_document(original_paragraphs, edited_paragraphs)
    for _hit in _loss:
        i = _hit["index"]
        # The author's text back — except for single-word spelling corrections, which
        # are kept. A whole-paragraph revert used to throw those away too: job #53's
        # `comparision`/`breaking` were corrected, the paragraph shrank for unrelated
        # reasons, and the misspellings shipped.
        kept = _losscheck.salvage_safe_corrections(
            original_paragraphs[i], edited_paragraphs[i])
        edited_paragraphs[i] = kept
        salvaged = kept != original_paragraphs[i]
        guard_queries.append({
            "index": i,
            "snippet": original_paragraphs[i][:200],
            "query": f"The copyedit was not applied to this paragraph: {_hit['detail']} "
                     + ("Only its spelling corrections were kept; the wording is the "
                        "author's own. Please edit it by hand."
                        if salvaged else
                        "The original was kept. Please edit it by hand."),
            "suggestion": None,
        })

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

    # The same reading applied to what is inside the tables. Job #52 printed
    # `CONCETRATION (M)` as a column heading of Table 2 and every check missed it: the
    # copyeditor is only given cells with three or more words (so it can never be handed
    # a bare number to "correct"), and the proofreader was only ever given body text.
    #
    # Reported, never rewritten — findings come back as table queries, which is why it
    # is safe to look at cells the copyeditor is deliberately kept away from.
    if structure is not None:
        try:
            cells = collect_table_texts_for_proofing(structure)
            if cells:
                cell_findings = run_proofread(
                    [t for _a, t in cells],
                    generate=_generate_text if ai_review_enabled else None,
                    settings=llm_settings, use_llm=ai_review_enabled,
                    lang_type=lang_type)
                for f in cell_findings:
                    if f.paragraph is None or f.paragraph >= len(cells):
                        continue
                    (_t, _r, _c, _p), _text = cells[f.paragraph]
                    table_queries.append({
                        "index": None,
                        "query": (f"[Table {_t + 1}, row {_r + 1}, column {_c + 1}] "
                                  f"{f.message}"),
                        "suggestion": f.suggestion,
                    })
        except Exception as cell_exc:                            # noqa: BLE001
            warnings.append(f"Table proofreading failed: {cell_exc}")

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

    # The bibliography, checked one last time against the author's own.
    #
    # There was already a check here — and job #62 still returned four of the author's
    # works replaced by second copies of four others, with neither this guard nor the
    # re-sort's own census saying anything. Running it once in the middle of the chain
    # means every step after it is unguarded, and the chain is long: renumbering, link
    # restoration, Crossref completion, the abbreviation pass. Rather than keep hunting
    # for which one did it, the question is asked again here, where nothing can follow.
    #
    # It is cheap — a surname-and-year census — and it is idempotent: if the earlier
    # call already restored the list, this one finds nothing to do.
    edited_paragraphs, _final_ref_queries = verify_reference_block(
        original_paragraphs, edited_paragraphs)
    for _q in _final_ref_queries:
        editor_queries = list(editor_queries) + [_q]

    # What the reference guards could actually see, recorded on the job.
    #
    # Three days running the question "did this guard run, and on what" could not be
    # answered from anything the job kept. Jobs #91 and #94 delivered references whose
    # links had been deleted; handed those same files afterwards the guard restores
    # them correctly, so the state it saw during the run was not the state on disk —
    # and there was no record of either. Before that, the census was blind to an
    # unnumbered list (#67, #69, #70) and to an initials-first one (#45, #68) and said
    # nothing in both cases, because a guard that finds no bibliography returns
    # silently and looks exactly like a guard that found nothing wrong.
    _ref_start = _references_start(original_paragraphs)
    _ref_entries = ([] if _ref_start is None
                    else [p for p in original_paragraphs[_ref_start + 1:]
                          if len((p or "").strip()) > 20])
    reference_trace = {
        "bibliography_found": _ref_start is not None,
        "entries": len(_ref_entries),
        "works_readable": sum(
            1 for p in _ref_entries if _reference_identity(p) is not None),
        "links_in_original": sum(1 for p in _ref_entries if _REF_URL.search(p or "")),
        "links_missing_at_redline": 0,
    }

    # And the link, for the same reason and in the same place.
    #
    # Job #91 ¶211 was delivered as `Unesco.org. 2026. Available from: ` with the
    # address gone — the identical symptom job #61 had, six days after it was written
    # down as fixed. The guard for it sits in the middle of the chain, and handed job
    # #91's own paragraphs it restores the link correctly; the list still has the link
    # when that guard has finished. Something between there and here takes it off, and
    # which step that is is not yet known.
    #
    # Asking again where nothing can follow both puts the author's link back and says
    # so: this call is silent unless the link had actually gone by this point, which
    # is the measurement the middle of the chain cannot make.
    edited_paragraphs, _final_url_queries = restore_reference_urls(
        original_paragraphs, edited_paragraphs)
    for _q in _final_url_queries:
        editor_queries = list(editor_queries) + [_q]
    reference_trace["links_missing_at_redline"] = len(_final_url_queries)

    # And the entry number, last of the three and for exactly the same reason. The
    # middle-of-chain call runs before Crossref completion rewrites an entry, and job
    # #104 delivered 12 of 21 entries unnumbered — every one of them an entry Crossref
    # had filled out. Silent on a list that still has its numbers.
    edited_paragraphs, _final_num_queries = restore_reference_numbering(
        original_paragraphs, edited_paragraphs)
    for _q in _final_num_queries:
        editor_queries = list(editor_queries) + [_q]
    if _final_url_queries:
        print(f"[job {job_id}] a reference link was missing at the redline and was "
              f"put back ({len(_final_url_queries)}) — the middle-of-chain guard had "
              f"already restored it, so a later step removes it", flush=True)

    # The net underneath every guard above, and the last thing to look: which technical
    # tokens the author wrote are not in what we are about to hand back. It knows
    # nothing about any particular failure, which is the point — every guard in
    # `edit_guards` was written after a person found the defect first.
    #
    # Measured over all 88 redlines produced up to 16 Sep: 20 findings in 6 files, and
    # every one of them the `G_IC` -> `GIC` loss the quality team reported. The classes
    # that made the first version half noise — unit spacing, a reference volume read as
    # amperes, an underscore inside an ordinary word, a DOI suffix read as a salt — are
    # each normalised away in `token_census`, with the case that taught it written down.
    try:
        for _q in _token_census.missing_tokens(original_paragraphs, edited_paragraphs):
            editor_queries = list(editor_queries) + [_q]
    except Exception as _census_exc:                             # noqa: BLE001
        warnings.append(f"The technical-token check was skipped: "
                        f"{skip_reason(_census_exc)}")

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

    # The same manuscript and the same tracked changes, with only the questions the
    # author is the one to answer — and every insertion highlighted, so the changes
    # are visible whether or not they know where Word keeps the review pane.
    #
    # The quality team's own request, 16 Sep: they can read a redline carrying every
    # guard note and every house-style point; an author opening the same file cannot.
    # The decision stays theirs either way: a tracked change is accepted or rejected
    # in Word, and nothing here changes that.
    author_redline_path = out_dir / f"user_{user_id}_{ts}_author.docx"
    try:
        generate_redline_docx(
            input_path, edited_paragraphs, str(author_redline_path),
            queries=editor_queries, table_edits=table_edits, audience="author",
        )
    except Exception as _author_exc:                             # noqa: BLE001
        author_redline_path = ""
        warnings.append(f"The author's copy could not be written: "
                        f"{skip_reason(_author_exc)}")

    progress(0.74, "Generating editorial report...")
    report = generate_report(
        edit_style, ref_style, lang_type, use_crossref, custom_dict,
        enabled_rule_ids, custom_rules, queries=editor_queries, warnings=warnings,
        plagiarism=plagiarism,
    )
    report += _house_style_section(layout_findings, proof_findings)

    proxy_abstract = " ".join(original_paragraphs[:15])[:1500]
    recommended = []
    journal_report_path = ""
    if journals_enabled:
        progress(0.78, "Recommending journals...")
        recommended = recommend_journals(proxy_abstract, llm_settings, warnings=warnings)
        journal_report_path = out_dir / f"user_{user_id}_{ts}_journals.docx"
        markdown_to_docx(build_journal_report(recommended), str(journal_report_path))

    review_report_path = out_dir / f"user_{user_id}_{ts}_review.docx"
    markdown_to_docx(report, str(review_report_path))

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

    best_journal = recommended[0]["name"] if recommended else "the journal"
    cover_letter = ""
    if cover_letter_enabled:
        progress(0.92, "Generating cover letter...")
        cover_letter = generate_cover_letter(proxy_abstract, best_journal, llm_settings)

    polished_titles = ""
    if polish_enabled:
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
        # What the job actually spent. `cost_usd` is None when the provider did not
        # report one; that must render as "not reported", never as zero.
        "usage": meter.snapshot(),
        "redline_path": str(redline_path),
        "author_redline_path": str(author_redline_path),
        "journal_report_path": str(journal_report_path),
        "review_report_path": str(review_report_path),
        "ai_review_path": str(ai_review_path) if ai_review_path else "",
        "jats_path": str(jats_path),
        "report_md": report,
        # The same house-style and proofreading findings the report renders, kept in
        # their own shape as well. A consumer that wants to show them — the editorial
        # platform lists them on the manuscript — should not have to parse prose back
        # into data that existed as data one function earlier.
        "findings": _findings_payload(layout_findings, proof_findings),
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
        # The same change made over and over, counted once. A manuscript that writes
        # "Fig." forty times has one habit, not forty problems, and a reviewer asked to
        # approve it forty times stops reading by the sixth.
        "patterns": recurring_changes(original_paragraphs, edited_paragraphs),
        "duration": round(duration, 1),
        # Not for the editor — for whoever has to ask tomorrow what the guards saw.
        "reference_trace": reference_trace,
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
        # Present only on a manual run. Kept in the result because "who decided this"
        # is part of the record of the job, not decoration: a manuscript where four
        # changes were refused by a person reads differently from one where the timer
        # ran out.
        "review": review_summary,
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

    # Only for a job that came from manuscript-ngine, and only while it runs: the
    # platform's screen shows the same work this app's live feed shows. None of it can
    # fail the job — see `ProgressReporter`.
    reporter = None
    try:
        reporter = mng_bridge.reporter_for(opts)
    except Exception as exc:  # noqa: BLE001
        print(f"[bridge] no progress reporter for job {job_id}: {exc}", flush=True)

    def cb(frac: float, stage: str, events=None) -> None:
        # Cooperative cancellation: bail before doing more LLM work if the job
        # was cancelled out from under us.
        if auth.job_is_cancelled(job_id):
            raise JobCancelled()
        auth.update_job_progress(job_id, frac, stage)
        # The live feed is written separately from the bar so that a failure to record
        # what changed can never fail the job that changed it.
        if events:
            auth.append_job_events(job_id, events)
        if reporter is not None:
            try:
                reporter.send(frac, stage, events)
            except Exception as exc:  # noqa: BLE001
                print(f"[bridge] progress report raised, ignored: {exc}", flush=True)

    meter = _usage.Meter()
    failed = False
    try:
        result = run_pipeline(opts, job["input_path"], cb, job_id=job_id, meter=meter,
                              reporter=reporter)
        auth.complete_job(job_id, json.dumps(result))
    except JobCancelled:
        print(f"[worker] job {job_id} cancelled; stopping work")
    except Exception as exc:
        failed = True
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
        # Recorded on every path, including cancellation and failure. Whatever the
        # provider was asked to do, it was paid for.
        try:
            auth.record_job_usage(job_id, meter.snapshot())
        except Exception:
            traceback.print_exc()
        # The uploaded input file is no longer needed once the job is done — but a job
        # that FAILED is not done with, and this deleted the one thing anybody could
        # look at. Jobs #76, #77 and #78 all failed on "could not be opened" and by the
        # time the question was asked there was nothing left to open; the cause had to
        # be inferred from a filename. A failed job keeps its input, and the retention
        # sweep clears it with everything else.
        path = job.get("input_path")
        try:
            if failed:
                print(f"[job {job_id}] failed — input kept at {path}", flush=True)
            elif path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


#: How often a worker looks for jobs whose process died. Cheap: one indexed query.
STALL_SWEEP_SECONDS = 120


def _worker_loop() -> None:
    last_sweep = 0.0
    while True:
        try:
            # Startup re-queueing is not enough on its own. A rolling deploy runs both
            # containers at once for a few seconds, so a job can be claimed *after* the
            # new process has already swept the table — and then be killed with the old
            # one. It stays `running` with nobody working on it, which reads as a busy
            # job for ever. Any worker may sweep; the re-queue is guarded on the status
            # it expects, so two of them racing is harmless.
            if time.monotonic() - last_sweep > STALL_SWEEP_SECONDS:
                last_sweep = time.monotonic()
                stalled = auth.requeue_stalled_jobs()
                if stalled:
                    print(f"[worker] re-queued stalled job(s): {stalled}", flush=True)

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


def _findings_payload(layout_findings, proof_findings) -> Dict[str, Any]:
    """House-style and proofreading findings as data, not prose.

    Paragraph numbers are made 1-based here for the same reason `Finding.__str__` does
    it: every place a person reads one is 1-based, and a number that means ¶142 in one
    view and ¶143 in another reads as a tool that cannot count.
    """
    def one(f) -> Dict[str, Any]:
        return {
            "rule": getattr(f, "rule", ""),
            "severity": getattr(f, "severity", "info"),
            "paragraph": (f.paragraph + 1) if getattr(f, "paragraph", None) is not None
                         else None,
            "message": getattr(f, "message", ""),
            "detail": getattr(f, "detail", "") or getattr(f, "fragment", ""),
            "suggestion": getattr(f, "suggestion", None),
        }

    return {
        "layout": [one(f) for f in (layout_findings or [])],
        "proofreading": [one(f) for f in (proof_findings or [])],
    }


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
