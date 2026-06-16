# Deploying Manuscript Editor Pro on Coolify

This is the authoritative, production-hardened deployment guide. Run through
[LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) alongside it.

[Coolify](https://coolify.io) is a self-hosted PaaS. This guide assumes you
already have a running Coolify instance with a git account connected.

---

## Overview

```
Internet ──HTTPS──> Coolify reverse proxy ──:8501──> app container ──> Postgres
                    (Let's Encrypt)                   (Dockerfile)      (Coolify DB)
                                                            │
                                                       /data volume
                                                  (SQLite fallback, redlines,
                                                   generated embeddings)
```

- The app is built from the repo `Dockerfile` (multi-stage, runs as non-root,
  has a healthcheck).
- The image already sets safe production defaults: `LLM_CONFIG_LOCKED=1`,
  `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none`, `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=50`.
- Postgres is the production database. Without `DATABASE_URL` the app falls back
  to a SQLite file under `/data` — fine for a quick demo, **not** for production.

---

## 1. Create a Postgres service

1. **+ New Resource → Database → PostgreSQL 16**.
2. Name it `manuscript-db`. Keep the credentials Coolify generates.
3. Wait for the healthcheck to go green.
4. Copy the **Internal Connection URL** — it looks like
   `postgresql://user:pass@manuscript-db:5432/manuscript`. You'll use it as
   `DATABASE_URL`. (The schema is created automatically on first connection.)

## 2. Create the application

1. **+ New Resource → Application → Public/Private Repository**.
2. Choose the connected GitHub account, then `celnetamit/journal-manager`.
   Branch: `main`.
3. **Build Pack: Dockerfile** (auto-detected at repo root).
4. **Port: `8501`** (the Dockerfile `EXPOSE`s it).

## 3. Configure environment variables

Application → **Environment Variables**. Add:

| Key                       | Value                                              | Secret? |
|---------------------------|----------------------------------------------------|:-------:|
| `GEMINI_API_KEY`          | your Gemini API key (or use `LLM_API_KEY`)         |   ✅    |
| `DATABASE_URL`            | the Postgres internal URL from step 1              |   ✅    |
| `DATA_DIR`                | `/data`                                            |         |
| `OUTPUT_DIR`              | `/data/outbound`                                   |         |
| `LLM_CONFIG_LOCKED`       | `1` (image default — keep it on in production)     |         |
| `LOGIN_MAX_ATTEMPTS`      | `10` (failed logins before lockout; `0` disables)  |         |
| `LOGIN_LOCKOUT_MINUTES`   | `15` (lockout window)                              |         |
| `LOGIN_TOKEN_TTL_DAYS`    | `30` ("remember me" lifetime; `0` = never expires) |         |
| `GEMINI_TEXT_MODEL`       | `gemini-2.5-pro` (optional)                        |         |
| `GEMINI_EMBED_MODEL`      | `text-embedding-004` (optional)                    |         |

> Mark `GEMINI_API_KEY` and `DATABASE_URL` as **Secret** so they're stored
> encrypted and kept out of logs.

To use a different provider (e.g. OpenRouter), set `LLM_PROVIDER`, `LLM_API_KEY`,
and `LLM_BASE_URL` instead — see the env table in [README.md](README.md#environment-variables).

With `LLM_CONFIG_LOCKED=1`, the in-app sidebar is **read-only**: users see the
configured provider/model but cannot change or overwrite the shared key.

## 4. Add a persistent volume

Redlines, the SQLite fallback, and generated embeddings must survive restarts.

1. Application → **Storages** → **+ Add Storage**.
2. **Mount path:** `/data`. Leave the source blank to let Coolify create a named
   volume (e.g. `manuscript_data`).
3. Save.

## 5. Attach a domain (HTTPS)

1. **Domains** tab → add your domain (e.g. `manuscript.example.com`) and point
   its DNS A record at the Coolify host.
2. Coolify issues a Let's Encrypt certificate automatically and forwards
   `443 → 8501`. **Do not expose port 8501 directly** — always go through the
   proxy so traffic (including auth cookies/tokens) is TLS-encrypted.

## 6. Deploy

1. **Deployments** tab → **Deploy**.
2. Watch the build logs — the image is built, not pulled, so the first deploy
   takes a couple of minutes.
3. Once **Running**, open the domain. You should see the login page over HTTPS.

## 7. First run

1. Register the first account from the **Register** tab. There is no admin
   bootstrap — the first registration is a normal user. (See "Limiting who can
   register" before going public.)
2. **(Optional) Pre-built embeddings:** journal recommendations work best with a
   `journals_embedded.json` matching your provider/model. The repo ships one for
   the Gemini defaults. For a different provider, rebuild it once and place it on
   the volume:
   ```bash
   # In Coolify's Terminal tab on the running container:
   GEMINI_API_KEY=... python embed_journals.py
   ```
   Point `JOURNALS_EMBEDDED_FILE` at the result if you store it outside the repo
   path. If embeddings are missing the app degrades gracefully rather than crashing.

## 8. Post-deploy verification

From Coolify's **Terminal** tab on the running container:

```bash
python -c "import auth; auth.init_auth(); print('db ok')"   # schema reachable
curl -s http://localhost:8501/_stcore/health                # -> {"status":"ok"}
```

Then, from a browser, confirm the [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md)
end-to-end items: register → login → upload a real `.docx` → process → download
the redline → logout.

---

## Security hardening (do before public launch)

- **Rotate the API key.** The repo's local `config.json` holds a live key for dev.
  Rotate it and supply production keys via env vars only. Never deploy by copying
  the working directory — only the Dockerfile path is safe (it `.dockerignore`s
  `config.json`).
- **Keep `LLM_CONFIG_LOCKED=1`.** Otherwise any logged-in user can overwrite the
  shared provider/key from the sidebar and spend your budget.
- **Limiting who can register.** Registration is open by default. Because all
  users share one server-side API key, open signup is a cost-abuse vector. Options:
  - Put Coolify behind an auth proxy / Cloudflare Access for a closed beta.
  - Deploy on a private network / IP allowlist.
  - Register the intended users yourself, then keep the URL unadvertised.
  (There is no built-in invite system yet — gate it at the edge.)
- **Add IP-level rate limiting / WAF.** The app throttles failed logins
  *per username* (`LOGIN_MAX_ATTEMPTS` within `LOGIN_LOCKOUT_MINUTES`), but does
  not stop volumetric or distributed abuse. Front it with Cloudflare or an nginx
  `limit_req` rule for request throttling.
- **Secrets handling.** Mark `GEMINI_API_KEY`/`DATABASE_URL` as Secret; tracebacks
  are already hidden in the browser (`STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none`).

---

## Updating

Push to `main`. With **Auto Deploy** enabled, Coolify detects the new commit and
rebuilds. The `/data` volume and the Postgres service are preserved across deploys.

## Rollback

Coolify keeps previous deployments. Use **Deployments → (previous build) →
Rollback** to revert the image. Database schema changes in this app are additive
(`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`), so rolling the image
back does not require a DB migration.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Login page never loads, healthcheck red | App can't reach Postgres — recheck `DATABASE_URL` (use the **internal** URL, not the public one). |
| "Invalid credentials" for a known-good user | Account is locked out after repeated failures — wait `LOGIN_LOCKOUT_MINUTES` or raise `LOGIN_MAX_ATTEMPTS`. |
| Redlines/history empty after restart | The `/data` volume isn't mounted — recheck Storages (step 4). |
| Sidebar won't let you change the model | Expected with `LLM_CONFIG_LOCKED=1`; change models via env vars and redeploy. |
| Journal recommendations look weak | Embeddings don't match the active provider/model — rebuild `journals_embedded.json` (step 7). |
| Upload rejected as too large | Files are capped at 50 MB (`STREAMLIT_SERVER_MAX_UPLOAD_SIZE`); raise it if needed. |
