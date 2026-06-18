# Public Launch Checklist

Use this as the go/no-go gate for a public release of Manuscript Editor Pro.

## Blockers

- [ ] Rotate any previously committed API keys and the key currently present in the local `config.json`, then confirm no secrets remain in git history.
- [ ] Confirm the app starts without optional dependencies missing.
- [ ] Verify `streamlit run app.py` opens the login page in the target runtime.
- [ ] Verify the Docker image starts cleanly in Coolify or the intended host.
- [ ] Verify the persistent volume is mounted at `/data` and survives restart.
- [ ] Verify the production database is Postgres and reachable from the app.
- [ ] Confirm the login/register flow works end to end.
- [ ] Confirm the upload -> process -> download flow works with a real `.docx` file.

## Security And Abuse Controls

- [ ] Put the app behind HTTPS.
- [ ] Add rate limiting or an upstream proxy with request throttling.
- [ ] Confirm cookies, auth tokens, and config files are not logged.
- [ ] Confirm `config.json`, `analytics.db`, and journal embeddings are ignored from git.
- [ ] Review file upload limits and storage usage for abuse resistance.
- [ ] Confirm only anonymized analytics are visible in the Analytics tab.

## Reliability

- [ ] Generate journal embeddings for the deployed provider/model combination.
- [ ] Smoke test Crossref lookups against the live network.
- [ ] Verify the journal recommendation fallback path does not crash if embeddings are missing.
- [ ] Verify the healthcheck endpoint returns OK after deployment.
- [ ] Verify logout clears the persistent login token.

## Observability

- [ ] Confirm deployment logs are available in the platform.
- [ ] Confirm job failures are visible in the UI and captured in the database.
- [ ] Confirm the history tab shows downloadable redline artifacts.
- [ ] Add at least one automated smoke test for startup and one for core document processing.

## Launch Decision

- [ ] All blockers above are green.
- [ ] At least one successful end-to-end manual test has been completed in the production-like environment.
- [ ] The launch owner has signed off that the current risk level is acceptable.

## Verified In This Workspace

- [x] `python3 -c "import app"` succeeds without the optional cookie package installed.
- [x] `pytest -q` passes.
- [x] `curl http://localhost:8502/_stcore/health` returned `ok` on a live local Streamlit process.
