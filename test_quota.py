"""The monthly usage quota.

Two things here are the whole point.

`test_a_failed_job_still_counts_against_the_quota` — a job that fails spends its
tokens, often more than one that succeeds, because a chunk that burns its budget
reasoning and returns nothing is a common failure on this platform. If the quota
counted only completed jobs, a user could run the API bill up indefinitely on work
that never counted.

`test_admins_are_never_capped` — the person who has to clear a stuck queue must not be
the person locked out by their own allowance.

The cap is in tokens, not money. Cost is not always reported by the provider, and a
limit that silently stops being enforced whenever a price is missing is not a limit.
"""

import os

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MONTHLY_TOKEN_CAP", raising=False)
    monkeypatch.delenv("MONTHLY_MANUSCRIPT_CAP", raising=False)
    import importlib
    import config
    import auth
    importlib.reload(config)
    importlib.reload(auth)
    return auth


def _user(auth, name="editor"):
    assert auth.register(name, "pw-long-enough")
    return auth.login(name, "pw-long-enough")


def _spend(auth, user_id, prompt=0, completion=0, cost=None):
    job_id = auth.create_job(user_id, "p.docx", "/tmp/p.docx", "{}")
    auth.record_job_usage(job_id, {
        "prompt_tokens": prompt, "completion_tokens": completion,
        "cached_tokens": 0, "calls": 1, "cost_usd": cost,
    })
    return job_id


def test_no_cap_configured_means_no_limit(db):
    _spend(db, 1, prompt=10_000_000)
    assert db.quota_check(1)["allowed"] is True


def test_cap_blocks_once_it_is_reached(db, monkeypatch):
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "1000")
    _spend(db, 1, prompt=600, completion=300)
    assert db.quota_check(1)["allowed"] is True, "900 of 1000 must still be allowed"
    _spend(db, 1, prompt=200)
    check = db.quota_check(1)
    assert check["allowed"] is False
    assert check["used"] == 1100 and check["cap"] == 1000


def test_the_refusal_names_the_numbers_and_when_it_resets(db, monkeypatch):
    """A refusal that just says no leaves the user with nothing to do about it."""
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "100")
    _spend(db, 1, prompt=500)
    message = db.quota_check(1)["message"]
    assert "500" in message and "100" in message
    assert "resets" in message.lower()
    assert "administrator" in message.lower()


def test_a_failed_job_still_counts_against_the_quota(db, monkeypatch):
    """Otherwise the quota is walked past by submitting work that fails."""
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "1000")
    job_id = db.create_job(1, "p.docx", "/tmp/p.docx", "{}")
    db.record_job_usage(job_id, {"prompt_tokens": 900, "completion_tokens": 400,
                                 "calls": 1, "cost_usd": 0.02})
    db.fail_job(job_id, "the model returned empty content")
    assert db.quota_check(1)["allowed"] is False


def test_usage_is_recorded_for_a_cancelled_job_too(db):
    """`complete_job` and `fail_job` guard on 'running' so a cancelled job is not
    resurrected. Usage must not be guarded that way — it was still spent."""
    job_id = db.create_job(1, "p.docx", "/tmp/p.docx", "{}")
    db.record_job_usage(job_id, {"prompt_tokens": 700, "calls": 3})
    assert db.get_job(job_id)["prompt_tokens"] == 700


def test_one_users_spending_does_not_touch_another(db, monkeypatch):
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "1000")
    _spend(db, 1, prompt=5000)
    assert db.quota_check(1)["allowed"] is False
    assert db.quota_check(2)["allowed"] is True


def test_a_per_user_cap_overrides_the_deployment_default(db, monkeypatch):
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "100")
    uid = _user(db)
    _spend(db, uid, prompt=500)
    assert db.quota_check(uid)["allowed"] is False
    db.set_token_cap(uid, 10_000)
    assert db.quota_check(uid)["allowed"] is True


def test_a_per_user_cap_of_zero_is_an_exemption_not_a_block(db, monkeypatch):
    """0 must read as 'no limit', the same as it does for the deployment default —
    not as 'this user may spend nothing'."""
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "100")
    uid = _user(db)
    _spend(db, uid, prompt=500)
    db.set_token_cap(uid, 0)
    assert db.quota_check(uid)["allowed"] is True


def test_clearing_a_per_user_cap_restores_the_default(db, monkeypatch):
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "100")
    uid = _user(db)
    _spend(db, uid, prompt=500)
    db.set_token_cap(uid, 10_000)
    db.set_token_cap(uid, None)
    assert db.quota_check(uid)["allowed"] is False


def test_admins_are_never_capped(db, monkeypatch):
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "10")
    uid = _user(db, "boss")
    db.set_user_role(uid, "admin")
    _spend(db, uid, prompt=99_999)
    assert db.quota_check(uid)["allowed"] is True
    assert db.token_cap_for(uid) == 0


def test_an_unpriced_month_still_enforces_the_cap(db, monkeypatch):
    """Tokens, not money. A provider that reports no cost must not disable the gate."""
    monkeypatch.setenv("MONTHLY_TOKEN_CAP", "1000")
    _spend(db, 1, prompt=2000, cost=None)
    assert db.month_usage(1)["cost_usd"] is None
    assert db.quota_check(1)["allowed"] is False


# --- the manuscript allowance ------------------------------------------------
#
# The token cap above is a safety net a deployment opts into. This is the allowance
# the product promises, and it is what an administrator sets in the UI: people reason
# in manuscripts, not tokens. Measured over real jobs a manuscript ran from 102k to
# 926k tokens — a ninefold spread — so no token figure honestly means "three
# manuscripts", and the two limits have to be separate.


def test_a_new_account_gets_three_manuscripts_by_default(db):
    """An unset environment must mean the documented allowance, NOT unlimited.

    This is the opposite of the token cap's default and the asymmetry is the point:
    a deployment that forgets to configure this should be closed, not wide open.
    """
    uid = _user(db)
    assert db.default_job_cap() == 3
    for _ in range(3):
        assert db.quota_check(uid)["allowed"] is True
        _spend(db, uid, prompt=10)
    assert db.quota_check(uid)["allowed"] is False


def test_the_refusal_counts_manuscripts_not_tokens(db):
    uid = _user(db)
    for _ in range(3):
        _spend(db, uid, prompt=10)
    check = db.quota_check(uid)
    assert check["jobs_used"] == 3 and check["jobs_cap"] == 3
    message = check["message"]
    assert "3 of your 3 manuscripts" in message
    assert "resets" in message.lower() and "administrator" in message.lower()


def test_an_admin_can_raise_one_users_allowance(db):
    uid = _user(db)
    for _ in range(3):
        _spend(db, uid, prompt=10)
    assert db.quota_check(uid)["allowed"] is False
    db.set_job_cap(uid, 10)
    assert db.quota_check(uid)["allowed"] is True


def test_unlimited_is_zero_and_reads_as_no_limit(db):
    """0 must mean 'unlimited', matching the token cap's convention — never
    'this user may process nothing'. The admin UI never asks anyone to type it."""
    uid = _user(db)
    for _ in range(5):
        _spend(db, uid, prompt=10)
    assert db.quota_check(uid)["allowed"] is False
    db.set_job_cap(uid, 0)
    assert db.job_cap_for(uid) == 0
    assert db.quota_check(uid)["allowed"] is True


def test_clearing_a_users_allowance_restores_the_default(db):
    uid = _user(db)
    db.set_job_cap(uid, 0)
    db.set_job_cap(uid, None)
    assert db.job_cap_for(uid) == 3


def test_admins_are_never_capped_on_manuscripts_either(db):
    uid = _user(db, "boss")
    db.set_user_role(uid, "admin")
    for _ in range(20):
        _spend(db, uid, prompt=10)
    assert db.job_cap_for(uid) == 0
    assert db.quota_check(uid)["allowed"] is True


def test_the_deployment_can_opt_out_explicitly(db, monkeypatch):
    """`MONTHLY_MANUSCRIPT_CAP=0` is the documented way to disable the limit — an
    unset variable is not, or the default would be a suggestion rather than a rule."""
    monkeypatch.setenv("MONTHLY_MANUSCRIPT_CAP", "0")
    uid = _user(db)
    for _ in range(9):
        _spend(db, uid, prompt=10)
    assert db.quota_check(uid)["allowed"] is True


def test_a_failed_manuscript_still_counts(db):
    """Same reasoning as the token cap: otherwise the allowance is walked past by
    submitting work that fails."""
    uid = _user(db)
    for _ in range(3):
        job_id = db.create_job(uid, "p.docx", "/tmp/p.docx", "{}")
        db.record_job_usage(job_id, {"prompt_tokens": 10, "calls": 1})
        db.fail_job(job_id, "the model returned empty content")
    assert db.quota_check(uid)["allowed"] is False


def test_one_users_manuscripts_do_not_touch_another(db):
    a, b = _user(db, "a"), _user(db, "b")
    for _ in range(3):
        _spend(db, a, prompt=10)
    assert db.quota_check(a)["allowed"] is False
    assert db.quota_check(b)["allowed"] is True


def test_a_garbled_environment_value_falls_back_to_the_default(db, monkeypatch):
    """Not to unlimited. A typo in configuration must not silently remove the limit."""
    monkeypatch.setenv("MONTHLY_MANUSCRIPT_CAP", "three")
    assert db.default_job_cap() == 3
