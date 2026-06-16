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
- **Live Crossref DOI validation** for bibliography entries.
- **Auto-numbered citations** + bibliography re-sort.
- **Semantic journal recommendations** via the selected embedding model.
- **Cover letter generation** for the top recommended journal.
- **Title & abstract polish** suggestions.
- **Per-user history** with re-downloadable redline files.
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
| `OUTPUT_DIR`            | `$DATA_DIR/outbound`          | Where generated redline `.docx` files are written.       |
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

Full step-by-step instructions — Postgres, env vars, persistent volume,
HTTPS, hardening, and troubleshooting — live in
**[DEPLOY_COOLIFY.md](DEPLOY_COOLIFY.md)**.

In short: build from the repo `Dockerfile` (port `8501`), attach a PostgreSQL
service as `DATABASE_URL`, mount a persistent `/data` volume, set the
environment variables above (keep `LLM_CONFIG_LOCKED=1`), and attach a domain
so Coolify terminates HTTPS for you.

---

## Security notes

- **API keys** are read from the `GEMINI_API_KEY` env var first,
  falling back to `config.json` for local dev. `.env`,
  `config.json`, `analytics.db`, and `journals_embedded.json` are all
  `.gitignore`d.
- **Passwords** are hashed with **bcrypt (rounds=12)**. Legacy
  unsalted-SHA-256 hashes from the original prototype are
  automatically upgraded on the user's next successful login.
- **Login throttling**: failed logins are rate-limited per username
  (`LOGIN_MAX_ATTEMPTS` within `LOGIN_LOCKOUT_MINUTES`), and persistent
  "remember me" tokens expire after `LOGIN_TOKEN_TTL_DAYS` and are revoked
  on logout.
- **Locked config in production**: with `LLM_CONFIG_LOCKED=1` (the Docker
  image default) the provider/API key come from env vars only and the in-app
  sidebar is read-only, so users can't overwrite the shared key.
- **Analytics tab** only shows daily aggregates — no per-user rows.
- **File uploads** are limited to `.docx` and 50 MB. In the container this is
  enforced via `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (the `.streamlit/` dir is
  not shipped in the image); `.streamlit/config.toml` covers local dev.
- **Error details** are hidden from the browser in production
  (`STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none`).
- The container runs as a **non-root** user (`uid 1000`).
- XSRF protection is enabled (`enableXsrfProtection = true`).

### Public launch checklist

Use [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) as the go/no-go gate before
exposing the app publicly, and [DEPLOY_COOLIFY.md](DEPLOY_COOLIFY.md) for the
hosting steps.

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
