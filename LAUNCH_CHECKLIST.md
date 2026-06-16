# Public Launch Checklist

Use this as the go/no-go gate for a public release of Manuscript Editor Pro.
For step-by-step hosting instructions see [DEPLOY_COOLIFY.md](DEPLOY_COOLIFY.md).

## Blockers

- [ ] **Rotate the API key in local `config.json`** and any previously shared key,
      then confirm no secrets remain in git history. *(Owner action — the key is a
      live credential. It is gitignored and dockerignored, so it is not in git
      history or the image, but it must still be rotated before launch.)*
- [x] Confirm the app starts without optional dependencies missing.
      *(Verified: `import app` and the smoke tests pass without the cookie package.)*
- [x] Verify `streamlit run app.py` opens the login page in the target runtime.
      *(Verified locally: HTTP 200 on `/` and `/_stcore/health`.)*
- [ ] Verify the Docker image starts cleanly in Coolify or the intended host.
      *(Deployment step — see DEPLOY_COOLIFY.md §6.)*
- [ ] Verify the persistent volume is mounted at `/data` and survives restart.
      *(Deployment step — DEPLOY_COOLIFY.md §4.)*
- [ ] Verify the production database is Postgres and reachable from the app.
      *(Deployment step — set `DATABASE_URL`; DEPLOY_COOLIFY.md §1, §3.)*
- [ ] Confirm the login/register flow works end to end. *(Deployment smoke test.)*
- [ ] Confirm the upload -> process -> download flow works with a real `.docx` file.

## Production configuration (set in Coolify env vars)

- [ ] `LLM_CONFIG_LOCKED=1` — provider/API key come from env only; the in-app
      sidebar becomes read-only and cannot overwrite the shared config.
      *(The Docker image sets this by default.)*
- [ ] `GEMINI_API_KEY` (or `LLM_API_KEY`) set and marked **Secret**.
- [ ] `DATABASE_URL` set to the Postgres internal URL and marked **Secret**.
- [ ] `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` reviewed (defaults 10 / 15).
- [ ] `LOGIN_TOKEN_TTL_DAYS` reviewed (default 30).
- [ ] `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none` and
      `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=50` confirmed *(image defaults).*

## Security and abuse controls

- [ ] Put the app behind HTTPS. *(Coolify issues Let's Encrypt automatically once a
      domain is attached — DEPLOY_COOLIFY.md §5.)*
- [x] In-app login throttling (per-username lockout after repeated failures).
- [ ] Add upstream rate limiting / WAF for IP-level abuse (e.g. Cloudflare in front
      of Coolify). *(In-app throttle covers credential stuffing per username, not
      volumetric or distributed abuse.)*
- [x] Persistent login tokens expire (`LOGIN_TOKEN_TTL_DAYS`) and are revoked on logout.
- [x] Provider/API-key config cannot be changed by end users in production
      (`LLM_CONFIG_LOCKED`).
- [x] Tracebacks are hidden from the browser in production
      (`STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none`).
- [x] Cookies, auth tokens, and config files are not logged.
      *(Tokens are stored only as SHA-256 hashes; the key field is a password input.)*
- [x] `config.json`, `analytics.db`, and journal embeddings are ignored from git.
      *(Verified in `.gitignore`; also excluded from the image via `.dockerignore`.)*
- [x] File upload limited to `.docx` and capped at 50 MB
      (`STREAMLIT_SERVER_MAX_UPLOAD_SIZE`).
- [x] Only anonymized, aggregated analytics are visible in the Analytics tab
      (`fetch_global_analytics` returns per-day rollups, no per-user rows).
- [ ] Decide whether registration is open or invite-only. *(Registration is open by
      default — combined with a shared key, gate it for cost control. See
      DEPLOY_COOLIFY.md "Limiting who can register".)*

## Reliability

- [ ] Generate journal embeddings for the deployed provider/model combination.
- [ ] Smoke test Crossref lookups against the live network.
- [ ] Verify the journal recommendation fallback path does not crash if embeddings are missing.
- [ ] Verify the healthcheck endpoint returns OK after deployment.
- [x] Verify logout clears (revokes) the persistent login token. *(Verified in code:
      logout calls `auth.revoke_login_token`.)*

## Observability

- [ ] Confirm deployment logs are available in the platform.
- [ ] Confirm job failures are visible in the UI and captured in the database.
- [ ] Confirm the history tab shows downloadable redline artifacts.
- [x] At least one automated startup smoke test and core-config tests exist
      (`test_startup_smoke.py`, 12 tests).

## Launch decision

- [ ] All blockers above are green.
- [ ] At least one successful end-to-end manual test has been completed in the
      production-like environment.
- [ ] The launch owner has signed off that the current risk level is acceptable.

## Verified in this workspace

- [x] `python3 -c "import app"` succeeds without the optional cookie package installed.
- [x] `pytest -q` passes (12 tests).
- [x] `curl http://localhost:8501/_stcore/health` returned `ok` on a live local Streamlit process.
- [x] Login throttling and login-token expiry verified end to end against SQLite.
