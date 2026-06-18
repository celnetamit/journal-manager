"""Tests for the shared LLM concurrency cap and 429 exponential backoff."""

import threading
import time

import pytest
import requests

import editor


class FakeResp:
    def __init__(self, status, json_data=None, headers=None):
        self.status_code = status
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _patch_posts(monkeypatch, responses):
    """Serve the given response objects in order; record sleep durations."""
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        r = responses[calls["n"]]
        calls["n"] += 1
        return r

    sleeps = []
    monkeypatch.setattr(editor.requests, "post", fake_post)
    monkeypatch.setattr(editor.time, "sleep", lambda s: sleeps.append(s))
    return calls, sleeps


def test_backoff_retries_then_succeeds(monkeypatch):
    responses = [FakeResp(429), FakeResp(429), FakeResp(200, {"ok": True})]
    calls, sleeps = _patch_posts(monkeypatch, responses)
    out = editor._post_json("http://x", {})
    assert out == {"ok": True}
    assert calls["n"] == 3
    assert sleeps == [2.0, 4.0]  # exponential doubling between attempts


def test_backoff_exhausts_and_raises(monkeypatch):
    responses = [FakeResp(429)] * editor._RATE_LIMIT_MAX_RETRIES
    _patch_posts(monkeypatch, responses)
    with pytest.raises(RuntimeError, match="Rate limited"):
        editor._post_json("http://x", {})


def test_retry_after_header_is_honored(monkeypatch):
    responses = [FakeResp(429, headers={"Retry-After": "7"}), FakeResp(200, {"ok": 1})]
    _calls, sleeps = _patch_posts(monkeypatch, responses)
    editor._post_json("http://x", {})
    assert sleeps == [7.0]  # used the server hint, not the default 2.0


def test_non_429_error_propagates_without_retry(monkeypatch):
    responses = [FakeResp(500)]
    calls, sleeps = _patch_posts(monkeypatch, responses)
    with pytest.raises(requests.HTTPError):
        editor._post_json("http://x", {})
    assert calls["n"] == 1  # no retry on non-429
    assert sleeps == []


def test_semaphore_caps_concurrency():
    cap = editor._llm_max_concurrency()
    sem = editor._LLM_SEMAPHORE
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def worker():
        with sem:
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.02)
            with lock:
                state["now"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(cap + 4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["max"] <= cap  # never more than the cap ran at once
    assert state["max"] >= 1


def test_max_concurrency_env_default():
    assert editor._llm_max_concurrency() >= 1
