from __future__ import annotations

import importlib
import sys

import pytest

from app.config import Settings, SettingsError, set_settings_for_tests


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
        "BEDROCK_MODEL_MASTER",
        "BEDROCK_MODEL_SQL",
        "BEDROCK_MODEL_CORRECTOR",
        "BEDROCK_MODEL_FINAL",
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


def test_main_import_fails_fast_for_invalid_mem_db_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("MEM_DB_URI", "://postgres:bad@host:5432/agent_mem")
    sys.modules.pop("app.main", None)

    with pytest.raises(SettingsError, match=r"MEM_DB_URI must use a postgres:// or postgresql:// URI\."):
        importlib.import_module("app.main")
