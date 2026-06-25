import asyncio

import agent
from app.models import AgentGraphResult


def test_run_agent_structured_defaults_blank_database_to_kpi_data(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSettings:
        redshift_database = "kpi_data"
        max_sql_retries = 1

        def validate_database(self, database: str) -> None:
            captured["validated_database"] = database

    class FakeGraph:
        async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
            captured["state"] = state
            return state

        def result_from_state(self, state: dict[str, object]) -> AgentGraphResult:
            return AgentGraphResult(
                ok=True,
                answer=f"database={state['database']}",
                needs_database=False,
            )

    monkeypatch.setattr(agent, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent, "get_default_graph", lambda: FakeGraph())

    result = asyncio.run(agent.run_agent_structured("u1", "Show KPI metrics", {"dict": {}}, "   "))

    assert result.ok is True
    assert result.answer == "database=kpi_data"
    assert captured["validated_database"] == "kpi_data"
    assert captured["state"]["database"] == "kpi_data"
