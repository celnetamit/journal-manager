# ce4 stage 3 — the copy editing options move to the platform

**Where this comes from.** The staging was Amit's: (1) the live diff, (2) ce4's job state
inside manuscript-ngine, (3) "uploads and settings move too, Streamlit becomes the
admin/debug console." Stages 1 and 2 are live. This is the plan for 3, written before any
of it is built so the parts that are decisions rather than code get decided first.

## What is true today

An editor on manuscript-ngine can send a manuscript, watch it being copy edited, answer
the review question, and read the result. What they **cannot** do is say *how* it should be
copy edited. Eight choices exist in ce4's own screen and none of them reaches the bridge:

| Choice | ce4's screen | What a bridge job gets today |
|---|---|---|
| Copyediting style | CMOS / APA / MLA / IEEE | always **CMOS** |
| Reference style | Vancouver / Harvard / APA / Chicago / IEEE | always **Vancouver** |
| Language | Auto / US / UK / Australian | **UK or US**, from the journal's spelling |
| Copy edit tables | on/off | always **on** |
| Auto-number & sort citations | on/off | always **on** |
| Crossref DOI validation | on/off | always **on** |
| House rules (11 groups) | tick any subset | always **all eleven** |
| Extra house rules | free text | always **none** |

Those defaults are not wrong — they are what STM Journals mostly wants. They are just not
*choosable*, and two of them are wrong often enough to matter: a law journal running
Vancouver numbering, and a manuscript whose references are Harvard coming back renumbered.

## What stage 3 does

**1. The options come from the platform, per journal, with a per-manuscript override.**

- A new settings group, `Copy editing defaults`, holds the eight values above. It is where
  the house answer lives: CMOS + Vancouver + auto language + all rules on.
- Each journal may override any of them (`Journal.copyedit_options`, a JSON field). A law
  journal sets Harvard once and never thinks about it again.
- The send form shows what will be used and offers **"Change for this manuscript"**, which
  expands the eight controls with the journal's values already filled in.
- The chosen set is stored on `ExternalCopyeditJob.options` and handed to ce4 at claim
  time, exactly like `variant` and `review_mode` are today.

*Why journal-level and not only per-manuscript:* the person sending a manuscript is rarely
the person who knows the journal's reference style. Asking them every time is how you get
whatever the default was, chosen by nobody.

**2. ce4 stops inventing defaults for bridge jobs.** `_options_for()` currently hardcodes
them. It will take what the platform sent and fall back to today's values only for fields
the platform did not send — so an older platform keeps working unchanged.

**3. Upload without a manuscript, from the platform.** The one thing ce4's screen can do
that the platform cannot: copy edit a loose file. A production editor with a Word document
that is not yet a submission has to open ce4, log in, and upload it there.

- A new page, **Copy editing → Send a file**, takes a `.docx`, the same options, and
  produces the same redline + report, with no manuscript record.
- It reuses the whole bridge: a job row with `manuscript = null`, which today is not
  allowed and becomes a two-line change on the model.
- The file and its result live on the job row and are downloadable from that page. They do
  **not** land in a manuscript's file list, because they belong to no manuscript.

**4. Streamlit becomes the admin console.** Once 1–3 are in, ce4's own screen keeps: the
rules editor, the LLM provider settings, the queue and its logs, the user admin. It loses
nothing — nobody's workflow breaks — but the editorial team never needs to open it.

## What is deliberately *not* in stage 3

- **The rules registry stays in ce4.** Eleven rule groups, each a block of prose the model
  is given. Editing them from the platform means a second editor for the same text and a
  migration to keep them in step; the rules change a few times a year and the person who
  changes them is technical.
- **No new engine work.** Stage 3 moves controls, it does not touch the pipeline.
- **The LLM settings stay in ce4.** They are a credential and a cost lever, not an
  editorial choice.

## Order of work

1. `copyedit_options` on the settings registry + on `Journal` (migration, admin screen).
2. Send form: show the resolved options, allow a per-manuscript override, store on the job.
3. Bridge: carry them in the claim payload; ce4 reads them with today's values as the
   fallback. Tests both sides, including a job sent by an older platform.
4. Loose-file page: `manuscript = null` jobs, upload, download, listing.
5. A note on ce4's screen saying where the editorial controls now live.

Steps 1–3 are the ones that change what the team can do; 4 is the one that lets ce4's
screen be retired for them. 5 is a paragraph.

## Open question for Amit

**Who may change a journal's copy editing defaults?** Production editors on that journal,
or only the portfolio administrator? The first is faster for the team; the second is how
every other journal-wide setting on the platform works today. My suggestion is the second,
because a reference style changed by one person silently changes every manuscript that
follows.
