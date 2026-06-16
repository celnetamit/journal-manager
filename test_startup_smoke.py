from __future__ import annotations


def test_app_imports_without_optional_cookie_dependency() -> None:
    import app

    assert hasattr(app, "st")
    assert app.COOKIE_MANAGER_AVAILABLE in {True, False}


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
