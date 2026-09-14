"""Collecting copy editing work from manuscript-ngine, and sending it back.

The editorial platform (`manuscript-engine.celnet.in`) holds the manuscripts; this holds
the engine that reads them. Rather than keep two sets of copy editing rules in step —
which means fixing every future bug twice — a manuscript is handed here, run through the
ordinary pipeline, and the marked-up file goes back as a file on that manuscript.

**This side pulls.** ce4 opens no new endpoint for the platform to call: the bridge is a
client, exactly like the worker is a client of its own queue. That keeps the public
surface of this service unchanged, and it means an outage here looks like a queue that
stops draining rather than like requests failing on the other side.

**The pipeline is untouched.** A collected manuscript becomes an ordinary row in `jobs`
and is claimed by the same `claim_next_job()` as everything else, so it gets the same
guards, the same redline, the same live feed. All this module adds is the two ends: put
the work in, take the result out.

**What has been returned is recorded, not inferred.** `bridge_jobs` says which local job
answers which remote one and when the answer was sent. Deciding that from the job's own
state instead — "it is done, so presumably it went back" — is the mistake that hides a
returned file nobody received.

Unconfigured, this does nothing at all: no `MNG_BASE_URL` or no `MNG_BRIDGE_SECRET` and
the thread never starts. A bridge that is not set up should be absent, not noisy.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import requests

import auth
import config

#: How long to wait between asking the platform whether anything is waiting. The work
#: itself takes minutes, so polling faster buys nothing and only makes the log noisier.
POLL_SECONDS = int(os.getenv("MNG_POLL_SECONDS", "60") or 60)
HTTP_TIMEOUT = 120


#: Settings come from the environment first and from a file on the data volume second.
#:
#: The file exists because this service's environment is owned by the deployment platform
#: and cannot be changed from here, while the volume survives a deploy. It is deliberately
#: *not* `config.json`: that one is rendered on an admin screen, and a shared secret has
#: no business being somewhere it can be displayed.
SETTINGS_FILE = "mng_bridge.json"


def _from_file(key: str) -> str:
    try:
        path = config.data_dir() / SETTINGS_FILE
        if not path.exists():
            return ""
        with path.open() as fh:
            return str(json.load(fh).get(key, "") or "")
    except (OSError, ValueError):
        return ""


def base_url() -> str:
    value = os.getenv("MNG_BASE_URL", "") or _from_file("base_url")
    return value.rstrip("/")


def secret() -> str:
    return os.getenv("MNG_BRIDGE_SECRET", "") or _from_file("secret")


def configured() -> bool:
    return bool(base_url() and secret())


# ----------------------------------------------------------------------------------
# Talking to the platform
# ----------------------------------------------------------------------------------


def _signature(method: str, path: str, timestamp: str, body: bytes) -> str:
    """Must match `apps/copyedit/bridge.py` on the platform, byte for byte.

    Method and path are inside the signature so a captured request cannot be replayed
    against a different route, and the body hash is inside it so what was signed is what
    arrives.
    """
    digest = hashlib.sha256(body or b"").hexdigest()
    message = f"{method.upper()}\n{path}\n{timestamp}\n{digest}".encode()
    return hmac.new(secret().encode(), message, hashlib.sha256).hexdigest()


def _call(method: str, path: str, *, body: bytes = b"", files=None, data=None,
          stream: bool = False) -> requests.Response:
    stamp = str(int(time.time()))
    headers = {"X-CE4-Timestamp": stamp,
               "X-CE4-Signature": _signature(method, path, stamp, body)}
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": HTTP_TIMEOUT, "stream": stream}
    if files is not None:
        kwargs["files"] = files
        kwargs["data"] = data or {}
    elif body:
        headers["Content-Type"] = "application/json"
        kwargs["data"] = body
    return requests.request(method, base_url() + path, **kwargs)


def _multipart_body(files: dict, data: dict) -> bytes:
    """The encoded body, so the signature covers what is actually sent.

    `requests` builds the multipart body itself, and signing anything other than those
    exact bytes produces a signature the platform correctly rejects. So the body is built
    once here, signed, and handed over already encoded.
    """
    req = requests.Request("POST", "http://x/", files=files, data=data).prepare()
    return req.body if isinstance(req.body, bytes) else (req.body or "").encode(), \
        req.headers.get("Content-Type", "")


# ----------------------------------------------------------------------------------
# Bringing work in
# ----------------------------------------------------------------------------------


def pending() -> list:
    response = _call("GET", "/api/v1/copyedit/bridge/pending/")
    if response.status_code == 503:
        raise BridgeNotReady(response.text[:200])
    response.raise_for_status()
    return response.json().get("jobs", [])


def collect_one(remote: dict) -> Optional[int]:
    """Claim one remote job, fetch its file, and queue it here.

    Claim first, download second. A worker that dies between the two leaves a job the
    platform can see is claimed and never returned, which is a state somebody can act on;
    downloading first and dying would leave the platform believing nothing had happened
    while a file sat here.
    """
    remote_id = remote["job_id"]
    claim = _call("POST", f"/api/v1/copyedit/bridge/claim/{remote_id}/")
    if claim.status_code != 200:
        print(f"[bridge] could not claim {remote_id}: "
              f"{claim.status_code} {claim.text[:120]}", flush=True)
        return None
    claimed = claim.json()

    got = _call("GET", f"/api/v1/copyedit/bridge/file/{remote_id}/", stream=True)
    if got.status_code != 200:
        _report_failure(remote_id, f"could not download the manuscript: {got.status_code}")
        return None

    inbox = config.data_dir() / "mng-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    name = claimed.get("filename") or "manuscript.docx"
    path = inbox / f"{remote_id}-{Path(name).name}"
    with open(path, "wb") as fh:
        for chunk in got.iter_content(65536):
            fh.write(chunk)

    if path.stat().st_size == 0:
        _report_failure(remote_id, "the manuscript downloaded as an empty file")
        path.unlink(missing_ok=True)
        return None

    options = _options_for(claimed, remote_id, name)
    job_id = auth.create_job(user_id=None, filename=name, input_path=str(path),
                             options_json=json.dumps(options))
    _record(job_id, remote_id)
    print(f"[bridge] collected {claimed.get('manuscript_number') or remote_id} "
          f"as job {job_id}", flush=True)
    return job_id


#: What the platform asked for is a copy edit, so that is what runs.
#:
#: `run_pipeline` insists on `edit_style`, `ref_style` and `lang_type` and has sensible
#: defaults for the rest — but three of those defaults are wrong for a manuscript that
#: already has a home. Journal recommendations and a cover letter are for an author
#: deciding where to submit; this one has been submitted, and both would come back as
#: files the editor did not ask for. The AI reviewer is switched off for the same reason:
#: the platform runs its own peer review, and a second opinion arriving inside a
#: copy-editing return is a report nobody commissioned.
def _options_for(claimed: dict, remote_id: str, name: str = "manuscript.docx") -> dict:
    variant = (claimed.get("variant") or "british").lower()
    return {
        # No ce4 account is behind this: the platform is the publisher's own system,
        # not a tenant. `token_cap_for(None)` is already "no limit", which is the right
        # answer — the house's own manuscripts must not be stopped by a per-user quota.
        "user_id": None,
        "filename": name,
        "edit_style": "Chicago Manual of Style (CMOS)",
        # The platform's own reference checker reads against Vancouver and tells authors
        # so on the public page. The two must not disagree.
        "ref_style": "Vancouver",
        "lang_type": "US English" if variant == "american" else "UK English",
        "journals_enabled": False,
        "cover_letter_enabled": False,
        "ai_review_enabled": False,
        # Kept so the finished job can say where it came from without another lookup.
        "source": "manuscript-ngine",
        "mng_job_id": remote_id,
        # Manual mode, when the editor asked for it on the platform. The review panel
        # then appears there rather than here — see `ProgressReporter.set_ask`. Anything
        # this side does not recognise is auto, which is the mode that needs nobody.
        "review_mode": ("manual" if str(claimed.get("review_mode") or "") == "manual"
                        else "auto"),
        "manuscript_number": claimed.get("manuscript_number", ""),
        "journal_code": claimed.get("journal_code", ""),
        "variant": variant,
    }


# ----------------------------------------------------------------------------------
# Saying what is happening, while it happens
# ----------------------------------------------------------------------------------
#
# A copy edit takes minutes, and for all of them the platform's screen said "With ce4"
# and nothing else — while this side knew the paragraph number, the change being made and
# the patterns building up. The same signed channel carries it back, so the editor
# watches the work on the manuscript they are already looking at.
#
# None of it is required for the copy edit. If the platform is unreachable, or refuses
# the report, the pass runs to the end and the file still goes back — which is why every
# failure here is logged and swallowed. A progress bar must never be able to fail a job.

#: The floor between two reports for the same job. The chunk pool can finish several
#: paragraphs a second on a short manuscript; the screen polls far slower than that, so
#: anything more often is writes nobody reads.
PROGRESS_EVERY_SECONDS = 3.0
#: Short on purpose. This call sits in the worker thread between two chunks of real work,
#: so a platform that has stopped answering must cost seconds, not the two minutes the
#: file transfers are allowed.
PROGRESS_TIMEOUT = 8
#: The floor while a question is on the platform's screen. A countdown that jumps three
#: seconds at a time under a browser that polls every two is a clock nobody can trust, and
#: the answer coming back rides on the same call — so while somebody is being asked, this
#: side speaks more often. It is bounded: the question lasts as long as the review does.
PROGRESS_WHILE_ASKING = 1.5


class ProgressReporter:
    """Per-job throttle and accumulator for what ce4 is doing.

    It carries the patterns as well as the last few edits, because the patterns are the
    part that is worth interrupting for: "this manuscript writes Fig. everywhere" is
    knowable at paragraph ten and useful there, not only in the report at the end. They
    are counted from the diff spans the feed already produced, through the *same*
    grouping the finished report uses — one implementation, so the running number and the
    final number cannot disagree.
    """

    def __init__(self, remote_id: str, clock=time.monotonic) -> None:
        self.remote_id = str(remote_id)
        self.clock = clock
        # None, not 0.0: "never reported" has to be a state of its own, or the first
        # report of a job is held back for the throttle interval — and the first one is
        # the one that turns "With ce4" into a moving bar.
        self.last_sent = None
        self.observations: list = []
        self.recent: list = []
        self.failures = 0
        #: The question currently on the platform's screen, or None. Attached to every
        #: report while it is set, because the report is the only channel there is.
        self.ask: Optional[Dict[str, Any]] = None
        #: What came back on the last accepted report. Read and cleared by the gate.
        self.answers: Dict[str, str] = {}
        self._ask_delivered = False

    def note(self, events) -> None:
        from editor import pairs_from_spans

        for event in events or []:
            para = event.get("para") or 0
            for old, new in pairs_from_spans(event.get("spans")):
                self.observations.append((para, old, new))
        if events:
            # Held, not just forwarded. Only the copyediting stage produces edits; the
            # stages after it (proofreading, references, the report) produce none, and a
            # panel that emptied itself at 60% looked like a job that had stopped doing
            # anything. The last few changes stay on screen until the file comes back.
            self.recent = (self.recent + list(events))[-6:]

    # ------------------------------------------------------------------
    # Asking, and being answered
    # ------------------------------------------------------------------
    #
    # Manual mode pauses the pass and asks whether each proposed change should stand.
    # ce4's own screen can show that panel, but nobody is sitting in front of ce4 when a
    # manuscript arrives over the bridge — the editor is on the platform, looking at the
    # manuscript. So the question travels out on the progress report and the decisions
    # come back in its response: no new endpoint on either side, and no polling channel
    # that could be up while the reporting one is down.

    def set_ask(self, payload: Optional[Dict[str, Any]]) -> None:
        """Put a question on the platform's screen, or take it away."""
        self.ask = dict(payload) if payload else None
        self._ask_delivered = False

    def update_ask(self, **fields: Any) -> None:
        """Change the countdown and the tally without resending the paragraphs."""
        if self.ask is not None:
            self.ask.update(fields)

    def take_answers(self) -> Dict[str, str]:
        """The decisions that arrived since this was last called."""
        answers, self.answers = self.answers, {}
        return answers

    def _ask_for_the_wire(self) -> Optional[Dict[str, Any]]:
        """The question as it should be sent now.

        The paragraphs go once and are then left out — they are the bulk of it, and a
        forty-paragraph review would otherwise put its text on the wire every second and a
        half for ten minutes. They keep going until a report is actually accepted: a
        question the platform never received is not a question.
        """
        if self.ask is None:
            return None
        if self._ask_delivered:
            return {k: v for k, v in self.ask.items() if k != "paragraphs"}
        return dict(self.ask)

    def due(self) -> bool:
        every = PROGRESS_WHILE_ASKING if self.ask is not None else PROGRESS_EVERY_SECONDS
        return self.last_sent is None or (self.clock() - self.last_sent) >= every

    def send(self, progress: float, stage: str, events, force: bool = False) -> bool:
        from editor import group_changes

        self.note(events)
        if not force and not self.due():
            return False
        self.last_sent = self.clock()
        payload = {
            "progress": progress,
            "stage": stage,
            "events": self.recent,
            "patterns": group_changes(self.observations),
        }
        ask = self._ask_for_the_wire()
        if ask is not None:
            payload["ask"] = ask
        body = json.dumps(payload).encode()
        path = f"/api/v1/copyedit/bridge/progress/{self.remote_id}/"
        try:
            stamp = str(int(time.time()))
            response = requests.post(
                base_url() + path, data=body, timeout=PROGRESS_TIMEOUT,
                headers={"Content-Type": "application/json",
                         "X-CE4-Timestamp": stamp,
                         "X-CE4-Signature": _signature("POST", path, stamp, body)})
        except requests.RequestException as exc:
            self._failed(f"{type(exc).__name__}: {exc}")
            self._ask_delivered = False
            return False
        if response.status_code != 200:
            self._failed(f"{response.status_code} {response.text[:120]}")
            self._ask_delivered = False
            return False
        self.failures = 0
        self._ask_delivered = self.ask is not None
        self._read_answers(response)
        return True

    def _read_answers(self, response) -> None:
        """Decisions the editor has taken, out of the response to our own report.

        Defensive to the point of dullness on purpose: this is parsed inside the worker
        thread between two chunks of real work, and a platform that answers with a login
        page must cost nothing at all. Only the two words the gate acts on are kept —
        anything else is somebody else's idea of a decision.
        """
        try:
            answers = (response.json() or {}).get("answers")
        except ValueError:
            return
        if not isinstance(answers, dict):
            return
        for key, value in answers.items():
            if str(value) in ("keep", "reject"):
                self.answers[str(key)] = str(value)

    def _failed(self, why: str) -> None:
        # Said once per job, not once per tick: a platform that is down would otherwise
        # write a line every three seconds for the length of the manuscript, and bury the
        # log line that matters.
        self.failures += 1
        if self.failures == 1:
            print(f"[bridge] progress for {self.remote_id} not accepted ({why}); "
                  f"the pass continues", flush=True)


def reporter_for(options: Dict[str, Any]) -> Optional[ProgressReporter]:
    """A reporter for a job that came from the platform, or None for a local upload."""
    remote_id = (options or {}).get("mng_job_id")
    if not remote_id or not configured():
        return None
    return ProgressReporter(str(remote_id))


# ----------------------------------------------------------------------------------
# Sending it back
# ----------------------------------------------------------------------------------


def return_one(local_job: dict, remote_id: str) -> bool:
    """Post the redline back, or say why there is not one."""
    status = local_job.get("status")
    if status == "error":
        return _report_failure(remote_id,
                               local_job.get("error_message") or "the pass failed here")
    if status == "cancelled":
        return _report_failure(remote_id, "the pass was cancelled here")

    try:
        result = json.loads(local_job.get("result_json") or "{}")
    except ValueError:
        result = {}
    redline = result.get("redline_path") or ""
    if not redline or not Path(redline).exists():
        return _report_failure(
            remote_id, "the pass finished but produced no marked-up document")

    with open(redline, "rb") as fh:
        payload = fh.read()
    number = _manuscript_number(local_job)

    report = {
        "changes": _count_tracked_changes(payload),
        "ce4_job_id": local_job.get("id"),
        # The findings that have nowhere to sit in the redline. Measured on a real
        # manuscript: the pass flagged 7 things and only 3 could be anchored as Word
        # comments, and 10 house-style findings — a missing Abstract heading, references
        # without a hanging indent — are about the document rather than any span of it.
        # Sending only the marked-up file loses all fourteen, silently.
        "findings": result.get("findings") or {},
        # What the review came to, when there was one. Afterwards, a manuscript somebody
        # actually looked at and one whose thirty seconds ran out unwatched are otherwise
        # indistinguishable — and only one of those is a reviewed manuscript.
        "review": result.get("review") or {},
    }
    # Named for the manuscript, not for the run that produced it. `run_pipeline` writes
    # `user_None_2_redline.docx`, which is fine inside ce4 and meaningless on somebody's
    # manuscript — the editor sees this filename in their file list.
    name = f"{number}-copyedited.docx" if number else "copyedited.docx"
    files = {"file": (name, payload,
                      "application/vnd.openxmlformats-officedocument."
                      "wordprocessingml.document")}

    # The editorial report travels as a second file: it is what an editor reads *beside*
    # the redline, and the redline cannot carry it. Its absence is not fatal — a
    # copy edit that came back without its report is still a copy edit — so a missing
    # file here does not fail the return.
    review = result.get("review_report_path") or ""
    if review and Path(review).exists():
        with open(review, "rb") as fh:
            files["report_file"] = (
                f"{number}-copyedit-report.docx" if number else "copyedit-report.docx",
                fh.read(),
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document")

    data = {"report": json.dumps(report)}
    body, content_type = _multipart_body(files, data)

    stamp = str(int(time.time()))
    path = f"/api/v1/copyedit/bridge/result/{remote_id}/"
    response = requests.post(
        base_url() + path, data=body, timeout=HTTP_TIMEOUT,
        headers={"Content-Type": content_type, "X-CE4-Timestamp": stamp,
                 "X-CE4-Signature": _signature("POST", path, stamp, body)})
    if response.status_code not in (200, 201):
        print(f"[bridge] returning {remote_id} failed: {response.status_code} "
              f"{response.text[:160]}", flush=True)
        return False
    _mark_returned(remote_id)
    print(f"[bridge] returned {remote_id}", flush=True)
    return True


def _manuscript_number(local_job: dict) -> str:
    try:
        return json.loads(local_job.get("options_json") or "{}").get(
            "manuscript_number", "")
    except ValueError:
        return ""


def _count_tracked_changes(payload: bytes) -> Dict[str, int]:
    """How much was actually changed, counted from the file being sent.

    Measured rather than taken from the pipeline's own summary: the redline is what the
    editor opens, so the number beside it on the manuscript should describe that file and
    nothing else. An empty count here means a pass that changed nothing, which is a real
    and reportable outcome.
    """
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            document = archive.read("word/document.xml").decode("utf-8", "replace")
            comments = 0
            if "word/comments.xml" in names:
                comments = archive.read("word/comments.xml").decode(
                    "utf-8", "replace").count("<w:comment ")
    except (zipfile.BadZipFile, KeyError):
        return {}
    return {"insertions": document.count("<w:ins "),
            "deletions": document.count("<w:del "),
            "queries": comments}


def _report_failure(remote_id: str, message: str) -> bool:
    """Tell the platform there is no file, and why.

    A failure that is only logged here leaves the manuscript sitting in "with ce4"
    forever, which reads exactly like a job that is still running.
    """
    body = json.dumps({"error": message}).encode()
    path = f"/api/v1/copyedit/bridge/result/{remote_id}/"
    try:
        response = _call("POST", path, body=body)
    except requests.RequestException as exc:
        print(f"[bridge] could not report failure for {remote_id}: {exc}", flush=True)
        return False
    if response.status_code in (200, 202):
        _mark_returned(remote_id)
        return True
    print(f"[bridge] failure report for {remote_id} rejected: "
          f"{response.status_code} {response.text[:120]}", flush=True)
    return False


class BridgeNotReady(RuntimeError):
    """The platform has no shared secret yet. Expected before setup; not an error here."""


# ----------------------------------------------------------------------------------
# What we have taken, and what we have answered
# ----------------------------------------------------------------------------------
#
# Kept in ce4's own database beside the jobs it refers to. Two columns carry the whole
# point: `mng_job_id` is what the platform is waiting on, and `returned_at` is the only
# thing that means an answer was actually delivered. Working that out from the local
# job's status instead — "it is done, so it must have gone back" — is how a result that
# never arrived looks identical to one that did.

_SCHEMA_SQLITE = """CREATE TABLE IF NOT EXISTS bridge_jobs (
    mng_job_id  TEXT PRIMARY KEY,
    job_id      INTEGER NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    returned_at TEXT
)"""
_SCHEMA_PG = """CREATE TABLE IF NOT EXISTS bridge_jobs (
    mng_job_id  TEXT PRIMARY KEY,
    job_id      INTEGER NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    returned_at TIMESTAMPTZ
)"""


def ensure_schema() -> None:
    with auth._connect() as conn:                                        # noqa: SLF001
        cur = conn.cursor()
        cur.execute(_SCHEMA_PG if auth._is_postgres() else _SCHEMA_SQLITE)  # noqa: SLF001
        conn.commit()


def _ph() -> str:
    return "%s" if auth._is_postgres() else "?"                          # noqa: SLF001


def _record(job_id: int, remote_id: str) -> None:
    ensure_schema()
    p = _ph()
    with auth._connect() as conn:                                        # noqa: SLF001
        cur = conn.cursor()
        cur.execute(f"INSERT INTO bridge_jobs (mng_job_id, job_id) VALUES ({p},{p})",
                    (str(remote_id), job_id))
        conn.commit()


def _mark_returned(remote_id: str) -> None:
    p = _ph()
    now = "now()" if auth._is_postgres() else "datetime('now')"          # noqa: SLF001
    with auth._connect() as conn:                                        # noqa: SLF001
        cur = conn.cursor()
        cur.execute(f"UPDATE bridge_jobs SET returned_at={now} WHERE mng_job_id={p}",
                    (str(remote_id),))
        conn.commit()


def unreturned() -> Iterator[tuple]:
    """Local jobs that have finished and whose answer has not been delivered."""
    ensure_schema()
    with auth._connect() as conn:                                        # noqa: SLF001
        cur = conn.cursor()
        cur.execute("SELECT mng_job_id, job_id FROM bridge_jobs WHERE returned_at IS NULL")
        rows = cur.fetchall()
    for row in rows:
        remote_id = row["mng_job_id"] if isinstance(row, dict) else row[0]
        job_id = row["job_id"] if isinstance(row, dict) else row[1]
        yield str(remote_id), int(job_id)


# ----------------------------------------------------------------------------------
# The loop
# ----------------------------------------------------------------------------------


def tick() -> Dict[str, int]:
    """One pass: deliver what is finished, then take on what is waiting.

    Delivering first is deliberate. If this instance can only manage one thing per cycle,
    the useful thing is finishing what somebody is already waiting for, not starting
    something new.
    """
    done = taken = 0
    for remote_id, job_id in list(unreturned()):
        local = auth.get_job(job_id)
        if local is None:
            _report_failure(remote_id, "the copy editing job disappeared from ce4")
            continue
        if local.get("status") in ("done", "error", "cancelled") and return_one(local, remote_id):
            done += 1

    for remote in pending():
        if collect_one(remote):
            taken += 1
    return {"returned": done, "collected": taken}


def run_forever(stop: Optional[threading.Event] = None) -> None:
    if not configured():
        print("[bridge] MNG_BASE_URL/MNG_BRIDGE_SECRET not set — bridge idle", flush=True)
        return
    print(f"[bridge] collecting from {base_url()} every {POLL_SECONDS}s", flush=True)
    ensure_schema()
    while stop is None or not stop.is_set():
        try:
            counts = tick()
            if counts["returned"] or counts["collected"]:
                print(f"[bridge] {counts}", flush=True)
        except BridgeNotReady:
            print("[bridge] the platform has no shared secret yet; waiting", flush=True)
        except requests.RequestException as exc:
            print(f"[bridge] platform unreachable: {exc}", flush=True)
        except Exception as exc:                                          # noqa: BLE001
            print(f"[bridge] tick failed: {type(exc).__name__}: {exc}", flush=True)
        if stop is not None:
            stop.wait(POLL_SECONDS)
        else:
            time.sleep(POLL_SECONDS)


def start_in_background() -> Optional[threading.Thread]:
    """Started beside the worker, not inside the Streamlit app.

    The worker learned this the hard way: anything started from `app.py` only runs when
    somebody opens the page, so after a deploy the queue stood still while the health
    check stayed green.
    """
    if not configured():
        # Said out loud, once. An operator who has just set the two variables needs to be
        # able to tell "not configured" from "configured and broken" by reading the log,
        # and an absence that explains itself is the difference between a restart and an
        # afternoon.
        missing = [n for n, v in (("MNG_BASE_URL", base_url()),
                                  ("MNG_BRIDGE_SECRET", secret())) if not v]
        print(f"[bridge] idle — {' and '.join(missing)} not set "
              f"(env, or {config.data_dir() / SETTINGS_FILE})", flush=True)
        return None
    thread = threading.Thread(target=run_forever, name="mng-bridge", daemon=True)
    thread.start()
    return thread
