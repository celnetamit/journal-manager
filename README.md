# Manuscript Editor Pro

AI-powered scientific copyediting and journal-recommendation platform.
Upload a `.docx` manuscript and get back a **redline Word document with
native Track Changes**, journal recommendations, a cover letter, and
polished titles — driven by Google Gemini.

---

## Features

- **Word-native redline output** — true `w:ins` / `w:del` track changes,
  not comments.
- **Style-aware copyediting** — CMOS, APA, MLA, IEEE.
- **Live Crossref DOI validation** for bibliography entries.
- **Auto-numbered citations** + bibliography re-sort.
- **Semantic journal recommendations** via Gemini embeddings.
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
| `GEMINI_API_KEY`        | *(empty)*                     | **Required.** Read by `config.py`.                       |
| `DATABASE_URL`          | `sqlite:///./data/analytics.db` | Set to your Postgres URL in production.                |
| `DATA_DIR`              | `./data`                      | Where `config.json`, analytics DB, and embeddings live.  |
| `OUTPUT_DIR`            | `$DATA_DIR/outbound`          | Where generated redline `.docx` files are written.       |
| `JOURNALS_FILE`         | `./journals.json`             | Source journals catalogue.                               |
| `JOURNALS_EMBEDDED_FILE`| `./journals_embedded.json`    | Pre-computed embeddings (build with `embed_journals.py`).|
| `GEMINI_TEXT_MODEL`     | `gemini-2.5-pro`              | Override the chat model.                                 |
| `GEMINI_EMBED_MODEL`    | `text-embedding-004`          | Override the embedding model.                            |
| `PORT`                  | `8501`                        | Streamlit listen port.                                   |

> **Never commit `config.json`, `analytics.db`, or `journals_embedded.json`.**
> They are listed in `.gitignore`.

---

## Project layout

```
.
├── app.py                 # Streamlit entrypoint
├── config.py              # env-var + path resolution
├── auth.py                # bcrypt + Postgres/SQLite auth + analytics
├── editor.py              # docx + Gemini pipeline
├── embed_journals.py      # CLI to (re)build journals_embedded.json
├── requirements.txt
├── Dockerfile             # production image
├── docker-compose.yml     # local-dev stack (app + Postgres)
├── .streamlit/config.toml # prod server settings
├── config.example.json    # template for local-only API key
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
  falling back to `config.json` for local dev. `config.json` is
  `.gitignore`d.
- **Passwords** are hashed with **bcrypt (rounds=12)**. Legacy
  unsalted-SHA-256 hashes from the original prototype are
  automatically upgraded on the user's next successful login.
- **Analytics tab** only shows daily aggregates — no per-user rows.
- **File uploads** are limited to 50 MB via `.streamlit/config.toml`.
- The container runs as a **non-root** user (`uid 1000`).
- XSRF protection is enabled (`enableXsrfProtection = true`).

### Things you should still do

1. **Rotate the Gemini key** that was previously committed to
   `config.json` before the first deploy.
2. Put the app behind **Coolify's automatic HTTPS** (default).
3. If you expose this beyond your team, add a real rate-limit
   proxy in front (Caddy / Traefik with `limit_req`).

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
