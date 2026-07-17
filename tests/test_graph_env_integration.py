import asyncio

import pytest

from agent import run_agent_structured
from app.config import DEFAULT_FAST_MODEL_ID, get_settings, set_settings_for_tests
from app.graph import set_default_graph_for_tests
from app.services.bedrock import BedrockService
from app.services.redshift import QueryExecution, RedshiftService


@pytest.fixture(autouse=True)
def reset_runtime_singletons() -> None:
    set_settings_for_tests(None)
    set_default_graph_for_tests(None)
    yield
    set_settings_for_tests(None)
    set_default_graph_for_tests(None)


def _configure_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    base_env = {
        "LMD_AWS_REGION": "us-east-1",
        "MODEL_ID": "model-from-env",
        "DB_URI": "redshift://env_user:env_pass@warehouse.example.org:5440/kpi_data",
        "MEM_DB_URI": "",
        "DEFAULT_LIMIT": "7",
        "MAX_LIMIT": "20",
        "MAX_SQL_RETRIES": "1",
        "MAX_SCHEMA_TABLES_RETURNED": "1",
        "QUERY_TIMEOUT_SECONDS": "30",
        "AGENT_ENVIRONMENT": "local",
        "LOG_LEVEL": "INFO",
    }
    base_env.update(overrides)

    for name in (
        "AWS_REGION",
        "BEDROCK_MODEL_MASTER",
        "BEDROCK_MODEL_SQL",
        "BEDROCK_MODEL_CORRECTOR",
        "BEDROCK_MODEL_FINAL",
        "REDSHIFT_URI",
        "DATABASE_URL_READER",
        "REDSHIFT_HOST",
        "REDSHIFT_PORT",
        "REDSHIFT_USER",
        "REDSHIFT_PASSWORD",
        "REDSHIFT_SCHEMA",
    ):
        monkeypatch.delenv(name, raising=False)

    for name, value in base_env.items():
        monkeypatch.setenv(name, value)


def test_real_graph_uses_env_parsed_runtime_for_database_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_env(monkeypatch)
    captured: dict[str, object] = {
        "models": [],
        "schema_tables": [],
        "database_rules": None,
    }

    async def fake_generate_json(self: BedrockService, model_id: str | None, _: str, payload: dict[str, object]) -> dict[str, object]:
        captured["models"].append(model_id)
        if "schema_context" in payload:
            schema_context = payload["schema_context"]
            assert isinstance(schema_context, dict)
            tables = schema_context.get("tables", [])
            assert isinstance(tables, list)
            captured["schema_tables"] = [table["table_name"] for table in tables]
            captured["database_rules"] = payload["database_rules"]
            return {
                "sql": "SELECT metric_name FROM public.metrics",
                "assumptions": ["integration"],
                "confidence": "high",
            }
        return {
            "needs_database": True,
            "route_reason": "Database query required.",
            "schema_search_terms": ["metrics", "kpi"],
        }

    async def fake_generate_text(self: BedrockService, model_id: str | None, _: str, user_text: str) -> str:
        assert model_id == "model-from-env"
        assert "SELECT metric_name FROM public.metrics LIMIT 7" in user_text
        return "## Answer\n\nIntegration test answer."

    async def fake_load_full_schema(self: RedshiftService, database: str, schema_name: str | None = None) -> dict[str, object]:
        assert database == "kpi_data"
        assert schema_name == "public"
        return {
            "tables": [
                {
                    "table_schema": "public",
                    "table_name": "metrics",
                    "columns": [
                        {"column_name": "metric_name", "data_type": "varchar", "ordinal_position": 1},
                    ],
                },
                {
                    "table_schema": "public",
                    "table_name": "metrics_archive",
                    "columns": [
                        {"column_name": "metric_name", "data_type": "varchar", "ordinal_position": 1},
                    ],
                },
            ]
        }

    async def fake_execute_sql(self: RedshiftService, sql: str) -> QueryExecution:
        assert self.settings.redshift_host == "warehouse.example.org"
        assert self.settings.redshift_port == 5440
        assert self.settings.redshift_user == "env_user"
        assert self.settings.redshift_password == "env_pass"
        assert sql == "SELECT metric_name FROM public.metrics LIMIT 7"
        return QueryExecution(rows=[{"metric_name": "retention"}], error=None)

    monkeypatch.setattr(BedrockService, "generate_json", fake_generate_json)
    monkeypatch.setattr(BedrockService, "generate_text", fake_generate_text)
    monkeypatch.setattr(RedshiftService, "load_full_schema", fake_load_full_schema)
    monkeypatch.setattr(RedshiftService, "execute_sql", fake_execute_sql)

    result = asyncio.run(
        run_agent_structured(
            "u1",
            "Show KPI metrics",
            {"dict": {"session_id": "portal-session"}, "xml": "<ctx />"},
            "kpi_data",
        )
    )

    settings = get_settings()

    assert settings.aws_region == "us-east-1"
    assert settings.redshift_host == "warehouse.example.org"
    assert settings.redshift_port == 5440
    assert settings.redshift_user == "env_user"
    assert settings.redshift_password == "env_pass"
    assert result.ok is True
    assert result.answer == "## Answer\n\nIntegration test answer."
    assert result.sql_used == "SELECT metric_name FROM public.metrics LIMIT 7"
    assert result.row_count == 1
    assert result.metadata["session_id"] == "portal-session"
    assert result.metadata["max_sql_retries"] == 1
    # Master orchestrator inherits MODEL_ID; the SQL generator defaults to the fast Haiku model.
    assert captured["models"] == ["model-from-env", DEFAULT_FAST_MODEL_ID]
    assert captured["schema_tables"] == ["metrics"]
    assert captured["database_rules"] == {
        "database": "kpi_data",
        "schema": "public",
        "default_limit": 7,
        "max_limit": 20,
    }


def test_real_graph_produces_chart_spec_for_visualization_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_env(monkeypatch)

    async def fake_generate_json(self: BedrockService, model_id: str | None, _: str, payload: dict[str, object]) -> dict[str, object]:
        if "columns" in payload:  # visualization agent
            return {
                "chart_type": "line",
                "x_field": "fiscal_year",
                "y_field": "value",
                "series_field": None,
                "title": "Training KPI trend",
            }
        if "schema_context" in payload:  # sql generator
            return {
                "sql": "SELECT fiscal_year, value FROM public.training_kpi",
                "assumptions": ["viz"],
                "confidence": "high",
            }
        # master orchestrator: chart-worthy database question
        return {
            "needs_database": True,
            "needs_visualization": True,
            "route_reason": "Trend chart requested.",
            "schema_search_terms": ["training", "malawi"],
        }

    async def fake_generate_text(self: BedrockService, model_id: str | None, _: str, user_text: str) -> str:
        return "## Answer\n\n## Chart\n\nShowing a line chart of the training KPI trend."

    async def fake_load_full_schema(self: RedshiftService, database: str, schema_name: str | None = None) -> dict[str, object]:
        return {
            "tables": [
                {
                    "table_schema": "public",
                    "table_name": "training_kpi",
                    "columns": [
                        {"column_name": "fiscal_year", "data_type": "varchar", "ordinal_position": 1},
                        {"column_name": "value", "data_type": "integer", "ordinal_position": 2},
                    ],
                }
            ]
        }

    async def fake_execute_sql(self: RedshiftService, sql: str) -> QueryExecution:
        return QueryExecution(
            rows=[{"fiscal_year": "FY24", "value": 10}, {"fiscal_year": "FY25", "value": 20}],
            error=None,
        )

    monkeypatch.setattr(BedrockService, "generate_json", fake_generate_json)
    monkeypatch.setattr(BedrockService, "generate_text", fake_generate_text)
    monkeypatch.setattr(RedshiftService, "load_full_schema", fake_load_full_schema)
    monkeypatch.setattr(RedshiftService, "execute_sql", fake_execute_sql)

    result = asyncio.run(
        run_agent_structured(
            "u1",
            "show the training KPI trend for Malawi over time",
            {"dict": {"route": "malawi", "session_id": "portal-session"}, "xml": "<ctx />"},
            "kpi_data",
        )
    )

    assert result.ok is True
    assert result.metadata["needs_visualization"] is True
    assert result.chart_spec == {
        "chart_type": "line",
        "x_field": "fiscal_year",
        "y_field": "value",
        "series_field": None,
        "title": "Training KPI trend",
    }


def test_real_graph_uses_env_limits_during_retry_and_correction(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_env(
        monkeypatch,
        DEFAULT_LIMIT="5",
        MAX_LIMIT="5",
        MAX_SQL_RETRIES="1",
    )
    captured: dict[str, object] = {
        "loader_calls": 0,
        "executed_sql": [],
        "corrector_seen": False,
    }

    async def fake_generate_json(self: BedrockService, model_id: str | None, _: str, payload: dict[str, object]) -> dict[str, object]:
        if "failed_sql" in payload:
            # SQL corrector defaults to the fast Haiku model.
            assert model_id == DEFAULT_FAST_MODEL_ID
            captured["corrector_seen"] = True
            return {
                "corrected_sql": "SELECT metric_name FROM public.metrics LIMIT 99",
                "correction_reason": "Fixed bad column reference.",
            }
        if "schema_context" in payload:
            # SQL generator defaults to the fast Haiku model.
            assert model_id == DEFAULT_FAST_MODEL_ID
            return {
                "sql": "SELECT missing_column FROM public.metrics",
                "assumptions": ["integration"],
                "confidence": "medium",
            }
        # Master orchestrator keeps the stronger MODEL_ID.
        assert model_id == "model-from-env"
        return {
            "needs_database": True,
            "route_reason": "Database query required.",
            "schema_search_terms": ["metrics"],
        }

    async def fake_generate_text(self: BedrockService, model_id: str | None, user_prompt: str, user_text: str) -> str:
        assert model_id == "model-from-env"
        assert user_prompt
        assert "SELECT metric_name FROM public.metrics LIMIT 5" in user_text
        return "## Answer\n\nRetry integration answer."

    async def fake_load_full_schema(self: RedshiftService, database: str, schema_name: str | None = None) -> dict[str, object]:
        captured["loader_calls"] = int(captured["loader_calls"]) + 1
        assert database == "kpi_data"
        assert schema_name == "public"
        return {
            "tables": [
                {
                    "table_schema": "public",
                    "table_name": "metrics",
                    "columns": [
                        {"column_name": "metric_name", "data_type": "varchar", "ordinal_position": 1},
                    ],
                }
            ]
        }

    async def fake_execute_sql(self: RedshiftService, sql: str) -> QueryExecution:
        executed_sql = captured["executed_sql"]
        assert isinstance(executed_sql, list)
        executed_sql.append(sql)
        if len(executed_sql) == 1:
            return QueryExecution(rows=None, error="ERROR: column does not exist")
        return QueryExecution(rows=[{"metric_name": "retention"}], error=None)

    monkeypatch.setattr(BedrockService, "generate_json", fake_generate_json)
    monkeypatch.setattr(BedrockService, "generate_text", fake_generate_text)
    monkeypatch.setattr(RedshiftService, "load_full_schema", fake_load_full_schema)
    monkeypatch.setattr(RedshiftService, "execute_sql", fake_execute_sql)

    result = asyncio.run(
        run_agent_structured(
            "u1",
            "Show KPI metrics with retry",
            {"dict": {}, "xml": "<ctx />"},
            "kpi_data",
        )
    )

    assert result.ok is True
    assert result.answer == "## Answer\n\nRetry integration answer."
    assert result.sql_used == "SELECT metric_name FROM public.metrics LIMIT 5"
    assert result.row_count == 1
    assert result.metadata["retry_count"] == 1
    assert result.metadata["session_id"] == "kpi_data:u1"
    assert captured["corrector_seen"] is True
    assert captured["loader_calls"] == 2
    assert captured["executed_sql"] == [
        "SELECT missing_column FROM public.metrics LIMIT 5",
        "SELECT metric_name FROM public.metrics LIMIT 5",
    ]
