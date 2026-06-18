"""Tests for Google-SSO domain restriction, admin roles, and break-glass admin."""

import importlib

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOWED_LOGIN_DOMAINS", raising=False)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    import config
    import auth
    importlib.reload(config)
    importlib.reload(auth)
    return config, auth


def test_allowed_domains_default(mods):
    config, _ = mods
    assert config.allowed_login_domains() == ["celnet.in", "conwiz.in", "stmjournals.com"]
    assert config.email_domain_allowed("a@celnet.in")
    assert config.email_domain_allowed("b@conwiz.in")
    assert config.email_domain_allowed("c@stmjournals.com")
    assert not config.email_domain_allowed("x@gmail.com")
    assert not config.email_domain_allowed("nodomain")
    assert not config.email_domain_allowed("")


def test_admin_email_default_and_case_insensitive(mods):
    config, _ = mods
    assert config.admin_emails() == ["amit.rai@celnet.in"]
    assert config.is_admin_email("amit.rai@celnet.in")
    assert config.is_admin_email("AMIT.RAI@CELNET.IN")
    assert not config.is_admin_email("someone@celnet.in")


def test_domain_and_admin_env_override(mods, monkeypatch):
    config, _ = mods
    monkeypatch.setenv("ALLOWED_LOGIN_DOMAINS", "example.com, foo.org")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    assert config.allowed_login_domains() == ["example.com", "foo.org"]
    assert config.email_domain_allowed("u@example.com")
    assert not config.email_domain_allowed("u@celnet.in")
    assert config.is_admin_email("boss@example.com")


def test_oauth_user_roles_and_idempotent(mods):
    _, auth = mods
    admin = auth.get_or_create_oauth_user("amit.rai@celnet.in", "Amit")
    member = auth.get_or_create_oauth_user("staff@stmjournals.com", "Staff")
    assert auth.is_admin(admin)
    assert not auth.is_admin(member)
    assert auth.get_user_role(member) == "member"
    # same email -> same row
    assert auth.get_or_create_oauth_user("amit.rai@celnet.in") == admin
    # case-insensitive username
    assert auth.get_or_create_oauth_user("AMIT.RAI@CELNET.IN") == admin


def test_sso_account_cannot_password_login(mods):
    _, auth = mods
    auth.get_or_create_oauth_user("staff@conwiz.in", "Staff")
    assert auth.login("staff@conwiz.in", "anything") is None
    assert auth.login("staff@conwiz.in", "") is None


def test_seed_admin_break_glass(mods, monkeypatch):
    _, auth = mods
    monkeypatch.setenv("SEED_ADMIN_USERNAME", "breakglass")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "S3cret!pw")
    auth.ensure_seed_admin()
    uid = auth.login("breakglass", "S3cret!pw")
    assert uid is not None and auth.is_admin(uid)
    # wrong password fails
    assert auth.login("breakglass", "nope") is None


def test_set_user_role(mods):
    _, auth = mods
    uid = auth.get_or_create_oauth_user("staff@celnet.in")
    assert not auth.is_admin(uid)
    auth.set_user_role(uid, "admin")
    assert auth.is_admin(uid)


def test_materialize_auth_secrets_from_env(tmp_path, monkeypatch):
    import config
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-xyz")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://ce4.celnet.in/oauth2callback")
    monkeypatch.setenv("OAUTH_COOKIE_SECRET", "deadbeef" * 8)

    assert config.materialize_auth_secrets() is True
    content = (tmp_path / ".streamlit" / "secrets.toml").read_text()
    assert "[auth]" in content and "[auth.google]" in content
    assert 'redirect_uri = "https://ce4.celnet.in/oauth2callback"' in content
    assert 'client_id = "cid.apps.googleusercontent.com"' in content
    # idempotent: a file already containing [auth] is not overwritten
    assert config.materialize_auth_secrets() is False


def test_materialize_noop_without_env(tmp_path, monkeypatch):
    import config
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
              "OAUTH_REDIRECT_URI", "OAUTH_COOKIE_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert config.materialize_auth_secrets() is False
    assert not (tmp_path / ".streamlit" / "secrets.toml").exists()
