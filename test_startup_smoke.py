from __future__ import annotations


def test_app_imports_without_optional_cookie_dependency() -> None:
    import app

    assert hasattr(app, "st")
    assert app.COOKIE_MANAGER_AVAILABLE in {True, False}


def test_llm_settings_shape() -> None:
    import config

    settings = config.get_llm_settings()
    assert {"provider", "api_key", "base_url", "text_model", "embed_model"} <= set(settings)
