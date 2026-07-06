# Publication House Platform — Foolproof Roadmap

> **Purpose.** Evolve the current single-user AI copyediting tool into a
> multi-role **journal / publication-house management system** where a manuscript
> travels through submission → review → quality → decision → revision →
> copyright → production → publication, and where **all communication is mediated
> by the Journal Manager**.
>
> **Status:** planning document. No code is implied by merging this file.
> **Supersedes/extends:** [`ROADMAP.md`](ROADMAP.md) (the generic multi-role
> roadmap). This document is the authoritative plan for the *publication-house
> operating model* specifically; the generic roadmap's phases are folded in below.
>
> **Effort key:** **S** ≈ ≤1 day · **M** ≈ 2–4 days · **L** ≈ 1–2 weeks ·
> **XL** ≈ 3+ weeks (single engineer, rough).

---

## 0. TL;DR — the shape of the target system

- **Four participant roles** + system admins: **Author**, **Editor/Reviewer**,
  **Quality Team**, **Journal Manager**.
- **The one hard rule:** *no participant may communicate with another participant
  directly.* Every message, file, comment, and decision flows **through the
  Journal Manager**, who is the only role that can talk to everyone. This is a
  hub-and-spoke ("star") topology enforced in the data layer, not just the UI.
- **A manuscript is a first-class object** with a lifecycle state machine, an
  immutable activity timeline (the author's "track record"), versioned
  submissions/resubmissions, a copyright/license step, and a production/publish
  step.
- **Build on what exists:** `auth.py` roles + Postgres schema, the background
  `jobs` queue, the `pipeline.py`/`editor.py` AI engine (copyedit, AI reviewer,
  originality scan, JATS export) become **tools the roles invoke**, not the
  product itself.

---

## 1. The operating model

### 1.1 Roles

| Role | Does | Talks to | Sees |
|---|---|---|---|
| **Author** | Submits manuscript, tracks status, uploads revisions/resubmissions, signs & submits copyright/license, responds to queries. | **Journal Manager only** | Own manuscripts + status + manager messages. Never sees reviewer/quality identities. |
| **Editor / Reviewer** | Reviews assigned manuscripts, writes comments & recommendation (Accept / Minor / Major / Reject). Can use the AI reviewer as a *draft*. | **Journal Manager only** | Only manuscripts assigned to them. **Blind review** (§1.3): sees the author only under single-blind; author masked under double-blind. Never sees other reviewers; author never sees them. |
| **Quality Team** | Runs quality/compliance checks (formatting, house rules, references, ethics, plagiarism/originality, figures, metadata completeness) against a checklist; passes/fails with notes. | **Journal Manager only** | Only manuscripts routed to them for QC. |
| **Journal Manager** | The **hub**. Screens submissions, assigns reviewers & quality, relays every message, collates reviews, records decisions, manages state transitions, drives copyright & production. | **Everyone** (per manuscript they manage) | Full identities + full timeline for their manuscripts. |
| **Admin / Superadmin** *(system)* | User & role management, config, audit, deployment. Not part of editorial content flow. | System-level | Everything (governance), audit logs. |

> **Decision to confirm (see §9):** is "Editor" a distinct handling-editor role,
> or is *Editor/Reviewer* one referee role while the *Journal Manager* is the
> handling editor? This roadmap assumes the latter (Manager = handling editor;
> Editor/Reviewer = referee) and notes where a separate Editor role would slot in.

### 1.2 The communication principle (hub-and-spoke)

```
                 ┌──────────────────────┐
                 │   JOURNAL MANAGER     │  ← the ONLY hub; sees real identities
                 │   (coordinator/hub)   │
                 └───────┬───┬───┬───────┘
             relay ▲     │   │   │     ▲ relay
        ┌──────────┘     │   │   └──────────┐
        │            ┌───┘   └───┐          │
   ┌────┴─────┐  ┌───┴────┐  ┌───┴────┐ ┌───┴──────┐
   │  AUTHOR  │  │REVIEWER│  │REVIEWER│ │ QUALITY  │
   │          │  │   #1   │  │   #2   │ │   TEAM   │
   └──────────┘  └────────┘  └────────┘ └──────────┘
        ╳ no edge between any two spokes — ever ╳
```

- Spokes (Author, Reviewer, Quality) can address **only** the manager of that
  manuscript. There is **no schema path** for spoke → spoke.
- To move information from one spoke to another, the manager **composes a new
  outbound message** (a *relay*). The relay references the source message for
  audit, but the recipient sees the **manager** as sender. The manager may
  redact/anonymize/edit before relaying.
- Identities are **firewalled** per the blinding model (§1.3): the author never
  sees reviewers; reviewers never see each other; only the manager sees everyone.

### 1.3 Blinding model — **blind peer review (confirmed)**

The publication house runs a **double-blind peer-review process (confirmed
default)**. Blinding is stored per manuscript (`manuscripts.double_blind`,
**default `true`**) so a journal can override, but the platform default and the
identity firewall (INV-4) follow the double-blind model:

| Sees identity of → | Author | Reviewer | Quality | Manager |
|---|:--:|:--:|:--:|:--:|
| **Author** sees… | — | ❌ never | ❌ never | ✅ (the manager) |
| **Reviewer** sees… | *see note* | ❌ other reviewers hidden | ❌ | ✅ (the manager) |
| **Quality** sees… | *see note* | ❌ | — | ✅ (the manager) |
| **Manager** sees… | ✅ | ✅ | ✅ | — |

- **Double-blind (house default, `double_blind = true`):** author identity is
  masked from reviewers/quality — name, email, ORCID, and affiliation are
  stripped/aliased on the manuscript copy shown to them — **and** reviewers are
  masked from the author. Neither side sees the other; only the Manager does.
- **Single-blind (`double_blind = false`, optional override):** reviewers/quality
  *do* see the author, but the author still never sees reviewers.

Either way, the hard rule stands: **all contact is mediated by the Journal
Manager**, and the author-facing side is always blind (authors never learn who
reviewed them). Because the default is double-blind, submissions must also carry a
**blinded manuscript file** (author-identifying front matter removed) — the
Quality Team checklist (§5) verifies blinding before a manuscript enters review.

---

## 2. Where the codebase is today (reuse map)

| Asset | File | Role in the new system |
|---|---|---|
| Auth, roles, SSO, throttling | `auth.py` (1150 LOC) | **Extend** role enum; keep login/tokens/audit primitives. |
| Dual DB schema (SQLite + Postgres) | `auth.py` `_ensure_schema*` | **Extend** with manuscript/workflow/comms tables. |
| Background jobs (queue, status, progress) | `auth.py` `jobs` table + workers | **Reuse** to run copyedit/AI-review/JATS off-request per manuscript version. |
| AI engine (copyedit, house rules, AI reviewer, originality, JATS, Crossref) | `editor.py` (2616), `pipeline.py` (360) | Becomes a **toolbox** the Quality Team & Manager invoke on a version — not the whole app. |
| Config, admin allowlists, LLM providers | `config.py` (454) | **Reuse**; add confidential-mode + per-role config. |
| Streamlit UI | `app.py` (1328) | **Refactor** into role-scoped dashboards (or re-platform — see §7.5). |
| Process history, analytics | `process_logs`, `analytics.db` | Re-point to manuscript versions; feed reporting. |

**Core limitation to remove:** today it is a *one-shot tool* (one user, one file,
download). There is no manuscript object, no roles beyond admin, no process, no
mediated communication, no audit of who-did-what.

---

## 3. Target architecture

### 3.1 RBAC matrix (server-enforced, not UI-only)

| Action | Author | Reviewer | Quality | Manager | Admin |
|---|:--:|:--:|:--:|:--:|:--:|
| Submit / resubmit manuscript | ✅ (own) | — | — | — | — |
| View manuscript (full identities) | own only | assigned, **anonymized** | assigned, **anonymized** | managed | all |
| Assign reviewer / quality | — | — | — | ✅ | — |
| Submit review / recommendation | — | ✅ (assigned) | — | — | — |
| Submit quality check | — | — | ✅ (assigned) | — | — |
| Record editorial decision | — | — | — | ✅ | — |
| Transition manuscript state | submit/withdraw/resubmit/copyright | submit-review | submit-QC | **all others** | override |
| Send message | → Manager only | → Manager only | → Manager only | → any participant | — |
| Relay message (compose on behalf) | — | — | — | ✅ | — |
| Submit copyright/license | ✅ (own) | — | — | receive | — |
| Manage users/roles/config | — | — | — | — | ✅ |
| Read audit log | own timeline | own actions | own actions | managed manuscripts | all |

### 3.2 Manuscript lifecycle (state machine)

```
        ┌─────────┐  author submits   ┌──────────────────┐
        │  DRAFT  ├──────────────────►│    SUBMITTED     │
        └─────────┘                   └────────┬─────────┘
                                     manager screens
                                                │
                      manager desk-rejects ◄────┼────► ┌──────────────────┐
                                                │      │  QUALITY_CHECK   │ (Quality Team)
                                                ▼      └────────┬─────────┘
                                       ┌──────────────┐  pass   │  fail → back to author (revision)
                                       │  IN_REVIEW   │◄────────┘
                                       │ (reviewers)  │
                                       └──────┬───────┘
                          all reviews in      │
                                       ┌──────▼───────┐
                                       │  DECISION    │ (manager collates → decides)
                                       └──┬───┬───┬───┘
                     accept │    minor/major revision │        │ reject
                            ▼                          ▼        ▼
                   ┌────────────────┐        ┌───────────────┐  ┌──────────┐
                   │ COPYRIGHT_     │        │  REVISION_    │  │ REJECTED │ (terminal)
                   │ PENDING        │        │  REQUESTED    │  └──────────┘
                   └───────┬────────┘        └──────┬────────┘
             author signs  │                        │ author resubmits (new version)
             & submits     ▼                        ▼
                   ┌────────────────┐        ┌───────────────┐
                   │ IN_PRODUCTION  │        │  RESUBMITTED  │──► QUALITY_CHECK / IN_REVIEW
                   │ (typeset, DOI) │        └───────────────┘
                   └───────┬────────┘
                           ▼
                   ┌────────────────┐        (any non-terminal state)
                   │   PUBLISHED    │        ─────► WITHDRAWN (author, terminal)
                   └────────────────┘
```

**Transition ownership** (who may trigger each — enforced server-side):

| From → To | Actor |
|---|---|
| DRAFT → SUBMITTED | Author |
| SUBMITTED → QUALITY_CHECK / IN_REVIEW / desk-REJECTED | Manager |
| QUALITY_CHECK → IN_REVIEW / REVISION_REQUESTED | Manager (on Quality Team result) |
| IN_REVIEW → DECISION | Manager (when reviews complete) |
| DECISION → COPYRIGHT_PENDING / REVISION_REQUESTED / REJECTED | Manager |
| REVISION_REQUESTED → RESUBMITTED | Author (uploads new version) |
| RESUBMITTED → QUALITY_CHECK / IN_REVIEW | Manager |
| COPYRIGHT_PENDING → IN_PRODUCTION | Manager (after author submits copyright) |
| IN_PRODUCTION → PUBLISHED | Manager |
| any non-terminal → WITHDRAWN | Author |

Every transition writes to the **activity timeline** (§4, `activity_log`).

### 3.3 The mediated-communication model (the differentiator)

**Invariants — the system must guarantee these, in code, at the data layer:**

- **INV-1 — Spokes address the hub only.** A message authored by an Author,
  Reviewer, or Quality user has its recipient *forced* to the manuscript's
  assigned Journal Manager. Recipient is **not** user-selectable for spokes.
- **INV-2 — Hub addresses spokes.** Only a Manager may send to a specific
  participant of a manuscript they manage.
- **INV-3 — No spoke→spoke path exists.** There is no API/route/query that
  inserts a message from one spoke addressed to another spoke. Cross-spoke
  information moves only via a manager-authored **relay** (a new message that
  *references* a source but is authored by the manager).
- **INV-4 — Identity firewall (blind review, §1.3).** When any manuscript,
  message, review, or file is rendered to a spoke, all other participants'
  identities are replaced by stable role-aliases ("Author", "Reviewer 1",
  "Reviewer 2", "Quality Reviewer"). The **author is always blind** (never sees
  reviewer/quality identities). Under **double-blind**, the author's own identity
  (name, email, ORCID, affiliation) is *also* stripped from the copy shown to
  reviewers/quality. Only the Manager and Admin ever see real identities.
- **INV-5 — Everything is audited.** Every message, relay, decision, assignment,
  transition, upload, and download is appended to an immutable log with actor,
  timestamp, and (for relays) the source→relayed link.

**Relay flow (author asks reviewers a question):**

```
Author ──msg──► Manager        (INV-1: recipient forced = Manager)
                  │
                  │ Manager reviews, optionally edits/anonymizes
                  ▼
              relay msg ──► Reviewer #1   (INV-2: Manager-authored; INV-3: new message)
                        └─► Reviewer #2   (audit links relay → source, INV-5)
```

**Enforcement location:** a single module — proposed `workflow/comms.py` — exposes
`send_message(actor, manuscript, body, attachments)` and
`relay_message(manager, source_msg, recipients, edited_body)`. **No UI or route
composes SQL directly.** UI never chooses arbitrary recipients for spokes. A unit
test asserts that a spoke cannot, by any code path, create a message addressed to
another spoke.

---

## 4. Data model (new tables — dual SQLite/Postgres like `auth.py`)

> Sketch, not final DDL. Reuse `auth.py`'s `_ensure_schema` / `_ensure_schema_pg`
> pattern and idempotent `ALTER … ADD COLUMN`.

```
users                 (EXISTING — extend role enum)
  role  ∈ {author, reviewer, quality, manager, editor?, admin, superadmin}

manuscripts
  id, code (human ref e.g. JMS-2026-0042), title, abstract,
  author_id (submitter), manager_id (assigned hub), status,
  double_blind BOOL DEFAULT true,   -- house default = double-blind (§1.3)
  current_version_id, created_at, updated_at

manuscript_versions
  id, manuscript_id, version_no, file_path, kind (submission|revision),
  redline_path, jats_path, report_path, ai_review_path, plagiarism_path,
  submitted_by, submitted_at, notes

manuscript_authors            -- co-authors / metadata for JATS + copyright
  id, manuscript_id, name, email, orcid, affiliation, is_corresponding, order_no

assignments                   -- manager assigns reviewers & quality
  id, manuscript_id, version_id, assignee_id, kind (reviewer|quality),
  alias (e.g. "Reviewer 1"), status (invited|accepted|declined|submitted),
  due_at, assigned_by (manager), assigned_at

reviews
  id, assignment_id, manuscript_id, version_id, recommendation
  (accept|minor|major|reject), comments_to_manager, confidential_notes,
  attachment_path, ai_assisted BOOL, submitted_at

quality_checks
  id, assignment_id, manuscript_id, version_id, checklist_json (pass/fail items),
  overall (pass|fail|conditional), notes, originality_score, submitted_at

decisions
  id, manuscript_id, version_id, decision (accept|minor|major|reject),
  decision_letter, decided_by (manager), decided_at

messages                      -- mediated comms; INV-1..INV-3 enforced here
  id, manuscript_id, thread_id, sender_id, recipient_id, body,
  is_relay BOOL, relayed_from_message_id NULLABLE, visibility, created_at,
  read_at

message_attachments
  id, message_id, file_path, filename

copyright_submissions
  id, manuscript_id, form_type (CTA|license|ICMJE), file_path,
  signed_by, status (pending|submitted|verified|rejected), submitted_at,
  verified_by (manager), verified_at

activity_log                  -- the author-visible "track record" / timeline
  id, manuscript_id, actor_id, actor_role_alias, action, detail_json,
  visible_to_author BOOL, created_at

audit_log                     -- immutable governance trail (superset)
  id, ts, user_id, action, entity_type, entity_id, detail

notifications
  id, user_id, manuscript_id, kind, body, read_at, created_at
```

**Reuse:** re-point `process_logs` outputs and the `jobs` queue at a
`manuscript_versions.id` instead of standalone files.

---

## 5. Phased delivery plan

Each phase lists **Goal · Scope · Data · Acceptance criteria (the "foolproof"
gate) · Depends · Risk · Effort.**

### Phase 0 — Groundwork & role model · **M**
- **Goal:** the 4 editorial roles + identity plumbing exist before any workflow.
- **Scope:** extend `users.role` enum (`author|reviewer|quality|manager` +
  keep `admin|superadmin`); default new signups → `author`; seed first
  `manager`/`admin`. Role-based route/tab gating in `app.py`. Central
  `require_role()` helper. Admin panel: list users, set roles.
- **Data:** `users.role` migration; `audit_log` table + `log_audit()` helper.
- **Acceptance:** a user with role X cannot load any page/action outside their
  RBAC row (§3.1), verified by tests; role changes are audited.
- **Depends:** none. **Risk:** low (additive to `auth.py`).

### Phase 1 — Manuscript object & author submission + tracking · **L**
- **Goal:** turn "process a file" into "submit & track a manuscript."
- **Scope:** `manuscripts` + `manuscript_versions` + `manuscript_authors`;
  submission form (title, abstract, authors, file, cover letter);
  **Author dashboard** — my submissions, status badge, **activity timeline**
  (the track record), withdraw. Human-readable manuscript `code`.
- **Data:** the three tables above + `activity_log`.
- **Acceptance:** an author submits, sees status = SUBMITTED and a timeline
  entry; cannot see anyone else's manuscripts; withdraw works and is audited.
- **Depends:** Phase 0. **Risk:** medium (largest data-model change).

### Phase 2 — Journal Manager hub & assignment engine · **L**
- **Goal:** the coordinator can drive a manuscript through the state machine.
- **Scope:** **Manager dashboard** — inbox of submissions, screen/desk-reject,
  assign reviewers & quality (`assignments`, with aliases), set due dates,
  advance state. Server-enforced transition ownership (§3.2). Reuse `jobs`
  queue to auto-run copyedit/originality on submission as a manager aid.
- **Data:** `assignments`, `decisions` (skeleton), state-transition guard.
- **Acceptance:** only a Manager can assign/transition; illegal transitions are
  rejected server-side and audited; assignment creates anonymized aliases.
- **Depends:** Phase 1. **Risk:** medium.

### Phase 3 — Mediated communication system (hub-and-spoke) · **L** ⭐
- **Goal:** enforce "no direct communication" in the data layer — the signature
  feature.
- **Scope:** `messages` + relay model; `comms.py` with `send_message()` /
  `relay_message()`; **identity firewall** rendering (aliases for spokes);
  per-manuscript threaded inbox for each role; manager relay UI (pick source →
  edit/anonymize → forward to chosen participants).
- **Data:** `messages`, `message_attachments`.
- **Acceptance (hard gates):**
  - INV-1..INV-5 all covered by automated tests.
  - **No code path** lets a spoke create a message addressed to another spoke
    (asserted by test).
  - A reviewer viewing a manuscript sees `Author`/`Reviewer 2`, never real
    names; a manager sees real names.
  - Every relay stores `relayed_from_message_id` and appears in the audit.
- **Depends:** Phases 0–2. **Risk:** medium-high (this is the correctness core;
  invest in tests). ⭐ **This phase is the product's differentiator.**

### Phase 4 — Reviewer workflow · **M**
- **Goal:** referees do their job through the hub.
- **Scope:** **Reviewer dashboard** — assigned (anonymized) manuscripts, accept/
  decline, submit review (recommendation + comments-to-manager + confidential
  notes + file). **Reuse the AI reviewer** (`generate_ai_review`) as an editable
  *draft* the human reviewer adjusts — never auto-submitted.
- **Data:** `reviews`.
- **Acceptance:** reviewer sees only assigned + anonymized manuscripts; on
  submit, manager is notified and can collate; author never sees reviewer id.
- **Depends:** Phases 2–3. **Risk:** low-medium.

### Phase 5 — Quality Team workflow · **M**
- **Goal:** a gated quality check with a real checklist.
- **Scope:** **Quality dashboard**; a configurable checklist (house-rule
  compliance, references, figures/tables, metadata completeness, ethics,
  **originality/plagiarism** via existing scan, JATS-readiness, and — for
  double-blind (§1.3) — **blinding compliance**: verify the manuscript file has no
  author-identifying front matter before it enters review). Pass/fail/conditional
  with notes back to manager. Quality is a state gate before or after review
  (configurable per journal).
- **Data:** `quality_checks`.
- **Acceptance:** quality result routes back to the manager only; a "fail"
  can push the manuscript to REVISION_REQUESTED via the manager; results audited.
- **Depends:** Phases 2–3; leverages `editor.py` originality + house rules.
- **Risk:** low-medium.

### Phase 6 — Decisions, revisions & resubmission loop · **M**
- **Goal:** close the review loop with real editorial decisions.
- **Scope:** manager **collation** view (all reviews + quality side by side);
  record decision + **decision letter** (AI-drafted, manager-edited); trigger
  REVISION_REQUESTED; author **resubmission** creates a new version and
  re-enters the pipeline; diff/track prior version.
- **Data:** `decisions`; version linkage for resubmissions.
- **Acceptance:** decision letter reaches author (via relay), never exposing
  reviewer identity; resubmission is a new version linked to the original;
  full loop Submitted→Revision→Resubmitted→Decision works and is audited.
- **Depends:** Phases 3–5. **Risk:** medium.

### Phase 7 — Copyright / license & production/publish · **L**
- **Goal:** accepted → copyright → produced → published.
- **Scope:** **Copyright submission** step (author uploads/signs CTA or license,
  e.g. ICMJE/CC-BY; manager verifies); `copyright_submissions`. Then production:
  extend existing **JATS export**, add **Crossref DOI deposit** (today we only
  *validate* DOIs), galley/PDF handoff, publication metadata (pub date, license,
  funding, ORCID), mark PUBLISHED with a public record.
- **Data:** `copyright_submissions`; manuscript publication fields.
- **Acceptance:** cannot enter production without a verified copyright record;
  DOI is deposited & stored; published manuscript has complete JATS metadata.
- **Depends:** Phase 6 + existing JATS. **Risk:** medium (external Crossref API).

### Phase 8 — Notifications, tracking & reporting · **M**
- **Goal:** everyone stays informed without direct contact.
- **Scope:** in-app + email notifications (assignment, decision, message,
  due-date, status change) routed per RBAC; author-facing **track record**
  timeline polished; manager **turnaround/SLA reporting**, reviewer load,
  per-journal analytics (extend `analytics.db`).
- **Data:** `notifications`.
- **Acceptance:** each role receives only role-appropriate notifications; author
  timeline reflects every visible-to-author event; manager sees SLA metrics.
- **Depends:** Phases 1–7. **Risk:** low-medium.

### Phase 9 — Confidentiality, governance & ops hardening · **L**
- **Goal:** make it safe and reliable for a real publisher.
- **Scope:** **confidential LLM mode** (self-hosted/no-retention only — extend
  existing custom/OpenAI-compatible path + `LLM_CONFIG_LOCKED`); ensure logs
  never store manuscript body; **encryption at rest** option; **retention TTL**
  + cleanup job; per-user/role **quotas & cost caps**; background **job queue**
  hardening (already have `jobs`); **observability** (structured logs, Sentry);
  **backups**; end-to-end test suite for the whole workflow.
- **Acceptance:** confidential mode refuses 3rd-party providers; retention purge
  runs; an end-to-end test drives a manuscript submit→publish across all roles.
- **Depends:** everything. **Risk:** medium (infra).

---

## 6. MVP cut (ship the core loop first)

**Goal of MVP:** one manuscript, one manager, one author, one reviewer, one
quality reviewer — full mediated loop, minus production polish.

Ship **Phases 0 → 1 → 2 → 3 → 4 → 5 → 6** (roles, manuscript, hub, mediated
comms, reviewer, quality, decision/resubmission). Defer **7 (copyright/
production)**, **8 (notifications/reporting)**, **9 (governance/ops)** to fast-
follow. This delivers the defining behavior — *tracked manuscript with all
communication routed through the Journal Manager* — as early as possible.

Rough MVP effort: ~**6–8 weeks** single engineer (Phases 0–6). Full platform
incl. 7–9: add ~**4–6 weeks**.

---

## 7. Cross-cutting concerns

### 7.1 Security & access
- RBAC enforced **server-side** in a single guard layer, not per-widget in
  Streamlit. Every data-access function takes an `actor` and filters by it.
- Identity firewall (INV-4) applied at the **serialization boundary**, so no view
  can accidentally leak a name.

### 7.2 Audit & immutability
- `audit_log` is append-only; no update/delete in app code. Governance can
  reconstruct the full history of any manuscript and every relayed message.

### 7.3 Confidentiality
- Unpublished manuscripts are sensitive. Confidential mode restricts LLM calls to
  self-hosted/no-retention endpoints; body text is never written to logs.

### 7.4 Notifications without contact
- Because spokes can't reach each other, notifications are the "presence" signal:
  "your manuscript moved to Under Review," "a message from the Journal Manager,"
  etc. — never revealing another spoke's identity.

### 7.5 Platform note (honest)
- Streamlit is fine through MVP but is a real constraint for a multi-tenant,
  role-scoped, notification-driven app. Budget a possible re-platform of the UI
  layer to **FastAPI + a proper SPA** after MVP if scale/UX demands it. The
  data/enforcement layer (`workflow/*`, `comms.py`) is framework-agnostic and
  survives such a move — build it independent of Streamlit from day one.

---

## 8. Testing strategy (what makes it "foolproof")

- **Invariant tests (highest priority):** INV-1..INV-5 each get dedicated tests;
  the "spoke cannot address a spoke by any path" test is a merge gate.
- **RBAC matrix tests:** table-driven test that asserts every cell of §3.1.
- **State-machine tests:** every legal transition works with the right actor;
  every illegal transition is rejected and audited.
- **End-to-end workflow test:** scripted submit → screen → quality → assign →
  review → decide → revise → resubmit → accept → copyright → publish, asserting
  identity firewall and audit completeness at each hop.
- Extend existing `test_*.py` suite; keep the AI engine's current unit tests.

---

## 9. Assumptions & open decisions (need your confirmation)

1. **Editor vs Reviewer vs Manager.** Assumed: *Journal Manager = handling
   editor/coordinator*; *Editor/Reviewer = referee*. If you want a **separate
   Editor** role (assigns reviewers, recommends; Manager only coordinates
   comms/logistics), add it to the role enum and split Phase 2's decision rights.
2. **Blinding — CONFIRMED: double-blind** (§1.3), house default
   (`double_blind = true`). Author identity is masked from reviewers/quality and
   reviewers are masked from the author; only the Manager sees both. Single-blind
   remains available as a per-manuscript override. *(Resolved — no action.)*
3. **Multiple journals / tenancy.** One publication house = one journal, or
   **multiple journals** each with its own manager/config? (Affects a `journals`
   table + scoping.) Assumed single for MVP, multi-journal in Phase 8+.
4. **Copyright form type.** Which agreement(s) — Copyright Transfer Agreement,
   CC-BY license, ICMJE forms? Determines the copyright step's fields.
5. **Email delivery.** In-app only for MVP, or email from the start (SMTP/
   provider)? Affects Phase 8 timing.
6. **Payments / APCs.** Any article-processing-charge / invoicing step? Not in
   this roadmap — flag if needed (adds a billing phase).
7. **Manager scaling.** One manager for all, or many managers each owning a
   queue? Schema supports many (`manuscripts.manager_id`); confirm assignment
   policy (round-robin? by subject?).

---

## 10. Sequencing at a glance

```
Phase 0 Roles ─► 1 Manuscript ─► 2 Manager/Assign ─► 3 Mediated Comms ⭐
                                                          │
                              ┌───────────────┬───────────┴───────────┐
                              ▼               ▼                       ▼
                         4 Reviewer      5 Quality             (identity firewall
                              └──────┬────────┘                  used by all three)
                                     ▼
                              6 Decisions/Resubmit  ──►  7 Copyright/Production
                                     │                            │
                                     └──────────────┬─────────────┘
                                                    ▼
                                     8 Notifications/Reporting
                                                    ▼
                                     9 Confidentiality/Ops hardening
```

**Recommended order:** 0 → 1 → 2 → 3 → 4 → 5 → 6 (**MVP**) → 7 → 8 → 9.
Phase 3 (mediated communication) is the make-or-break correctness core — plan the
most test effort there.

---

*Prepared as a planning artifact. Nothing here changes application behavior until
the corresponding phase is implemented. Build the `workflow/` + `comms.py`
enforcement layer framework-agnostic so it survives a future UI re-platform.*
