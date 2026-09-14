#!/usr/bin/env python3
"""Rebuild `journals.json` from manuscript-ngine, which is where the scope actually lives.

    refresh_journals.py [--out journals.json] [--base https://manuscript-engine.celnet.in]

Until now this file held a name, a publisher, an impact factor and a `topics` list — and
232 of the 274 journals had exactly *one* topic. Across the whole portfolio there were 25
distinct topic-sets, so 28 computer journals were identical to the recommender and the only
thing separating them was the journal's name. Meanwhile manuscript-ngine holds the focus and
scope the editorial team writes and publishes on the website: about four thousand words per
journal, plus the journal's own subject areas.

So this is not new data. It is the same portfolio, read from the system that owns it.

**The public endpoints, deliberately.** `/api/v1/public/journals/` and
`/api/v1/public/journals/<code>/` need no key and expose exactly what an author sees on the
journal's page — which is the right input for "where should this paper go". No credential
lives in ce4 for this.

**The impact factor is carried over, not fetched.** manuscript-ngine does not hold one. The
numbers in the existing file came from somewhere else and ce4 prints them in author-facing
reports, so they are preserved as they are and flagged here rather than quietly dropped or,
worse, invented.

Run it whenever the team rewrites a scope, then rebuild the embeddings:

    python refresh_journals.py && python embed_journals.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://manuscript-engine.celnet.in"
TIMEOUT = 30

#: Journals that exist only to hold something inside the platform, not titles anybody
#: submits to.
SKIP_CODES = {"smoke", "unassigned"}


#: Cloudflare sits in front of manuscript-ngine and refuses the default `Python-urllib`
#: agent with a 403. Identifying the caller is the right thing to do anyway — a named agent
#: in somebody's access log is answerable; an anonymous one is a scraper.
USER_AGENT = "ce4-journal-refresh/1.0 (+https://ce4.celnet.in)"


def _key(name: str) -> str:
    """A name with its whitespace normalised, for matching across exports."""
    return re.sub(r"\s+", " ", name or "").strip().lower()


def fetch(url: str, attempts: int = 4) -> dict:
    """One GET, with a backoff on 429.

    The platform throttles public reads, and the first run of this script lost ten
    journals to it — they were reported on the console and then simply not written, which
    is the worst shape a failure can take: the file looked complete at 264.
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == attempts:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="journals.json")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()

    try:
        previous = {_key(j["name"]): j for j in json.load(open(args.out))}
    except (OSError, ValueError):
        previous = {}
        print(f"note: no readable {args.out} to carry impact factors over from")

    listing = fetch(f"{args.base}/api/v1/public/journals/")["journals"]
    print(f"{len(listing)} journals listed")

    out, thin, carried_over, lost = [], [], [], []
    for i, stub in enumerate(listing, start=1):
        code = (stub.get("code") or "").strip()
        if code.lower() in SKIP_CODES:
            continue
        try:
            detail = fetch(f"{args.base}/api/v1/public/journals/{code}/")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            # Carry the previous row rather than dropping the journal. A recommender that
            # silently stops knowing about ten titles is worse than one holding a stale
            # scope for them, and the count at the end would not have shown it.
            kept = previous.get(stub.get("title") or "")
            reason = getattr(exc, "code", exc)
            if kept:
                out.append(kept)
                carried_over.append(code)
                print(f"  {code}: {reason} — kept the previous entry")
            else:
                lost.append(code)
                print(f"  {code}: {reason} — NO previous entry, journal missing")
            continue

        areas = [a for a in (detail.get("subject_areas") or []) if isinstance(a, str)]
        scope = (detail.get("scope") or "").strip()
        name = detail.get("title") or stub.get("title") or code

        # A journal with no scope and no areas would embed as its own title, which is the
        # problem this script exists to remove. Name them rather than pretend.
        if len(scope) < 200 and len(areas) < 3:
            thin.append(code)

        row = {
            "name": name,
            "code": code,
            "topics": [t for t in [stub.get("domain") or ""] if t],
            "subject_areas": areas,
            "scope": scope,
            "publisher": detail.get("publisher_name") or "STM Journals",
        }
        # Matched on a whitespace-normalised name: one journal differed only by a double
        # space and silently lost its impact factor on the first run.
        old = previous.get(_key(name))
        if old and old.get("impact_factor") is not None:
            row["impact_factor"] = old["impact_factor"]
        out.append(row)

        if i % 40 == 0:
            print(f"  {i}/{len(listing)}")
        time.sleep(0.25)          # under the public read throttle, with room to spare

    with open(args.out, "w") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1)

    scope_chars = sum(len(j["scope"]) for j in out)
    areas_total = sum(len(j["subject_areas"]) for j in out)
    print(f"\nwrote {args.out}: {len(out)} journals")
    print(f"  scope text  : {scope_chars:,} characters ({scope_chars // max(1, len(out)):,} each)")
    print(f"  subject areas: {areas_total:,} ({areas_total / max(1, len(out)):.1f} each)")
    carried = sum(1 for j in out if "impact_factor" in j)
    print(f"  impact factors carried over: {carried}")
    if thin:
        print(f"  thin on both scope and areas ({len(thin)}): {', '.join(thin)}")
    if carried_over:
        print(f"  kept from the previous file ({len(carried_over)}): {', '.join(carried_over)}")
    if lost:
        print(f"  MISSING ({len(lost)}): {', '.join(lost)}")
    expected = len([s for s in listing if (s.get("code") or "").lower() not in SKIP_CODES])
    if len(out) != expected:
        print(f"\n  REFUSING to call this complete: {len(out)} written, {expected} expected")
        return 1
    print("\nNow rebuild the embeddings:  python embed_journals.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
