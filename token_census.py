"""Everything technical the author wrote, counted before and after the copyedit.

Amit, 16 Sep 2026, on why ce4 did not catch the `G_IC` -> `GIC` loss itself: it only
catches what it has been taught to catch. Every guard in `edit_guards` answers one
question about one past failure — did the reference keep its number, did the figure
survive, was the abbreviation expanded twice. A symbol quietly losing the underscore
that makes it a subscript is not any of those questions, so it walked through the
whole chain without touching a single check.

This is the net underneath all of them, and it asks nothing specific: **which technical
tokens were in the author's manuscript and are not in what we are about to hand back?**
A quantity with a unit, a symbol carrying a subscript or superscript marker, a chemical
formula. It does not need to know which way the next failure will come.

What it must not do is fire on correct work. Measured over the redlines already
produced, the first version's findings were about half legitimate copyediting — unit
spacing, mostly, `1J` -> `1 J` — so every class of that is normalised away here rather
than explained away in a report nobody will trust twice:

* whitespace, so `1J` and `1 J` are one token;
* the subscript and superscript digits, so the house `H2O` -> `H₂O` is not a loss;
* the invisible twins, so `µm` and `μm` are one token;
* tokens inside a URL — job #93's `cf_chl` and `f_tk` came out of a Cloudflare
  challenge string in a link that was correctly cleaned up.

And a token is only reported when it is missing from the **whole** edited manuscript,
not from its own paragraph: text moves between paragraphs legitimately, and a loss
that is not a loss is the one thing this cannot afford to report.
"""

from __future__ import annotations

import re
from typing import Dict, List

#: The three families worth counting. Each is something a reader would notice the
#: absence of, and none of them is ordinary prose a copyedit is free to rewrite.
#:
#: Every bound in here was measured against the redlines already produced, not guessed:
#:
#: * the head before `_` is at most three characters, because `Digital_Financial`,
#:   `fabriuc_GSM` and `CAST_UDL` are ordinary words an author typed an underscore
#:   into — and the copyedit opening them up is correct work. A real subscripted
#:   symbol is `G_IC`, `K_IC`, `E_f`, `m_r`.
#: * `A`, `L`, `M` and `t` are not in the unit list. `Figure 16 A comparison of…`
#:   flagged as sixteen amperes, and a reference volume `12A` as twelve.
#: * a chemical formula needs two element groups and small subscripts, or `In 2023`
#:   reads as an indium compound and a DOI suffix like `D2RA01131J` reads as a salt.
_TOKEN = re.compile(r"""(?x)
      \b[A-Za-z][A-Za-z0-9]{0,2}[_^](?:\([A-Za-z0-9,.\-]+\)|[A-Za-z0-9,.\-]+)
    | (?<![\w.,])\d+(?:[.,]\d+)?\s*(?:nm|µm|μm|mm|cm|dm|km|m|kg|mg|µg|ng|g
        |MPa|GPa|kPa|Pa|bar|psi|J|kJ|MJ|eV|W|kW|MW|V|mV|mA|kA
        |Hz|kHz|MHz|GHz|K|°C|°F|mol|mmol|µmol|mM|nM|mL|µL
        |min|h|s|ms|ns|rpm|wt%|vol%)(?![A-Za-z])
    | \b(?:[A-Z][a-z]?\d{1,3}){2,}[A-Z]?[a-z]?\d{0,3}\b
""")

#: A link. Its query string is full of things that look like symbols and are not.
_URL = re.compile(r"https?://\S+|www\.\S+|doi\.org/\S+|10\.\d{4,}/\S+")

#: Subscript digits become plain ones and superscript digits become `^`-marked ones,
#: which is asymmetric on purpose: it is how this pipeline actually behaves. It sets
#: `H2O` as `H₂O`, so the author's `H2O` must match; it sets `R^2` as `R²`, so the
#: author's caret must match — while `R2`, with the marker simply dropped, must not.
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUPERSCRIPT = {"⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4",
                "⁵": "^5", "⁶": "^6", "⁷": "^7", "⁸": "^8", "⁹": "^9"}

#: Kept in step with `edit_guards.INVISIBLE_TWINS` — the same character written twice.
_TWINS = (("µ", "μ"), ("Ω", "Ω"), ("Å", "Å"), ("K", "K"))


def normalise(token: str) -> str:
    """The token stripped of everything a correct copyedit is allowed to change.

    Deliberately does NOT strip `_`, `^` or brackets: those are the difference between
    `G_IC` and `GIC`, which is exactly what this is here to notice.
    """
    text = (token or "").translate(_SUBSCRIPT)
    for sup, marked in _SUPERSCRIPT.items():
        text = text.replace(sup, marked)
    for a, b in _TWINS:
        text = text.replace(a, b)
    return re.sub(r"\s+", "", text)


def _tokens_outside_links(text: str) -> List[str]:
    return _TOKEN.findall(_URL.sub(" ", text or ""))


#: A number and its unit, so the two halves can be looked for separately.
_QUANTITY = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(.+)$")


def _quantity_survives(token: str, flat: str) -> bool:
    """True when the value is still there, written differently.

    `(between 45°C - 48°C)` becomes `(45–48°C)`, which is a correct edit and removes
    the token `45°C` from the document. Asking for the number and its unit close
    together, rather than for the token itself, keeps that out of the report — and
    still catches the losses that matter, where the number goes with everything else:
    `K_IC ≈ 0.7 MPa` left no `0.7` anywhere in job #100.
    """
    m = _QUANTITY.match(normalise(token))
    if not m:
        return False
    number, unit = m.group(1), m.group(2)
    return bool(re.search(rf"{re.escape(number)}.{{0,40}}?{re.escape(unit)}", flat))


def missing_tokens(
    original: List[str], edited: List[str],
) -> List[Dict[str, object]]:
    """One query per technical token the author wrote and the copyedit did not return.

    Reported once each, against the first paragraph it went missing from: a term used
    in six paragraphs is one thing to check, not six.
    """
    survivors = {normalise(t)
                 for para in edited for t in _tokens_outside_links(para or "")}
    # Text a copyedit moves is not text it lost, and a symbol can also turn up inside
    # a sentence that was rewritten around it — so the whole edited manuscript is the
    # haystack, flattened, not the matching paragraph.
    flat = normalise(" ".join(p or "" for p in edited))

    seen: set = set()
    queries: List[Dict[str, object]] = []
    for i in range(min(len(original), len(edited))):
        before, after = original[i] or "", edited[i] or ""
        if not before or before == after:
            continue
        for token in _tokens_outside_links(before):
            key = normalise(token)
            if not key or key in seen or key in survivors or key in flat:
                continue
            if _quantity_survives(token, flat):
                continue
            seen.add(key)
            queries.append({
                "index": i,
                "snippet": before[:200],
                "query": (f"`{token}` is in the author's manuscript and is not in the "
                          f"copyedited text anywhere. Please check whether it was "
                          f"meant to go — a unit, a subscript or a formula that "
                          f"disappears is rarely an improvement."),
                "suggestion": None,
                # Only the author knows whether a value was meant to go.
                "audience": "author",
            })
    return queries
