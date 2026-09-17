"""Which field this manuscript belongs to, from what the system already knows.

Amit, 17 Sep 2026: *"jaise ye pehle hi detect kar leta hai ki US/UK English use karna
hai, waise hi iska subject/department ka detection ho jaye — Engineering / Medical /
Law / Chemistry?"*

**Nothing new has to be guessed.** The journal recommender already reads the abstract
and returns the three journals it fits best, each carrying the portfolio's own subject
topics. The manuscript's field is what those three agree on.

**The unit is the domain, not the topic, and that is the whole finding.** Measured over
the 78 completed jobs on this platform:

* at the **journal topic** level — `Mechanical Engineering` against `Energy` against
  `Material Science` — the top three agree on one answer in 33 of 78, **42%**;
* rolled up to **domain** — all three of those are engineering — they agree in **65 of
  78, 83%**.

That is the same ceiling found when the recommender itself was measured in September:
three separate methods all stopped near 50% and made the same mistakes, because the
limit is in how fine the label is, not in the method. Asked a coarser question, the
signal that was already there answers it.

So this reports a domain and how many of the three agreed. A manuscript where they
split is reported as split — an editor reading "engineering (2 of 3; the third said
chemistry)" knows exactly how much to trust it, and a single confident-looking word
would not have told them.
"""

from __future__ import annotations

import collections
from typing import Any, Dict, List, Optional, Tuple

#: The portfolio's own topic words, grouped. Built from the 274 journals in
#: `journals.json` rather than from a general taxonomy: these are the words this
#: publisher actually uses, and a scheme that does not cover them classifies nothing.
DOMAINS: Dict[str, Tuple[str, ...]] = {
    "engineering": (
        "mechanical engineering", "electrical engineering", "civil", "construction",
        "electronics", "telecommunication", "energy", "material science", "materials",
        "chemical engineering", "automobile", "aerospace", "industrial", "production",
        "mining", "textile", "petroleum", "instrumentation", "robotics", "polymer",
        "nano technology", "nanotechnology",
    ),
    "computer & IT": (
        "computer", "information technology", "software", "data science",
        "artificial intelligence", "networking", "cyber",
    ),
    "chemistry": ("chemistry", "analytical chemistry", "organic chemistry",
                  "physical chemistry", "inorganic chemistry"),
    "life sciences": ("life sciences", "biotechnology", "bio technology",
                      "microbiology", "biology", "botany", "zoology", "genetics",
                      "environmental"),
    "medical & health": ("medical", "medicine", "pharmacy", "pharmaceutical",
                         "nursing", "dental", "health", "clinical", "ayurveda",
                         "physiotherapy"),
    "agriculture": ("agriculture", "agronomy", "horticulture", "food technology",
                    "dairy", "veterinary", "fisheries", "forestry"),
    "management & commerce": ("management", "commerce", "business", "finance",
                              "economics", "marketing", "accounting", "banking"),
    "law": ("law", "legal", "jurisprudence"),
    "education & social sciences": ("education", "social sciences", "psychology",
                                    "sociology", "humanities", "english", "library",
                                    "journalism"),
    "physics & maths": ("physics", "mathematics", "statistics", "astronomy"),
}


def domain_of_topic(topic: str) -> Optional[str]:
    """The domain a journal topic belongs to, or None.

    Longest match wins: `chemical engineering` contains `chemistry`'s neighbour
    `chemical` and is engineering, while `analytical chemistry` is chemistry. A
    shortest-match rule put every chemical engineering journal in the wrong place.
    """
    text = (topic or "").lower()
    best: Optional[Tuple[str, int]] = None
    for domain, words in DOMAINS.items():
        for word in words:
            if word in text and (best is None or len(word) > best[1]):
                best = (domain, len(word))
    return best[0] if best else None


def detect(recommended: List[Dict[str, Any]], consider: int = 3) -> Optional[Dict[str, Any]]:
    """`{domain, agreed, of, others}` from the recommended journals, or None."""
    domains: List[str] = []
    for journal in (recommended or [])[:consider]:
        for topic in (journal.get("topics") or []):
            found = domain_of_topic(topic)
            if found:
                domains.append(found)
                break
    if not domains:
        return None
    counted = collections.Counter(domains)
    domain, agreed = counted.most_common(1)[0]
    return {
        "domain": domain,
        "agreed": agreed,
        "of": len(domains),
        "others": [d for d in counted if d != domain],
    }


def as_sentence(detected: Optional[Dict[str, Any]]) -> str:
    """One line for a report, saying how much to trust it."""
    if not detected:
        return ""
    domain, agreed, total = detected["domain"], detected["agreed"], detected["of"]
    if agreed == total:
        return f"Subject area: {domain} (all {total} recommended journals agree)."
    others = ", ".join(detected["others"])
    return (f"Subject area: {domain} ({agreed} of {total} recommended journals; "
            f"the rest said {others}).")
