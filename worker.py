"""The job worker as its own process.

Until now the worker only existed inside the Streamlit app: `app.py` calls
`start_worker_once()` at module level, and Streamlit executes that script per browser
session, not at server boot. So after every deploy the queue stood still until somebody
opened the page — measured on 2026-09-04, three jobs queued 20 minutes after a restart
and none of them started, while `GET /` returned 200 the whole time.

That directly contradicts what the app tells the user when they submit: *"It runs in the
background — you can close this tab and come back."* For the only user of a quiet
instance, closing the tab is exactly when nothing happens.

Run alongside the app rather than inside it. The workers only poll the database and
claim jobs atomically (`claim_next_job`), so a second process is safe: it is the same
mechanism that already lets `JOB_WORKERS>1` run several jobs at once.
"""

from __future__ import annotations

import signal
import sys
import threading
import time

import pipeline

_stop = threading.Event()


def _shutdown(signum, _frame):
    print(f"[worker] received signal {signum}, stopping", flush=True)
    _stop.set()


def main() -> int:
    # Without these the container's stop signal is ignored and Docker waits out its
    # ten-second grace period on every deploy.
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    pipeline.start_worker_once()
    print("[worker] standalone worker process started", flush=True)
    while not _stop.is_set():
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
