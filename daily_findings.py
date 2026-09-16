"""The day's copy editing, counted — so a change in what the tool catches is visible.

Amit, 17 Sep 2026: *"Abb sari findings ko tum future ke liye record kar lo aur daily
11pm ka ek trigger bana lo ki roj ka findings and summary auto records and update
hote rahe."*

Every job already knows what it found; nothing was keeping it. This reads the day's
jobs, counts what each guard caught, and appends one record per day to a file that
lives on the data volume rather than in a container.

What the record is *for* is the second derivative, not the total: a guard that stops
firing has usually stopped working, and a defect class that suddenly appears is a new
manuscript habit or a new model. Both are invisible in any single job.
"""

from __future__ import annotations

import collections
import datetime
import json
import os
from typing import Any, Dict, List, Optional

import config as app_config

#: One JSON object per line, on the data volume. A container is replaced on every
#: deploy; this file is not.
def record_path() -> str:
    return os.path.join(str(app_config.data_dir()), "daily-findings.jsonl")


def _jobs_on(day: datetime.date, fetch_jobs) -> List[Dict[str, Any]]:
    out = []
    for job in fetch_jobs(200):
        created = job.get("created_at")
        if isinstance(created, str):
            created = created[:10]
        elif created is not None:
            created = created.date().isoformat()
        if created == day.isoformat():
            out.append(job)
    return out


def summarise(day: datetime.date, fetch_jobs) -> Dict[str, Any]:
    """What the day's jobs found, by guard and by defect class."""
    jobs = _jobs_on(day, fetch_jobs)
    guards: collections.Counter = collections.Counter()
    proof: collections.Counter = collections.Counter()
    layout: collections.Counter = collections.Counter()
    for_author = 0
    failed = 0
    ids: List[Any] = []

    for job in jobs:
        ids.append(job.get("id"))
        if job.get("status") == "error":
            failed += 1
            continue
        try:
            result = json.loads(job.get("result_json") or "{}")
        except ValueError:
            continue
        for finding in result.get("guard_findings") or []:
            guards[finding.get("guard") or "unknown"] += 1
            if finding.get("audience") == "author":
                for_author += 1
        for finding in (result.get("findings") or {}).get("proofreading") or []:
            proof[finding.get("rule") or "unknown"] += 1
        for finding in (result.get("findings") or {}).get("layout") or []:
            layout[finding.get("rule") or "unknown"] += 1

    return {
        "date": day.isoformat(),
        "jobs": len(jobs),
        "job_ids": ids,
        "failed": failed,
        "guard_findings": dict(guards.most_common()),
        "for_the_author": for_author,
        "proofreading": dict(proof.most_common(12)),
        "layout": dict(layout.most_common(12)),
    }


def append(summary: Dict[str, Any], path: Optional[str] = None) -> str:
    """Write the day's record, replacing any earlier record for the same date.

    Re-runnable on purpose: a day can be summarised twice — at 23:00 and again by
    hand — without the file growing two different answers for it.
    """
    target = path or record_path()
    kept = []
    if os.path.exists(target):
        with open(target, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("date") != summary.get("date"):
                    kept.append(row)
    kept.append(summary)
    kept.sort(key=lambda r: r.get("date") or "")
    with open(target, "w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def history(days: int = 14, path: Optional[str] = None) -> List[Dict[str, Any]]:
    target = path or record_path()
    if not os.path.exists(target):
        return []
    rows = []
    with open(target, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows[-days:]


def in_words(summary: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> str:
    """The day in a few lines, for somebody reading it on a phone."""
    guards = summary.get("guard_findings") or {}
    lines = [f"ce4 — {summary['date']}",
             f"{summary['jobs']} manuscripts"
             + (f", {summary['failed']} failed" if summary.get("failed") else "")]
    if guards:
        top = ", ".join(f"{name.replace('_', ' ')} {n}"
                        for name, n in list(guards.items())[:5])
        lines.append(f"guards caught {sum(guards.values())}: {top}")
    else:
        lines.append("no guard fired")
    lines.append(f"{summary.get('for_the_author', 0)} queries for the author")

    if previous:
        was = set(previous.get("guard_findings") or {})
        now = set(guards)
        new = sorted(now - was)
        if new:
            lines.append("new today: " + ", ".join(n.replace('_', ' ') for n in new))
    return "\n".join(lines)
