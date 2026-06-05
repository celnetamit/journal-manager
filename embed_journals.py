"""One-off CLI to (re)build journals_embedded.json.

Run from repo root with the env var set, e.g.:

    GEMINI_API_KEY=... python embed_journals.py
"""
from __future__ import annotations

import json
import os
import time

import config as app_config
from editor import _embed  # type: ignore  # internal but stable


def main() -> None:
    key = os.environ.get("GEMINI_API_KEY") or app_config.get_gemini_api_key()
    if not key:
        raise SystemExit("GEMINI_API_KEY not set.")

    in_path = app_config.journals_path()
    out_path = app_config.journals_embedded_path()

    with in_path.open("r") as f:
        journals = json.load(f)

    texts = [j["name"] + " " + " ".join(j.get("topics", [])) for j in journals]

    embeddings = []
    try:
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            for t in batch:
                embeddings.append(_embed(t, api_key=key))
            time.sleep(0.5)
            print(f"  embedded {min(i + 100, len(texts))}/{len(texts)}")

        for j, emb in zip(journals, embeddings):
            j["embedding"] = emb

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(journals, f)
        print(f"Wrote {out_path} ({len(journals)} journals).")
    except Exception as e:
        print(f"Error embedding: {e}")
        raise


if __name__ == "__main__":
    main()
