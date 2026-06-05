"""Ad-hoc smoke test: JSON array output from Gemini.

Usage: GEMINI_API_KEY=... python test_json.py
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
        "Journal of Petroleum Engineering & Technology",
        "THE EFFECT OF DYNAMICS AND MASS TRANSFER LIMITATION ON THE KINETIC GROWTH RATE OF METHANE GAS HYDRATES",
    ]
    prompt = f"""You are a copyeditor. I am providing a JSON array of text paragraphs.
Edit them for CMOS style.
Return ONLY a valid JSON array of strings of the exact same length.

Input:
{json.dumps(paras)}
"""
    print(_generate_text(prompt))


if __name__ == "__main__":
    main()
