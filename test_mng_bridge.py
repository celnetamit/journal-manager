"""The manuscript-ngine bridge, from this side.

The one test that matters most is `test_the_signature_matches_the_platforms`: the two
implementations are in different repositories on different hosts, and if they ever drift
the symptom is a bridge that authenticates against nothing and a queue that never drains.
So the platform's construction is written out here independently rather than imported,
and the two are compared. A copy that is derived from the thing it checks checks nothing.

The rest is about the states a handover can get stuck in, because those are the ones that
look like success: a claim that was refused, a pass that produced no file, a result that
was posted and rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MNG_BASE_URL", "https://manuscript-engine.example/")
    monkeypatch.setenv("MNG_BRIDGE_SECRET", "a-shared-secret-for-tests")
    import importlib

    import auth
    import config
    importlib.reload(config)
    importlib.reload(auth)
    auth.init_auth()
    import mng_bridge
    importlib.reload(mng_bridge)
    mng_bridge.ensure_schema()
    return mng_bridge


# ----------------------------------------------------------------------------------
# The thing that must not drift
# ----------------------------------------------------------------------------------


def test_the_signature_matches_the_platforms(bridge):
    """Written out the way the platform builds it, not imported from it."""
    secret = "a-shared-secret-for-tests"
    method, path, stamp, body = "POST", "/api/v1/copyedit/bridge/claim/x/", "1757000000", b'{"a":1}'

    digest = hashlib.sha256(body).hexdigest()
    platform = hmac.new(secret.encode(),
                        f"{method}\n{path}\n{stamp}\n{digest}".encode(),
                        hashlib.sha256).hexdigest()

    assert bridge._signature(method, path, stamp, body) == platform


def test_an_empty_body_is_signed_as_the_empty_hash(bridge):
    """A GET has no body, and both sides must agree on what that hashes to."""
    empty = hashlib.sha256(b"").hexdigest()
    assert empty == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    a = bridge._signature("GET", "/p/", "1757000000", b"")
    b = bridge._signature("GET", "/p/", "1757000000", None)
    assert a == b


def test_the_signature_is_bound_to_method_and_path(bridge):
    base = bridge._signature("GET", "/a/", "1757000000", b"")
    assert bridge._signature("POST", "/a/", "1757000000", b"") != base
    assert bridge._signature("GET", "/b/", "1757000000", b"") != base


# ----------------------------------------------------------------------------------
# Being switched off
# ----------------------------------------------------------------------------------


def test_without_configuration_the_bridge_does_not_start(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MNG_BASE_URL", raising=False)
    monkeypatch.delenv("MNG_BRIDGE_SECRET", raising=False)
    import importlib

    import config
    importlib.reload(config)
    import mng_bridge
    importlib.reload(mng_bridge)

    assert mng_bridge.configured() is False
    assert mng_bridge.start_in_background() is None, (
        "an unconfigured bridge should be absent, not a thread logging failures")


def test_an_idle_bridge_says_which_variable_is_missing(tmp_path, monkeypatch, capsys):
    """Silence cannot be told apart from a bridge that is configured and broken."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MNG_BASE_URL", "https://manuscript-engine.example")
    monkeypatch.delenv("MNG_BRIDGE_SECRET", raising=False)
    import importlib

    import mng_bridge
    importlib.reload(mng_bridge)

    mng_bridge.start_in_background()

    said = capsys.readouterr().out
    assert "MNG_BRIDGE_SECRET" in said
    assert "MNG_BASE_URL" not in said, "only the one that is actually missing"


# ----------------------------------------------------------------------------------
# What has been returned is recorded, not inferred
# ----------------------------------------------------------------------------------


def test_a_collected_job_is_recorded_and_only_then_returned(bridge):
    bridge._record(41, "remote-1")
    assert [r for r in bridge.unreturned()] == [("remote-1", 41)]

    bridge._mark_returned("remote-1")
    assert list(bridge.unreturned()) == [], "delivered work stops being outstanding"


def test_a_finished_job_stays_outstanding_until_the_platform_takes_it(bridge, monkeypatch):
    """A local job being 'done' is not evidence the other side received anything."""
    import auth

    job_id = auth.create_job(user_id=None, filename="p.docx", input_path="/tmp/p.docx",
                             options_json=json.dumps({"mng_job_id": "remote-2"}))
    bridge._record(job_id, "remote-2")
    auth.claim_next_job()
    auth.complete_job(job_id, json.dumps({"redline_path": "/nonexistent/redline.docx"}))

    posted = {}
    monkeypatch.setattr(bridge, "_report_failure",
                        lambda rid, msg: posted.update({rid: msg}) or False)
    monkeypatch.setattr(bridge, "pending", lambda: [])

    bridge.tick()

    assert "remote-2" in posted
    assert "no marked-up document" in posted["remote-2"]
    assert list(bridge.unreturned()) == [("remote-2", job_id)], (
        "a report that was not accepted leaves the job outstanding, so it is retried")


def test_a_failed_pass_is_reported_rather_than_left_silent(bridge, monkeypatch):
    import auth

    job_id = auth.create_job(user_id=None, filename="p.docx", input_path="/tmp/p.docx",
                             options_json="{}")
    bridge._record(job_id, "remote-3")
    auth.claim_next_job()
    auth.fail_job(job_id, "the document has no readable body text")

    sent = {}
    monkeypatch.setattr(bridge, "_report_failure",
                        lambda rid, msg: sent.update({rid: msg}) or True)
    monkeypatch.setattr(bridge, "pending", lambda: [])

    counts = bridge.tick()

    assert sent["remote-3"] == "the document has no readable body text"
    assert counts["returned"] == 1


def test_a_vanished_local_job_is_reported_not_retried_forever(bridge, monkeypatch):
    bridge._record(999999, "remote-4")
    sent = {}
    monkeypatch.setattr(bridge, "_report_failure",
                        lambda rid, msg: sent.update({rid: msg}) or True)
    monkeypatch.setattr(bridge, "pending", lambda: [])

    bridge.tick()

    assert "disappeared" in sent["remote-4"]


# ----------------------------------------------------------------------------------
# Bringing work in
# ----------------------------------------------------------------------------------


def test_a_refused_claim_queues_nothing(bridge, monkeypatch):
    import auth

    class Refused:
        status_code = 409
        text = "that job is with ce4, not queued"

    monkeypatch.setattr(bridge, "_call", lambda *a, **k: Refused())

    assert bridge.collect_one({"job_id": "remote-5"}) is None
    assert auth.claim_next_job() is None, "nothing was queued locally"
    assert list(bridge.unreturned()) == []


def test_an_empty_download_is_reported_and_not_queued(bridge, monkeypatch, tmp_path):
    import auth

    class Ok:
        status_code = 200

        def json(self):
            return {"filename": "paper.docx", "variant": "british",
                    "manuscript_number": "JRN-2026-00001"}

        def iter_content(self, _n):
            return iter([b""])

    monkeypatch.setattr(bridge, "_call", lambda *a, **k: Ok())
    sent = {}
    monkeypatch.setattr(bridge, "_report_failure",
                        lambda rid, msg: sent.update({rid: msg}) or True)

    assert bridge.collect_one({"job_id": "remote-6"}) is None
    assert "empty file" in sent["remote-6"]
    assert auth.claim_next_job() is None


def test_a_collected_manuscript_becomes_an_ordinary_job(bridge, monkeypatch):
    import auth

    class Ok:
        status_code = 200

        def json(self):
            return {"filename": "paper.docx", "variant": "american",
                    "manuscript_number": "JRN-2026-00007", "journal_code": "JRN"}

        def iter_content(self, _n):
            return iter([b"PK\x03\x04 pretend docx"])

    monkeypatch.setattr(bridge, "_call", lambda *a, **k: Ok())

    job_id = bridge.collect_one({"job_id": "remote-7"})
    assert job_id is not None

    claimed = auth.claim_next_job()
    assert claimed["id"] == job_id, "the same worker claims it as everything else"
    options = json.loads(claimed["options_json"])
    assert options["lang_type"] == "US English", "the house spelling travels with it"
    assert options["mng_job_id"] == "remote-7"
    assert options["source"] == "manuscript-ngine"


def test_the_options_carry_everything_the_pipeline_insists_on(bridge):
    """Read the requirement out of the pipeline rather than restating it.

    `run_pipeline` reads some options with `opts[...]` and some with `opts.get(...)`; the
    first kind are mandatory and the second are not. A collected job that is missing one
    of the first kind fails after it has been claimed — the manuscript is out of the
    platform's queue and there is nothing to show for it. That is exactly what happened
    the first time this bridge ran against the live platform: `KeyError: 'edit_style'`.

    Deriving the list from the source means a rule added to the pipeline tomorrow breaks
    this test rather than a manuscript.
    """
    import re
    from pathlib import Path

    source = Path("pipeline.py").read_text()
    body = source[source.index("def run_pipeline"):]
    body = body[:body.index("\ndef ", 10)]
    required = set(re.findall(r'opts\["([a-z_]+)"\]', body))
    assert required, "the pipeline stopped reading options this way; update this test"

    options = bridge._options_for({"variant": "british"}, "remote-x", "p.docx")

    missing = required - set(options)
    assert not missing, f"the bridge would queue a job the pipeline cannot run: {missing}"


def test_a_manuscript_that_already_has_a_journal_is_not_sent_shopping(bridge):
    """It arrived from the platform, so it has been submitted somewhere already."""
    options = bridge._options_for({"variant": "british"}, "remote-y", "p.docx")

    assert options["journals_enabled"] is False
    assert options["cover_letter_enabled"] is False
    assert options["ai_review_enabled"] is False, (
        "the platform runs its own peer review; an uncommissioned one arriving inside a "
        "copy-editing return is noise an editor has to explain")


# ----------------------------------------------------------------------------------
# What the editor sees
# ----------------------------------------------------------------------------------


def _docx_with(ins: int, dele: int, comments: int = 0) -> bytes:
    import io
    import zipfile

    body = ("<w:ins >x</w:ins>" * ins) + ("<w:del >y</w:del>" * dele)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document>{body}</w:document>")
        if comments:
            z.writestr("word/comments.xml",
                       "<w:comments>" + "<w:comment >q</w:comment>" * comments
                       + "</w:comments>")
    return buf.getvalue()


def test_the_change_count_is_measured_from_the_file_that_is_sent(bridge):
    counts = bridge._count_tracked_changes(_docx_with(13, 8, comments=4))

    assert counts == {"insertions": 13, "deletions": 8, "queries": 4}


def test_a_pass_that_changed_nothing_reports_zero_not_nothing(bridge):
    """"No changes" is an outcome an editor can act on; a missing number is not."""
    assert bridge._count_tracked_changes(_docx_with(0, 0)) == {
        "insertions": 0, "deletions": 0, "queries": 0}


def test_an_unreadable_file_does_not_take_the_return_down_with_it(bridge):
    assert bridge._count_tracked_changes(b"not a zip at all") == {}


def test_the_returned_file_is_named_for_the_manuscript(bridge):
    job = {"options_json": json.dumps({"manuscript_number": "SMOKE-2026-00003"})}

    assert bridge._manuscript_number(job) == "SMOKE-2026-00003", (
        "ce4 names its output user_None_2_redline.docx, which is meaningless in "
        "somebody's manuscript file list")


def test_settings_can_come_from_the_volume_when_the_environment_cannot_be_changed(
        tmp_path, monkeypatch):
    """The deployment platform owns the environment; the volume survives a deploy."""
    import json as _json

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MNG_BASE_URL", raising=False)
    monkeypatch.delenv("MNG_BRIDGE_SECRET", raising=False)
    (tmp_path / "mng_bridge.json").write_text(_json.dumps(
        {"base_url": "https://manuscript-engine.example/", "secret": "from-the-volume"}))

    import importlib

    import config
    importlib.reload(config)
    import mng_bridge
    importlib.reload(mng_bridge)

    assert mng_bridge.configured() is True
    assert mng_bridge.base_url() == "https://manuscript-engine.example", "no trailing slash"
    assert mng_bridge.secret() == "from-the-volume"


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MNG_BRIDGE_SECRET", "from-the-environment")
    monkeypatch.setenv("MNG_BASE_URL", "https://env.example")
    (tmp_path / "mng_bridge.json").write_text(_json.dumps({"secret": "from-the-volume"}))

    import importlib

    import config
    importlib.reload(config)
    import mng_bridge
    importlib.reload(mng_bridge)

    assert mng_bridge.secret() == "from-the-environment"
