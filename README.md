# Manuscript Editor Pro

AI-powered scientific copyediting and journal-recommendation platform.
Upload a `.docx` manuscript and get back a **redline Word document with
native Track Changes**, journal recommendations, a cover letter, and
polished titles — driven by your selected LLM provider.

---

## Features

- **Word-native redline output** — true `w:ins` / `w:del` track changes,
  not comments.
- **Style-aware copyediting** — CMOS, APA, MLA, IEEE.
- **Publisher / house rules** — built-in reference, heading, and in-text
  citation rules that are shown in the UI, toggleable per user, and saved
  across sessions; plus your own free-form rules. Includes a deterministic
  6-author-limit enforcement pass.
- **Live Crossref DOI validation** for bibliography entries.
- **Auto-numbered citations** + bibliography re-sort.
- **Semantic journal recommendations** (with a per-journal "why recommended"
  rationale) via the selected embedding model.
- **AI peer reviewer** — an expert referee report (strengths, concerns, and
  an accept/revise/reject recommendation) generated in parallel with the
  copyedit pass.
- **JATS/XML production export** — publisher-ready JATS Journal Publishing XML
  with structured authors, references, figures/tables, in-text citation
  linking, optional article metadata (DOI, pub-date, license, funding), and a
  structural validity check.
- **Cover letter generation** for the top recommended journal.
- **Title & abstract polish** suggestions.
- **Downloadable reports** — editorial review, AI peer review, and journal
  recommendations as `.docx`, plus the JATS `.xml`.
- **Per-user history** with re-downloadable redline, reports, and JATS files.
- **Resilient LLM calls** — a shared concurrency cap and 429 exponential
  backoff across the copyedit pool and the AI reviewer.
- **Multi-user authentication** with bcrypt password hashing.

---

## Quick start (local Docker)

```bash
git clone https://github.com/celnetamit/journal-manager.git
cd journal-manager
cp config.example.json config.json          # or set GEMINI_API_KEY below
echo "GEMINI_API_KEY=AIza..." > .env
docker compose up --build
```

Open <http://localhost:8501>. Postgres runs on `localhost:5432`
(`manuscript:manuscript/manuscript`). All app data (DB, redline files,
embeddings) is persisted in the named volume `app_data`.

In the app sidebar you can choose the LLM provider and set the API key,
base URL, text model, and embedding model. Gemini remains the default,
but OpenRouter and custom OpenAI-compatible endpoints are supported.

OpenRouter uses its own OpenAI-compatible endpoint
(`https://openrouter.ai/api/v1`) and OpenRouter model IDs. The sidebar
prefills those values so you do not need to reuse a stale local URL
when you switch providers.

The login form also has a `Remember me on this device` option. When
enabled, the app stores an opaque login token in a browser cookie so
refreshing the page keeps you signed in. Logging out clears that cookie.

Local config resolution is `CONFIG_FILE` first, then `./config.json`,
then `./data/config.json`. Docker/Coolify usually use `/data/config.json`
through the mounted volume.

To re-build the journal embeddings (only needed if `journals.json` changes):

```bash
docker compose run --rm app python embed_journals.py
```

---

## Local development (no Docker)

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=AIza...          # or put it in config.json
export DATABASE_URL=postgresql://...   # optional, defaults to SQLite
streamlit run app.py
```

---

## Environment variables

| Variable                | Default                       | Notes                                                    |
|-------------------------|-------------------------------|----------------------------------------------------------|
| `GEMINI_API_KEY`        | *(empty)*                     | **Required** for Gemini if `LLM_API_KEY` is not set.     |
| `LLM_PROVIDER`          | `gemini`                      | Optional if you set provider in the sidebar/config file. |
| `LLM_API_KEY`           | *(empty)*                     | Generic API key override for supported providers.        |
| `LLM_TEXT_MODEL`        | `gemini-2.5-pro`              | Optional default text model.                             |
| `LLM_EMBED_MODEL`       | `text-embedding-004`          | Optional default embedding model.                        |
| `LLM_BASE_URL`          | *(empty)* | Base URL for OpenAI-compatible/custom endpoints. OpenRouter keeps its own default endpoint. |
| `DATABASE_URL`          | `sqlite:///./data/analytics.db` | Set to your Postgres URL in production.                |
| `DATA_DIR`              | `./data`                      | Where analytics DB and generated embeddings live.       |
| `OUTPUT_DIR`            | `$DATA_DIR/outbound`          | Where generated redline/report/JATS files are written.   |
| `OUTPUT_RETENTION_DAYS` | `30`                          | Age (days) after which generated output files are purged on startup. `0` keeps them forever. |
| `LLM_MAX_CONCURRENCY`   | `3`                           | Max concurrent LLM calls shared across the copyedit pool and the AI reviewer. |
| `LLM_RATE_LIMIT_RETRIES`| `4`                           | Retries on a `429 Too Many Requests` before giving up.   |
| `LLM_RATE_LIMIT_BASE_DELAY` | `2.0`                     | Initial backoff (seconds) on a 429; doubles each retry, honoring `Retry-After`. |
| `JATS_COPYRIGHT_HOLDER` | *(empty)*                     | Publisher/copyright holder stamped into JATS `<permissions>`. |
| `JATS_LICENSE_URL`      | *(empty)*                     | License URL for JATS `<license>`, e.g. a CC-BY link.     |
| `JATS_LICENSE_TEXT`     | *(empty)*                     | Human-readable license statement for JATS `<license-p>`. |
| `JOURNALS_FILE`         | `./journals.json`             | Source journals catalogue.                               |
| `JOURNALS_EMBEDDED_FILE`| `./journals_embedded.json`    | Pre-computed embeddings (build with `embed_journals.py`).|
| `GEMINI_TEXT_MODEL`     | `gemini-2.5-pro`              | Override the chat model.                                 |
| `GEMINI_EMBED_MODEL`    | `text-embedding-004`          | Override the embedding model.                            |
| `PORT`                  | `8501`                        | Streamlit listen port.                                   |
| `LLM_CONFIG_LOCKED`     | `0` (`1` in Docker image)     | When `1`, provider/key come from env only; the in-app sidebar is read-only and cannot overwrite the shared config. Recommended for public deployments. |
| `LOGIN_MAX_ATTEMPTS`    | `10`                          | Failed logins per username before a temporary lockout (`0` disables). |
| `LOGIN_LOCKOUT_MINUTES` | `15`                          | Sliding window over which failed logins are counted.     |
| `LOGIN_TOKEN_TTL_DAYS`  | `30`                          | Persistent "remember me" token lifetime (`0` = never expires). |
| `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS` | `none` (Docker image) | Keep tracebacks out of the browser in production.        |

> **Never commit `config.json`, `analytics.db`, or `journals_embedded.json`.**
> They are listed in `.gitignore`.

---

## Project layout

```
.
├── app.py                 # Streamlit entrypoint
├── config.py              # env-var + path resolution
├── auth.py                # bcrypt + Postgres/SQLite auth + analytics
├── editor.py              # docx + LLM pipeline
├── embed_journals.py      # CLI to (re)build journals_embedded.json
├── requirements.txt
├── Dockerfile             # production image
├── docker-compose.yml     # local-dev stack (app + Postgres)
├── .streamlit/config.toml # prod server settings
├── config.example.json    # template for local-only LLM settings
├── .gitignore
├── .dockerignore
├── journals.json          # source journal catalogue (tracked)
└── journals_embedded.json # generated; gitignored
```

---

## Coolify deployment

Coolify is a self-hosted PaaS. This guide assumes a running Coolify
instance and a connected git account.

### 1. Create a Postgres service

In Coolify:

1. **+ New Resource → Database → PostgreSQL 16**.
2. Name it `manuscript-db`. Use default credentials (Coolify generates them).
3. Wait for the healthcheck to go green.
4. Copy the **Internal Connection URL** — looks like
   `postgresql://user:pass@manuscript-db:5432/manuscript`.

### 2. Create the application

1. **+ New Resource → Application → Public/Private Repository**.
2. Pick the GitHub account connected to Coolify, then
   `celnetamit/journal-manager`. Branch: `main`.
3. **Build Pack: Dockerfile** (Coolify auto-detects the `Dockerfile`
   at repo root).
4. **Port: `8501`** (the Dockerfile already `EXPOSE 8501`).

### 3. Configure environment variables

In the application's **Environment Variables** tab, add:

| Key                       | Value                                                              |
|---------------------------|--------------------------------------------------------------------|
| `GEMINI_API_KEY`          | your Gemini API key from Google AI Studio                          |
| `DATABASE_URL`            | the Postgres internal URL from step 1                              |
| `DATA_DIR`                | `/data`                                                            |
| `OUTPUT_DIR`              | `/data/outbound`                                                   |
| `GEMINI_TEXT_MODEL`       | `gemini-2.5-pro` (optional)                                        |
| `GEMINI_EMBED_MODEL`      | `text-embedding-004` (optional)                                    |

> Mark `GEMINI_API_KEY` and `DATABASE_URL` as **Secret** so they're
> stored encrypted and not shown in logs.

### 4. Add a persistent volume

Redlines and any future data must survive container restarts.

1. Open the application → **Storages** tab.
2. **+ Add Storage**:
   - **Mount path:** `/data`
   - **Source path:** any host path (Coolify will create a named
     volume if you leave it blank, e.g. `manuscript_data`).
3. Save and redeploy.

### 5. Set the domain / port mapping

1. **Domains** tab → add your domain (e.g. `manuscript.example.com`).
2. Coolify will issue a Let's Encrypt certificate automatically.
3. Streamlit is served on port `8501`; Coolify's reverse proxy will
   forward `443 → 8501` for you.

### 6. Deploy

1. **Deployments** tab → **Deploy**.
2. Watch the build logs. The image is built from the `Dockerfile`,
   not pulled, so the first deploy will take a couple of minutes.
3. Once `Running`, click the domain. You should see the login page.
4. Create the first user account. (There's no admin bootstrap — the
   first registration is just a normal user.)

### 7. Post-deploy checks

```bash
# From Coolify's "Terminal" tab on the running container:
python -c "import auth; auth.init_auth(); print('db ok')"
curl -s http://localhost:8501/_stcore/health
# Should return: {"status":"ok"}
```

### 8. Updating

Push to `main`. Coolify auto-detects the new commit (if **Auto Deploy**
is enabled) and rebuilds. The `/data` volume is preserved.

---

## Security notes

- **API keys** are read from the `GEMINI_API_KEY` env var first,
  falling back to `config.json` for local dev. `.env`,
  `config.json`, `analytics.db`, and `journals_embedded.json` are all
  `.gitignore`d.
- **Passwords** are hashed with **bcrypt (rounds=12)**. Legacy
  unsalted-SHA-256 hashes from the original prototype are
  automatically upgraded on the user's next successful login.
- **Analytics tab** only shows daily aggregates — no per-user rows.
- **File uploads** are limited to 50 MB via `.streamlit/config.toml`.
- The container runs as a **non-root** user (`uid 1000`).
- XSRF protection is enabled (`enableXsrfProtection = true`).

### Public launch checklist

Use [LAUNCH_CHECKLIST.md](/home/itb09/.openclaw/workspace/manuscript_platform/LAUNCH_CHECKLIST.md) as the go/no-go gate before exposing the app publicly.

The current highest-priority items are:

1. Rotate any previously committed API keys and confirm there are no secrets left in git history.
2. Verify the app starts cleanly in the target runtime and that the optional cookie dependency does not block startup.
3. Put the app behind HTTPS and add upstream rate limiting if you will expose it beyond a small trusted group.
4. Complete one production-like end-to-end test with login, upload, processing, and download.

---

## Embedding the journal catalogue

The first time you deploy (or any time `journals.json` changes):

```bash
# Locally
GEMINI_API_KEY=... python embed_journals.py

# Or in Coolify: open a one-off terminal on the running container and run
# the same command. Then copy journals_embedded.json into the /data
# volume (or bake it into the image).
```

The `journals_embedded.json` is large (~12 MB) and gitignored, so it
must be generated per environment.

---

## License

Private — © Manuscript Editor Pro contributors.
