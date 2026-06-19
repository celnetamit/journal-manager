# Journal Recommendation Blueprint (Reusable)

A portable specification for building a **manuscript → journal recommendation** feature
in any application. It captures the *hybrid* approach used in this codebase: cheap
deterministic heuristics decide **who is eligible**, an LLM decides **the final ranking
and reasoning**, and a validation layer guarantees every recommendation is a **real,
active journal** from your own database.

> The LLM prompt is only ~40% of the solution. The pipeline rules around it
> (pre-filter, constrain, validate, scope-gate) are what prevent wrong or
> hallucinated journals. Do not ship the prompt alone.

---

## 1. Concept in one sentence

> Fingerprint the paper → score every active journal with a cheap heuristic →
> have the LLM pick the top 3 **only from that scored candidate list** → drop any
> journal not in your master list → cross-check each pick against the heuristics
> (penalising weak fits) → return the best 3 with rationale and your own metadata.

---

## 2. Pipeline overview

```
Manuscript
   │
   ▼
[1] Profile / fingerprint  ── domains, subdomains, methodology, articleType,
   │                           audience, keywords, focus & scope
   ▼
[2] Heuristic pre-filter   ── score every ACTIVE journal, keep top ~40–60
   │                           (term overlap + domain match + scope keywords)
   ▼
[3] LLM recommendation     ── send manuscript + candidate list, get top 3
   │                           (constrained to the candidate list)
   ▼
[4] Validate               ── exact match → accept; conservative fuzzy (>0.9) →
   │                           remap; else DISCARD as hallucination
   ▼
[5] Scope gate             ── cross-check each pick vs its heuristic score;
   │                           penalise (don't delete) on disagreement
   ▼
[6] Merge + cap to 3       ── LLM picks first; backfill with top heuristic matches
   │
   ▼
Final 3 recommendations (with your DB's real URLs/metadata + rationale)
```

---

## 3. Step 1 — Manuscript fingerprint

Extract a structured profile of the paper. This is the "what is this about" signal that
every later step matches against.

| Field | Description |
|-------|-------------|
| `domains` | Primary research fields (e.g. "Computer Science") |
| `subdomains` | Narrower areas (e.g. "Machine Learning") |
| `methodology` | e.g. "experimental", "qualitative", "review" |
| `articleType` | e.g. "Original Research", "Review", "Case Study" |
| `audience` | Intended readership |
| `keywords` | Author + extracted keywords |
| `focusAndScope` | One-paragraph scope statement |

Build it from `title + abstract + keywords + full text`. An LLM call or a rules-based
extractor both work; keep it deterministic enough to be cacheable.

---

## 4. Step 2 — Heuristic pre-filter (candidate selection)

Do **not** send your whole journal table to the LLM. Score each **active** journal with a
cheap formula and keep only the strongest candidates.

**Inputs per journal:** `name`, `scope/focus`, `about`, `primaryDomains`, `keywords`, `category`.

**Suggested score (0–100):**

```
score = topicalOverlap        // IDF-weighted term overlap (manuscript vs journal text)
      + domainMatch           // structured primaryDomains match + scope mentions
      + scopeKeywords         // manuscript keywords/focus found in journal scope text
```

**Gating rules (tunable):**

- Manuscript's specific keywords appear **nowhere** in the journal text →
  **reject (0)**, *unless* domain match is strong (≥ 60) → **penalise (cap ~55)** instead.
  *(Terminology differs — e.g. "COVID-19" vs "pandemic infectious disease" — so a strong
  domain match should rescue an on-topic journal rather than killing it.)*
- Both domain **and** topical scores weak → reject.
- Domain weak but not zero → cap the score and flag a risk note.

Sort descending and keep the **top 40–60** as the candidate pool. Pass each candidate's
`preScreenScore` to the LLM as a prior (not a final answer).

> **Always exclude inactive/archived/deleted journals** before they reach the candidate
> list, or you will recommend journals that should never be suggested.

---

## 5. Step 3 — The LLM prompt

Use a **system** message + a **user** message. Replace `{{...}}` at runtime.

### System prompt

```text
You are an expert scholarly publishing advisor and journal-fit recommendation engine.
Your job is to recommend the THREE journals that best fit a given manuscript, chosen
ONLY from a supplied candidate list.

=== HARD CONSTRAINTS ===
1. You MUST ONLY recommend journals whose ID and name appear EXACTLY in the
   "Candidate Journals" list. Copy the id and name verbatim. Any recommendation
   whose name is not found verbatim in that list will be discarded.
2. Do NOT invent, abbreviate, merge, or modify journal names or IDs.
3. If fewer than three candidates are a reasonable fit, return fewer — never pad
   with poor matches.
4. Judge fit HOLISTICALLY, not by keyword overlap alone. Terminology can differ
   (e.g. "COVID-19" vs "pandemic infectious disease") — reward true topical and
   domain alignment even when exact words differ.
=== END CONSTRAINTS ===

Scoring rubric (weights) for overall_fit_score (0-100):
- Scope alignment .......... 30%
- Domain/field match ....... 20%
- Target audience .......... 15%
- Methodology fit .......... 15%
- Contribution/article type  10%
- Other (impact, etc.) ..... 10%

Treat closely related fields as compatible (e.g. "Computer Science" and
"Information Technology"). Be conservative: a high score requires genuine scope
AND domain alignment, not just one of them.

Return ONLY valid JSON matching the requested schema. No markdown, no commentary.
```

### User prompt

```text
MANUSCRIPT
Title: {{title}}
Abstract: {{abstract}}
Keywords: {{keywords_comma_separated}}
Profile: {{fingerprint_json}}        // domains, subdomains, methodology, articleType, audience
Full text (excerpt): {{content_first_30000_chars}}

CANDIDATE JOURNALS (id | name) — recommend only from this list:
{{numbered_list_of_id_and_name}}

CANDIDATE DETAILS (use this evidence to judge fit):
{{candidate_details_json}}
// each item: { id, name, scope, about, primaryDomains, keywords, category, preScreenScore }
// preScreenScore = your heuristic pre-rank (0-100)

INSTRUCTIONS
1. Build a manuscript profile (primary domain, specific topics, methodology, contribution type).
2. For EACH candidate, assess scope, domain, audience, methodology, and contribution fit
   using its scope/about/keywords/primaryDomains.
3. Select the top 3 by the weighted rubric. Prefer candidates with strong scope AND
   domain alignment. Use preScreenScore as a prior, not a final answer.
4. For each pick, give concrete, evidence-based reasons grounded in the candidate's
   own scope text — not generic praise.
5. Return the JSON schema exactly.
```

---

## 6. Output schema

Bind this to JSON mode / forced tool output if your SDK supports it, so the model can't drift.

```json
{
  "manuscript_profile": {
    "primary_domain": "",
    "secondary_domains": [],
    "main_topics": [],
    "methodology": [],
    "contribution_type": "",
    "summary_of_fit_needs": ""
  },
  "recommended_journals": [
    {
      "rank": 1,
      "journal_id": "",
      "journal_name": "",
      "overall_fit_score": 0,
      "confidence": "High | Medium | Low",
      "fit_verdict": "Excellent Fit | Good Fit | Possible Fit",
      "why_this_journal": "",
      "evidence_based_match": {
        "scope_alignment": "",
        "topic_alignment": "",
        "audience_alignment": "",
        "methodology_fit": "",
        "contribution_fit": ""
      },
      "strengths_of_match": [],
      "fit_risks_or_cautions": []
    }
  ],
  "final_recommendation_summary": {
    "best_overall_journal": "",
    "why_best_overall": "",
    "selection_logic": ""
  }
}
```

---

## 7. Step 4 — Validate (anti-hallucination)

Even with the hard constraint, **never trust the returned names blindly**. For each
recommended journal:

1. **Exact match** against your real list (case-insensitive) → accept.
2. Else **conservative fuzzy match** — accept only if similarity is high
   (e.g. normalised containment or Dice coefficient **> 0.9**); remap to the canonical name.
3. Else **discard** as a hallucination (and log it).

Always pull the journal's **URL and metadata from your own DB** keyed by the validated
`journal_id` — never use any URL/field the LLM emits.

```text
normalise(name) = lowercase, strip punctuation, drop stop-words (the/of/and/for/in/on/a/an),
                  collapse whitespace
match if:  normalised equal
        OR one contains the other AND shorter/longer > 0.92
        OR Dice(token overlap) > 0.9 with >= 2 shared tokens
```

---

## 8. Step 5 — Scope gate (cross-check)

Compare each surviving LLM pick against your **heuristic score for that same journal**.
This is a *soft* gate — it never deletes a pick (the LLM sometimes catches real fits the
heuristic misses), it only adjusts the score:

- **Heuristic checks fail** (e.g. domain match very low, scope relevance < 40, or score
  below a floor) → keep the pick but **penalise** its score (e.g. `× 0.8`) and attach a
  warning risk-factor.
- **Checks pass** → **blend** the scores (e.g. `0.45 × LLM + 0.55 × heuristic`) for a
  calibrated final score.
- **No heuristic match at all** → keep only if LLM confidence/score is high; otherwise
  flag "no deterministic fallback".

---

## 9. Step 6 — Merge & finalise

1. Take validated + scope-gated **LLM picks first** (they're already constrained and checked).
2. **Backfill** with top heuristic matches if there are fewer than 3.
3. Sort by final score, **cap to 3**.
4. (Optional) Add a comparative rationale: "why this one over the others".

---

## 10. Tunable parameters (start here, then calibrate on real cases)

| Parameter | Suggested default | Notes |
|-----------|-------------------|-------|
| Candidate pool size | 40–60 | Cost vs recall trade-off |
| Content excerpt length | ~30,000 chars | Fit your model's context budget |
| Keyword-miss rescue domain threshold | 60 | Below → reject; ≥ → penalise/cap |
| Eligibility floor (heuristic) | score ≥ 45, domain ≥ 40 | Minimum to be a candidate |
| Fuzzy-match acceptance | > 0.9 | Higher = stricter anti-hallucination |
| Scope-gate penalty | × 0.8 | Applied when heuristic disagrees |
| Final result count | 3 | |

---

## 11. Failure modes this design prevents

| Symptom | Prevented by |
|---------|-------------|
| Recommends journals that don't exist | Constrain to candidate list + exact/fuzzy validation (Steps 3, 4) |
| Recommends deactivated/archived journals | Active-only candidate pool (Step 2) |
| On-topic journal dropped over terminology | Domain-aware keyword rescue (Step 2) |
| LLM confidently picks an off-topic journal | Scope gate penalises on heuristic disagreement (Step 5) |
| Wrong/placeholder URLs | Always use your DB's metadata by validated id (Step 4) |
| Returns 3 weak matches when only 1 fits | "Never pad" constraint + cap, not fill (Steps 3, 9) |

---

## 12. Reference implementation (this codebase)

| Stage | File / function |
|-------|------|
| Orchestration | `editor.py` — `recommend_journals()` |
| Semantic scoring (embeddings) | `editor.py` — `cosine_similarity`, `_build_journal_embeddings` |
| Heuristic pre-filter / candidate pool | `editor.py` — `_prescreen_score`, candidate slice in `recommend_journals` |
| Candidate shortlist + LLM prompt | `editor.py` — `_llm_rank_journals` |
| Validation (anti-hallucination) + scope gate | `editor.py` — `_validate_and_gate`, `_names_match`, `_normalize_journal_name` |
| Merge & cap | `editor.py` — backfill loop in `recommend_journals` |
| Rationale enrichment | `editor.py` — `_explain_journal_match`, `_finalize` |
| Report / UI surfacing | `editor.py` `build_journal_report`, `app.py`, `pipeline.py` `_sanitize_recommended` |

> The LLM call uses whichever provider is configured in the admin LLM settings
> (Gemini / OpenRouter / OpenAI-compatible) via `editor._generate_text` — there is
> no separate model for recommendations. The whole LLM stage degrades gracefully:
> if it is unavailable or fails, `recommend_journals` falls back to the
> pure-semantic top-k ranking.
>
> **Note on this catalogue:** `journals.json` carries only `name`, `topics`,
> `publisher`, and `impact_factor` (no rich scope/about/category or stable id),
> so the implementation uses `topics` as the scope-evidence signal and the list
> index as the candidate id. Steps that depend on richer fields in the blueprint
> are approximated accordingly.
