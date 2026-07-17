from __future__ import annotations

import importlib
import sys

import pytest

from app.config import (
    DEFAULT_FAST_MODEL_ID,
    DEFAULT_STRONG_MODEL_ID,
    Settings,
    SettingsError,
    set_settings_for_tests,
)


@pytest.fixture(autouse=True)
def reset_settings_cache() -> None:
    set_settings_for_tests(None)
    yield
    set_settings_for_tests(None)


def _clear_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AWS_REGION",
        "LMD_AWS_REGION",
        "MODEL_ID",
        "MODEL_ID_FAST",
        "BEDROCK_MODEL_MASTER",
        "BEDROCK_MODEL_SQL",
        "BEDROCK_MODEL_CORRECTOR",
        "BEDROCK_MODEL_FINAL",
        "BEDROCK_MODEL_VISUALIZATION",
        "DB_URI",
        "DATABASE_URL_READER",
        "REDSHIFT_URI",
        "REDSHIFT_HOST",
        "REDSHIFT_PORT",
        "REDSHIFT_DATABASE",
        "REDSHIFT_USER",
        "REDSHIFT_PASSWORD",
        "REDSHIFT_SCHEMA",
        "MEM_DB_URI",
        "SCHEMA_CACHE_TTL_SECONDS",
        "MAX_SQL_RETRIES",
        "QUERY_TIMEOUT_SECONDS",
        "DEFAULT_LIMIT",
        "MAX_LIMIT",
        "MAX_SCHEMA_TABLES_RETURNED",
        "AGENT_ENVIRONMENT",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_reject_invalid_mem_db_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("MEM_DB_URI", "://postgres:bad@host:5432/agent_mem")

    with pytest.raises(SettingsError, match=r"MEM_DB_URI must use a postgres:// or postgresql:// URI\."):
        Settings.from_env()


def test_settings_allow_blank_mem_db_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("MEM_DB_URI", "")

    settings = Settings.from_env()

    assert settings.mem_db_uri is None


def test_sql_agents_default_to_fast_model_master_final_to_strong(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_agent_env(monkeypatch)

    settings = Settings.from_env()

    # Master routing and final synthesis keep the stronger default.
    assert settings.bedrock_model_master == DEFAULT_STRONG_MODEL_ID
    assert settings.bedrock_model_final == DEFAULT_STRONG_MODEL_ID
    # SQL generation, correction, and visualization get the faster/cheaper Haiku default.
    assert settings.bedrock_model_sql == DEFAULT_FAST_MODEL_ID
    assert settings.bedrock_model_corrector == DEFAULT_FAST_MODEL_ID
    assert settings.bedrock_model_visualization == DEFAULT_FAST_MODEL_ID
    # The two workloads must resolve to different models by default.
    assert settings.bedrock_model_sql != settings.bedrock_model_master
    assert settings.bedrock_model_corrector != settings.bedrock_model_final


def test_model_id_only_leaves_sql_agents_on_fast_default_and_overrides_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("MODEL_ID", "custom-strong-model")

    settings = Settings.from_env()

    # MODEL_ID drives master/final only; sql/corrector stay on the Haiku fast default.
    assert settings.bedrock_model_master == "custom-strong-model"
    assert settings.bedrock_model_final == "custom-strong-model"
    assert settings.bedrock_model_sql == DEFAULT_FAST_MODEL_ID
    assert settings.bedrock_model_corrector == DEFAULT_FAST_MODEL_ID

    # An explicit per-agent override still wins over the default.
    monkeypatch.setenv("BEDROCK_MODEL_SQL", "explicit-sql-model")
    monkeypatch.setenv("MODEL_ID_FAST", "custom-fast-model")
    overridden = Settings.from_env()
    assert overridden.bedrock_model_sql == "explicit-sql-model"
    # Corrector (no explicit override) follows MODEL_ID_FAST.
    assert overridden.bedrock_model_corrector == "custom-fast-model"


def test_main_import_fails_fast_for_invalid_mem_db_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("MEM_DB_URI", "://postgres:bad@host:5432/agent_mem")
    sys.modules.pop("app.main", None)

    with pytest.raises(SettingsError, match=r"MEM_DB_URI must use a postgres:// or postgresql:// URI\."):
        importlib.import_module("app.main")
