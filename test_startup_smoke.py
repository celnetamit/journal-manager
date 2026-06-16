from __future__ import annotations


def test_app_imports_without_optional_cookie_dependency() -> None:
    import app

    assert hasattr(app, "st")
    assert app.COOKIE_MANAGER_AVAILABLE in {True, False}


def test_login_throttle_locks_after_max_attempts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "3")

    import importlib
    import config
    import auth

    importlib.reload(config)
    importlib.reload(auth)

    assert auth.register("throttle_user", "correct-pw") is True
    for _ in range(3):
        assert auth.login("throttle_user", "wrong-pw") is None
    assert auth.is_locked_out("throttle_user") is True
    # Correct credentials are refused while locked out.
    assert auth.login("throttle_user", "correct-pw") is None


def test_expired_login_token_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LOGIN_TOKEN_TTL_DAYS", "30")

    import importlib
    import config
    import auth

    importlib.reload(config)
    importlib.reload(auth)

    assert auth.register("token_user", "correct-pw") is True
    user_id = auth.login("token_user", "correct-pw")
    assert user_id is not None

    token = auth.issue_login_token(user_id)
    assert auth.resolve_login_token(token) is not None

    # Backdate the token past the TTL; it must no longer resolve.
    with auth._connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE login_tokens SET created_at=? WHERE token_hash=?",
            ("2000-01-01 00:00:00", auth._token_hash(token)),
        )
        conn.commit()
    assert auth.resolve_login_token(token) is None


def test_llm_settings_shape() -> None:
    import config

    settings = config.get_llm_settings()
    assert {"provider", "api_key", "base_url", "text_model", "embed_model"} <= set(settings)


def test_ollama_alias_maps_to_openrouter() -> None:
    import config

    settings = config.normalize_llm_settings({"provider": "ollama"})

    assert settings["provider"] == "openrouter"
    assert settings["base_url"] == "https://openrouter.ai/api/v1"


def test_openrouter_keeps_its_own_base_url(monkeypatch) -> None:
    import config

    monkeypatch.setenv("LLM_BASE_URL", "http://host.docker.internal:11434/api")
    settings = config.normalize_llm_settings(
        {"provider": "openrouter", "base_url": "http://host.docker.internal:11434/api"}
    )

    assert settings["provider"] == "openrouter"
    assert settings["base_url"] == "https://openrouter.ai/api/v1"


def test_llm_config_unlocked_by_default(monkeypatch) -> None:
    import config

    monkeypatch.delenv("LLM_CONFIG_LOCKED", raising=False)
    assert config.llm_config_locked() is False


def test_llm_config_lock_refuses_save(monkeypatch) -> None:
    import config

    monkeypatch.setenv("LLM_CONFIG_LOCKED", "1")
    assert config.llm_config_locked() is True
    try:
        config.save_llm_settings({"provider": "gemini", "api_key": "should-not-persist"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("save_llm_settings must refuse while LLM_CONFIG_LOCKED is set")


def test_provider_labels_exclude_ollama() -> None:
    import app

    assert "ollama" not in app._PROVIDER_LABELS
    assert "ollama" not in app._BASE_URL_PROVIDERS


def test_openrouter_sidebar_defaults_are_explicit() -> None:
    import app

    sidebar_settings = app._openrouter_sidebar_settings()

    assert sidebar_settings["provider"] == "openrouter"
    assert sidebar_settings["base_url"] == "https://openrouter.ai/api/v1"
    assert sidebar_settings["text_model"] == "openai/gpt-4o-mini"
    assert sidebar_settings["embed_model"] == "openai/text-embedding-3-small"


def test_openrouter_summary_card_matches_sidebar_defaults() -> None:
    import app

    summary = app._openrouter_summary_card()

    assert summary["title"] == "OpenRouter setup"
    assert summary["provider"] == "OpenRouter"
    assert summary["base_url"] == "https://openrouter.ai/api/v1"
    assert summary["text_model"] == "openai/gpt-4o-mini"
    assert summary["embed_model"] == "openai/text-embedding-3-small"


def test_provider_switch_to_openrouter_loads_openrouter_defaults() -> None:
    import app

    snapshot = dict(app.st.session_state)
    try:
        app.st.session_state.clear()
        app.st.session_state[app._SIDEBAR_LAST_PROVIDER_KEY] = "gemini"
        app.st.session_state[app._SIDEBAR_SETTING_KEYS["base_url"]] = ""
        app.st.session_state[app._SIDEBAR_SETTING_KEYS["text_model"]] = "google/gemini-2.5-pro"
        app.st.session_state[app._SIDEBAR_SETTING_KEYS["embed_model"]] = "google/gemini-embedding-2"

        app._sync_sidebar_defaults("openrouter")

        assert app.st.session_state[app._SIDEBAR_SETTING_KEYS["base_url"]] == (
            "https://openrouter.ai/api/v1"
        )
        assert app.st.session_state[app._SIDEBAR_SETTING_KEYS["text_model"]] == (
            "openai/gpt-4o-mini"
        )
        assert app.st.session_state[app._SIDEBAR_SETTING_KEYS["embed_model"]] == (
            "openai/text-embedding-3-small"
        )
        assert app.st.session_state[app._SIDEBAR_LAST_PROVIDER_KEY] == "openrouter"
    finally:
        app.st.session_state.clear()
        for key, value in snapshot.items():
            app.st.session_state[key] = value
