from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import unquote, urlparse
from typing import Any


class SettingsError(RuntimeError):
    """Raised when runtime settings are invalid for the selected environment."""


# Strong, higher-accuracy default for routing and final-response synthesis.
DEFAULT_STRONG_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
# Faster/cheaper default for the mechanical, structured SQL generation/correction work.
DEFAULT_FAST_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _getenv(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _getenv_any(names: tuple[str, ...], default: str | None = None) -> str | None:
    for name in names:
        value = _getenv(name)
        if value is not None:
            return value
    return default


def _promote_aws_aliases() -> None:
    alias_pairs = (
        ("AWS_ACCESS_KEY_ID", "LMD_AWS_ACCESS_KEY_ID"),
        ("AWS_SECRET_ACCESS_KEY", "LMD_AWS_SECRET_ACCESS_KEY"),
        ("AWS_REGION", "LMD_AWS_REGION"),
    )
    for canonical, alias in alias_pairs:
        if not os.getenv(canonical) and os.getenv(alias):
            os.environ[canonical] = os.environ[alias]


def _parse_database_uri(uri: str | None) -> dict[str, Any]:
    if not uri:
        return {}
    parsed = urlparse(uri)
    if not parsed.hostname:
        return {}
    values: dict[str, Any] = {
        "host": parsed.hostname,
        "port": parsed.port,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _get_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = _getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer.") from exc
    if minimum is not None and value < minimum:
        raise SettingsError(f"{name} must be greater than or equal to {minimum}.")
    return value


def _validate_postgres_uri(name: str, uri: str | None) -> None:
    if not uri:
        return

    parsed = urlparse(uri)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SettingsError(f"{name} must use a postgres:// or postgresql:// URI.")
    if not parsed.hostname:
        raise SettingsError(f"{name} must include a hostname.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise SettingsError(f"{name} must include a valid port when one is provided.") from exc


@dataclass(frozen=True)
class Settings:
    aws_region: str = "us-east-1"
    bedrock_model_master: str | None = None
    bedrock_model_sql: str | None = None
    bedrock_model_corrector: str | None = None
    bedrock_model_final: str | None = None

    redshift_host: str | None = None
    redshift_port: int = 5439
    redshift_database: str = "kpi_data"
    redshift_user: str | None = None
    redshift_password: str | None = None
    redshift_schema: str = "public"

    mem_db_uri: str | None = None

    schema_cache_ttl_seconds: int = 86400
    max_sql_retries: int = 1
    query_timeout_seconds: int = 30
    default_limit: int = 100
    max_limit: int = 1000
    max_schema_tables_returned: int = 25

    environment: str = "local"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, *, validate: bool = True) -> "Settings":
        _load_dotenv_if_available()
        _promote_aws_aliases()
        redshift_uri_values = _parse_database_uri(_getenv_any(("REDSHIFT_URI", "DB_URI", "DATABASE_URL_READER")))
        # Master routing and final-answer synthesis default to the stronger model (MODEL_ID);
        # SQL generation and correction default to a faster/cheaper Haiku model (MODEL_ID_FAST).
        strong_default = _getenv("MODEL_ID", DEFAULT_STRONG_MODEL_ID)
        fast_default = _getenv("MODEL_ID_FAST", DEFAULT_FAST_MODEL_ID)
        settings = cls(
            aws_region=_getenv_any(("AWS_REGION", "LMD_AWS_REGION"), "us-east-1") or "us-east-1",
            bedrock_model_master=_getenv("BEDROCK_MODEL_MASTER", strong_default),
            bedrock_model_sql=_getenv("BEDROCK_MODEL_SQL", fast_default),
            bedrock_model_corrector=_getenv("BEDROCK_MODEL_CORRECTOR", fast_default),
            bedrock_model_final=_getenv("BEDROCK_MODEL_FINAL", strong_default),
            redshift_host=_getenv("REDSHIFT_HOST", redshift_uri_values.get("host")),
            redshift_port=_get_int("REDSHIFT_PORT", int(redshift_uri_values.get("port") or 5439), 1),
            redshift_database=_getenv("REDSHIFT_DATABASE", "kpi_data") or "kpi_data",
            redshift_user=_getenv("REDSHIFT_USER", redshift_uri_values.get("user")),
            redshift_password=_getenv("REDSHIFT_PASSWORD", redshift_uri_values.get("password")),
            redshift_schema=_getenv("REDSHIFT_SCHEMA", "public") or "public",
            mem_db_uri=_getenv("MEM_DB_URI"),
            schema_cache_ttl_seconds=_get_int("SCHEMA_CACHE_TTL_SECONDS", 86400, 0),
            max_sql_retries=_get_int("MAX_SQL_RETRIES", 1, 0),
            query_timeout_seconds=_get_int("QUERY_TIMEOUT_SECONDS", 30, 1),
            default_limit=_get_int("DEFAULT_LIMIT", 100, 1),
            max_limit=_get_int("MAX_LIMIT", 1000, 1),
            max_schema_tables_returned=_get_int("MAX_SCHEMA_TABLES_RETURNED", 25, 1),
            environment=_getenv("AGENT_ENVIRONMENT", "local") or "local",
            log_level=_getenv("LOG_LEVEL", "INFO") or "INFO",
        )
        if settings.redshift_database != "kpi_data":
            raise SettingsError("REDSHIFT_DATABASE must be kpi_data.")
        if settings.default_limit > settings.max_limit:
            raise SettingsError("DEFAULT_LIMIT cannot exceed MAX_LIMIT.")
        if validate:
            settings.validate_runtime()
        return settings

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def allowed_databases(self) -> set[str]:
        return {self.redshift_database}

    def validate_database(self, database: str) -> None:
        if database not in self.allowed_databases:
            raise SettingsError(f"Database '{database}' is not configured for this service.")

    def validate_runtime(self) -> None:
        _validate_postgres_uri("MEM_DB_URI", self.mem_db_uri)

        if not self.is_production:
            return
        required: dict[str, Any] = {
            "MEM_DB_URI": self.mem_db_uri,
            "REDSHIFT_HOST": self.redshift_host,
            "REDSHIFT_USER": self.redshift_user,
            "REDSHIFT_PASSWORD": self.redshift_password,
            "BEDROCK_MODEL_MASTER": self.bedrock_model_master,
            "BEDROCK_MODEL_SQL": self.bedrock_model_sql,
            "BEDROCK_MODEL_CORRECTOR": self.bedrock_model_corrector,
            "BEDROCK_MODEL_FINAL": self.bedrock_model_final,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            joined = ", ".join(missing)
            raise SettingsError(f"Missing required production settings: {joined}")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def set_settings_for_tests(settings: Settings | None) -> None:
    global _settings
    _settings = settings
