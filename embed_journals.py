"""One-off CLI to (re)build the journal embeddings cache.

Run from repo root with the current app settings, e.g.:

    python embed_journals.py
"""
from __future__ import annotations

import json

import config as app_config
from editor import _build_journal_embeddings  # type: ignore  # internal but stable


def main() -> None:
    settings = app_config.get_llm_settings()
    if settings["provider"] in {"gemini", "openrouter"} and not settings["api_key"]:
        raise SystemExit(f"{settings['provider']} requires an API key.")

    try:
        out_path = _build_journal_embeddings(settings)
        with open(out_path, "r") as f:
            journals = json.load(f)
        print(f"Wrote {out_path} ({len(journals)} journals).")
    except Exception as e:
        print(f"Error embedding: {e}")
        raise


if __name__ == "__main__":
    main()
