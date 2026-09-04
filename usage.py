"""What a job cost, recorded instead of discarded.

Nothing stopped one user from submitting a 500-page file twenty times, and no job
recorded what it spent. The usage block has been in every provider response all along
and was being thrown away — except for one field, read only to explain an empty answer.

**Cost comes from the provider, not from a price table here.** OpenRouter returns the
real charge for the call when usage accounting is switched on. A hardcoded table of
per-million prices is right on the day it is written and quietly wrong afterwards:
model prices change, a model is swapped in the settings, and the number on the screen
stays confident and false. If the provider does not report a cost, this records `None`
and the UI says the cost is unknown — which is true — rather than inventing one.

Attribution is explicit. Three jobs can run at once and each spawns its own worker
pool, so a module-level counter would blend them, and a `contextvar` would not reach
the pool threads (`ThreadPoolExecutor` does not copy context). The meter therefore
travels in the settings dict, which is already built fresh per job and already threaded
through every call.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

#: The key the meter travels under. Private so it cannot collide with a real setting,
#: and so `normalize_llm_settings` — which rebuilds the dict from known keys — drops it
#: harmlessly rather than trying to stringify it.
METER_KEY = "_usage_meter"


class Meter:
    """Thread-safe running total for one job.

    Every counter is also broken down per model, because the settings can change
    between jobs and a total with no model attached cannot be checked against a
    provider invoice later.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_tokens = 0
        self.reasoning_tokens = 0
        #: None until at least one call reports a cost. Stays None if the provider
        #: never reports one — "unknown" is a real answer and must not read as free.
        self.cost_usd: Optional[float] = None
        self.by_model: Dict[str, Dict[str, Any]] = {}

    def record(self, usage: Optional[Dict[str, Any]], model: str = "") -> None:
        """Add one provider response's usage block."""
        if not usage:
            return
        prompt = _int(usage.get("prompt_tokens"))
        completion = _int(usage.get("completion_tokens"))
        details = usage.get("prompt_tokens_details") or {}
        cached = _int(details.get("cached_tokens"))
        comp_details = usage.get("completion_tokens_details") or {}
        reasoning = _int(comp_details.get("reasoning_tokens"))
        cost = usage.get("cost")
        cost = float(cost) if isinstance(cost, (int, float)) else None

        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.cached_tokens += cached
            self.reasoning_tokens += reasoning
            if cost is not None:
                self.cost_usd = (self.cost_usd or 0.0) + cost
            row = self.by_model.setdefault(model or "unknown", {
                "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "cached_tokens": 0, "cost_usd": None,
            })
            row["calls"] += 1
            row["prompt_tokens"] += prompt
            row["completion_tokens"] += completion
            row["cached_tokens"] += cached
            if cost is not None:
                row["cost_usd"] = (row["cost_usd"] or 0.0) + cost

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cached_tokens": self.cached_tokens,
                "reasoning_tokens": self.reasoning_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
                "cost_usd": self.cost_usd,
                "by_model": {k: dict(v) for k, v in self.by_model.items()},
            }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def attach(settings: Optional[Dict[str, Any]], meter: Meter) -> Dict[str, Any]:
    """Put `meter` in a job's settings so every call it makes is counted against it."""
    settings = dict(settings or {})
    settings[METER_KEY] = meter
    return settings


def meter_from(settings: Optional[Dict[str, Any]]) -> Optional[Meter]:
    """The meter for this call, or None when nothing is being metered.

    Returning None rather than a throwaway Meter is deliberate: a silently discarded
    total is how this stops working without anyone noticing.
    """
    if not isinstance(settings, dict):
        return None
    meter = settings.get(METER_KEY)
    return meter if isinstance(meter, Meter) else None


def format_cost(cost_usd: Optional[float]) -> str:
    """For display. `None` must never render as a number."""
    if cost_usd is None:
        return "not reported"
    if cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    return f"${cost_usd:.2f}"


def from_gemini(response: Any) -> Optional[Dict[str, Any]]:
    """Translate the Gemini SDK's `usage_metadata` into the OpenAI-shaped block.

    Different names for the same numbers. No cost: the Gemini SDK does not report
    one, so cost stays `None` for that provider and the UI says so rather than
    showing a zero that reads like "this was free".
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    return {
        "prompt_tokens": getattr(meta, "prompt_token_count", 0),
        "completion_tokens": getattr(meta, "candidates_token_count", 0),
        "prompt_tokens_details": {
            "cached_tokens": getattr(meta, "cached_content_token_count", 0) or 0,
        },
        "completion_tokens_details": {
            "reasoning_tokens": getattr(meta, "thoughts_token_count", 0) or 0,
        },
    }
