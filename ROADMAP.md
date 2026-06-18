# Publisher-Grade Platform — Roadmap

Status: planning document. No code changes implied by this file.
Goal: evolve the current **single-user manuscript-editing tool** into a
**multi-role journal publishing platform** suitable for a publication house.

Effort key: **S** ≈ ≤1 day · **M** ≈ 2–4 days · **L** ≈ 1–2 weeks · **XL** ≈ 3+ weeks
(single engineer, rough estimates).

---

## 1. Where we are today

**Stack:** Streamlit (single-process) · Postgres/SQLite (`auth.py`) · multi-provider
LLM (Gemini / OpenRouter / OpenAI-compatible, `editor.py` + `config.py`).

**Implemented:**
- LLM copyediting with selectable styles (CMOS/APA/MLA/IEEE).
- In-house / publisher rules — toggleable per user, persisted (`user_house_rules`),
  shown in UI; deterministic 6-author enforcement.
- Redline `.docx` (Word track changes), Crossref DOI validation, citation renumbering.
- Journal recommendations (embeddings) **with reasoning**.
- AI peer reviewer (runs in parallel), cover letter, title/abstract polish.
- Reports as `.docx`; **JATS/XML production export** (structured authors, refs,
  figures/tables, in-text xref linking, structural validation).
- History + Analytics tabs; bcrypt auth, login throttling, remember-me tokens.
- Rate-limit hardening: shared concurrency semaphore + 429 exponential backoff.

**Core limitation:** it is a *one-shot tool* — one user processes one file and
downloads outputs. There is no concept of a manuscript moving through a
multi-person editorial process, no roles, and no governance/audit.

---

## 2. Target architecture (the gap)

| Capability | Today | Publisher-grade |
|---|---|---|
| Users | flat, single role | admin / editor / author / reviewer |
| Work unit | a processed file | a **manuscript** with lifecycle state |
| Process | one-shot | submission → review → decision → production |
| Accountability | none | full audit trail |
| Confidentiality | text sent to 3rd-party LLM | self-hosted/no-retention option, governance |
| Production | JATS download | DOI deposit, indexing, typesetting handoff |
| Scale | synchronous in request | background jobs, quotas, observability |

---

## 3. Phases

### Phase 1 — Roles & Audit (foundation) · **M**
**Goal:** identity + access control + accountability. Everything else builds on this.

- `users.role` column (`admin|editor|author|reviewer`), default `author`; first
  user (or env-seeded) becomes `admin`. (`auth.py` schema + migration)
- Role-based gating of tabs/actions in `app.py` (e.g. authors can't see Analytics;
  only editors assign reviewers).
- `audit_log` table: `(id, ts, user_id, action, entity_type, entity_id, detail)`;
  helper `auth.log_audit(...)`; write on login, submit, assign, decide, download.
- Minimal **Admin panel**: list users, change roles, view audit log.

**Depends on:** nothing. **Risk:** low — additive to existing auth.
**Why first:** workflow, admin, and confidentiality controls all need roles.

---

### Phase 2 — Manuscript Submission Workflow · **L**
**Goal:** turn one-shot processing into a tracked, multi-person process.

- `manuscripts` table: `(id, author_id, title, status, created_at, updated_at,
  current_version_id)`. **State machine:**
  `Submitted → Screening → Under Review → Revision Requested → Accepted →
  In Production → Published` (+ `Rejected`, `Withdrawn`).
- `manuscript_versions` table: each upload/revision is a version (file path,
  produced redline/JATS/report paths). Re-point existing `process_logs` outputs
  to a version instead of being standalone.
- `review_assignments` table: editor assigns reviewer(s) to a manuscript; reviewer
  submits a review (reuse/extend the **AI peer reviewer** as a draft the human edits);
  editor records a **decision** (accept/minor/major/reject) with a decision letter.
- UI: Author dashboard (my submissions + status), Editor dashboard (queue, assign,
  decide), Reviewer dashboard (assigned + submit review).
- State transitions enforced server-side and written to `audit_log`.

**Depends on:** Phase 1 (roles). **Risk:** medium — largest data-model change;
needs careful state-transition validation.

---

### Phase 3 — Confidentiality & Data Governance · **M**
**Goal:** make unpublished-manuscript handling acceptable to a publisher.
(Biggest *adoption* blocker, even though it's mostly config/governance.)

- **Self-hosted / no-retention LLM:** document and harden the existing
  OpenAI-compatible/custom path so a publisher can point at self-hosted
  vLLM/Ollama or a no-retention enterprise endpoint. Add a "data handling"
  note per provider in the UI.
- **Don't persist manuscript text** anywhere it isn't needed; audit that logs
  (`process_logs`, prints) never store body content. Add a content-redaction pass
  to logging.
- **Encryption at rest** option for stored output files + DB (deployment-level
  guidance + app-level toggle for output dir).
- **Retention policy:** configurable TTL for generated files and manuscript data;
  ties into Phase 5 cleanup job.
- Per-deployment toggle: `LLM_CONFIG_LOCKED` already exists — extend with a
  "confidential mode" that refuses non-self-hosted providers.

**Depends on:** Phase 1 (roles to scope access). **Risk:** low-medium —
mostly config, docs, and disciplined logging; the LLM path already supports it.

---

### Phase 4 — Production Integration · **L**
**Goal:** close the loop from accepted manuscript to published, indexed article.

- **Crossref DOI deposit** (today we only *validate* DOIs): generate Crossref
  deposit XML from the JATS metadata and submit via the Crossref API; store the
  registered DOI on the manuscript.
- **JATS metadata completion:** article DOI, publication dates, license/copyright,
  funding, ORCID, corresponding author — needed for real deposit/indexing.
- **Typesetting/PDF handoff:** generate a galley PDF (or hand JATS to a typesetting
  tool); attach to the manuscript version.
- **Indexing push** hooks (PubMed/DOAJ) where applicable.

**Depends on:** Phase 2 (manuscripts) + the existing JATS export. **Risk:**
medium — external API integrations (Crossref) need credentials and careful testing.

---

### Phase 5 — Operational Hardening · **L**
**Goal:** reliability and scale for real traffic.

- **Background job queue** (Celery/RQ + Redis, or a DB-backed worker): move
  copyediting/AI-review/JATS off the Streamlit request so long manuscripts don't
  block/timeout; show job status in the UI.
- **File retention/cleanup job:** `data/outbound` grows unbounded today — add a
  scheduled purge by TTL (ties to Phase 3 retention policy).
- **Per-user quotas / cost controls:** cap LLM usage per user/role; surface usage.
- **Observability:** structured logging, error tracking (Sentry), basic metrics.
- **Test coverage:** end-to-end app-flow tests beyond current smoke/unit tests.

**Depends on:** Phases 1–2 for meaningful scoping. **Risk:** medium —
introduces infra (Redis/worker) and deployment changes.

---

## 4. Quick wins (can land anytime, independent) · **S each**
- **README refresh** — document AI reviewer, JATS export, house rules, rate-limit
  env vars (`LLM_MAX_CONCURRENCY`, `LLM_RATE_LIMIT_*`).
- **Output file cleanup** — minimal TTL purge of `data/outbound` (subset of Phase 5).
- **JATS article metadata** — add DOI/license/pub-date fields (subset of Phase 4).
- **Per-user usage counter** in Analytics.

---

## 5. Recommended sequence

```
Phase 1 (Roles & Audit)  ──►  Phase 2 (Workflow)  ──►  Phase 4 (Production)
        │                            │
        └──► Phase 3 (Confidentiality)   Phase 5 (Ops hardening, in parallel once 1–2 land)
```

1. **Phase 1** — unblocks everything; low risk; ~M.
2. **Phase 3** — high adoption value, low effort; can run alongside Phase 2.
3. **Phase 2** — the defining "platform" change; largest single effort.
4. **Phase 4** — only meaningful once manuscripts exist (Phase 2).
5. **Phase 5** — harden once there's real workflow to protect.

Quick wins (README, file cleanup) can be picked up between phases.

---

## 6. Honest caveats
- LLM copyedits/reference parsing remain **heuristic** — a publisher pipeline must
  keep **human-in-the-loop** sign-off; this roadmap adds the workflow *to enforce
  that*, it does not make the AI authoritative.
- Streamlit is fine for the current scale but is a constraint for a large
  multi-tenant platform; Phase 5 mitigates, but a future re-platform (FastAPI +
  proper frontend) may eventually be warranted — out of scope here.
- Estimates assume incremental work on the current stack, not a rewrite.
