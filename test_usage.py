"""Per-job token and cost accounting.

The test that earns its place here is `test_meter_survives_the_real_call_path`. The
meter travels inside the settings dict, and settings are passed through a dozen
functions before reaching the provider call. If any one of them rebuilt the dict — a
`_normalize_settings` on the way down would be enough — the meter would be dropped and
every job would record zero. Zero is a plausible-looking number, so nothing would look
broken; the quota would simply never fire and the cost column would read $0.00 forever.
Reading the call sites says it works. This runs it.

The other rule worth protecting: a provider that reports no cost leaves `cost_usd` as
None, and None renders as "not reported". A zero there would read as "this job was
free", which is a different claim and a false one.
"""

import editor as E
import usage as U


def test_counts_add_up_across_calls():
    m = U.Meter()
    m.record({"prompt_tokens": 100, "completion_tokens": 20,
              "prompt_tokens_details": {"cached_tokens": 80}, "cost": 0.0012}, "model-a")
    m.record({"prompt_tokens": 50, "completion_tokens": 10, "cost": 0.0004}, "model-a")
    snap = m.snapshot()
    assert snap["calls"] == 2
    assert snap["prompt_tokens"] == 150
    assert snap["completion_tokens"] == 30
    assert snap["cached_tokens"] == 80
    assert snap["total_tokens"] == 180
    assert abs(snap["cost_usd"] - 0.0016) < 1e-9


def test_unreported_cost_stays_none_not_zero():
    """A provider that does not price the call must not make the job look free."""
    m = U.Meter()
    m.record({"prompt_tokens": 10, "completion_tokens": 2}, "model-b")
    assert m.snapshot()["cost_usd"] is None
    assert U.format_cost(None) == "not reported"


def test_a_priced_and_an_unpriced_call_report_the_priced_part():
    m = U.Meter()
    m.record({"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.005}, "a")
    m.record({"prompt_tokens": 10, "completion_tokens": 2}, "b")
    assert m.snapshot()["cost_usd"] == 0.005


def test_per_model_breakdown():
    m = U.Meter()
    m.record({"prompt_tokens": 10, "completion_tokens": 1, "cost": 0.001}, "fast")
    m.record({"prompt_tokens": 90, "completion_tokens": 9, "cost": 0.009}, "slow")
    by = m.snapshot()["by_model"]
    assert by["fast"]["prompt_tokens"] == 10
    assert by["slow"]["prompt_tokens"] == 90


def test_missing_or_malformed_usage_is_ignored_not_crashed():
    m = U.Meter()
    m.record(None, "x")
    m.record({}, "x")
    m.record({"prompt_tokens": "not a number"}, "x")
    assert m.snapshot()["calls"] == 1  # only the third was a usage block at all
    assert m.snapshot()["prompt_tokens"] == 0


def test_concurrent_recording_loses_nothing():
    import threading
    m = U.Meter()
    def worker():
        for _ in range(200):
            m.record({"prompt_tokens": 1, "completion_tokens": 1}, "m")
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert m.snapshot()["prompt_tokens"] == 1600


def test_meter_from_returns_none_when_unmetered():
    """None, not a throwaway Meter — a silently discarded total is how this stops
    working without anyone noticing."""
    assert U.meter_from(None) is None
    assert U.meter_from({"provider": "openrouter"}) is None
    assert U.meter_from({U.METER_KEY: "not a meter"}) is None


def test_normalize_settings_drops_the_meter_harmlessly():
    """The meter must not reach the provider payload or break normalization."""
    import config as app_config
    m = U.Meter()
    s = U.attach(app_config.get_llm_settings(), m)
    normalized = app_config.normalize_llm_settings(s)
    assert U.METER_KEY not in normalized


def test_meter_survives_the_real_call_path(monkeypatch):
    """Settings pass through many hands before the provider call. Prove the meter
    arrives, rather than reading the call sites and believing it."""
    seen = {}

    def fake_post(url, payload, headers=None, **kwargs):
        seen["payload"] = payload
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300,
                      "prompt_tokens_details": {"cached_tokens": 1000},
                      "cost": 0.00042},
        }

    monkeypatch.setattr(E, "_post_json", fake_post)
    monkeypatch.setattr(E.time, "sleep", lambda *_: None)

    m = U.Meter()
    settings = U.attach({"provider": "openrouter", "base_url": "https://x/api/v1",
                         "api_key": "k", "text_model": "test-model",
                         "embed_model": "e"}, m)
    E._generate_text("hello", settings=settings)

    snap = m.snapshot()
    assert snap["calls"] == 1, "the meter did not reach the provider call"
    assert snap["prompt_tokens"] == 1200
    assert snap["cached_tokens"] == 1000
    assert snap["cost_usd"] == 0.00042
    assert snap["by_model"]["test-model"]["calls"] == 1


def test_usage_accounting_is_requested_from_the_provider(monkeypatch):
    """Without this in the payload OpenRouter reports no cost, and every job would
    record 'not reported' forever."""
    seen = {}
    monkeypatch.setattr(E, "_post_json", lambda url, payload, headers=None, **kw: (
        seen.update(payload=payload) or
        {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}))
    monkeypatch.setattr(E.time, "sleep", lambda *_: None)
    E._generate_text("hi", settings={"provider": "openrouter", "base_url": "https://x",
                                     "api_key": "k", "text_model": "m", "embed_model": "e"})
    assert seen["payload"].get("usage") == {"include": True}


def test_a_failed_call_still_counts_its_tokens(monkeypatch):
    """An empty answer burned the tokens and appears on the invoice. A total that
    counts only the successes understates what the job cost."""
    import pytest
    monkeypatch.setattr(E, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 4000,
                  "completion_tokens_details": {"reasoning_tokens": 3900},
                  "cost": 0.02},
    })
    monkeypatch.setattr(E.time, "sleep", lambda *_: None)
    m = U.Meter()
    settings = U.attach({"provider": "openrouter", "base_url": "https://x",
                         "api_key": "k", "text_model": "m", "embed_model": "e"}, m)
    with pytest.raises(RuntimeError):
        E._generate_text("hi", settings=settings)
    snap = m.snapshot()
    assert snap["calls"] == 1
    assert snap["prompt_tokens"] == 900
    assert snap["cost_usd"] == 0.02


def test_unmetered_calls_still_work(monkeypatch):
    """Metering is additive. A call with no meter must behave exactly as before."""
    monkeypatch.setattr(E, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": "fine"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1}})
    monkeypatch.setattr(E.time, "sleep", lambda *_: None)
    assert E._generate_text("hi", settings={"provider": "openrouter",
                                            "base_url": "https://x", "api_key": "k",
                                            "text_model": "m", "embed_model": "e"}) == "fine"
