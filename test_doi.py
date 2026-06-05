"""Ad-hoc smoke test: ask Gemini to append DOIs to two reference paragraphs.

Usage: GEMINI_API_KEY=... python test_doi.py
"""
from __future__ import annotations

import json
import os

from editor import _generate_text  # type: ignore


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        from config import get_gemini_api_key
        os.environ["GEMINI_API_KEY"] = get_gemini_api_key()

    paras = [
        "Einstein A, Podolsky B, Rosen N. Can quantum-mechanical description of physical reality be considered complete?. Physical review. 1935 May 15;47(10):777.",
        "This is just a normal paragraph about some scientific stuff.",
    ]
    prompt = f"""You are a copyeditor. I am providing a JSON array of text paragraphs.
Edit them for CMOS style.
For references/bibliography entries, format to Vancouver style AND append the correct DOI (https://doi.org/...) or source link if possible. Do not hallucinate DOIs.

Input:
{json.dumps(paras)}
"""
    print(_generate_text(prompt))


if __name__ == "__main__":
    main()
