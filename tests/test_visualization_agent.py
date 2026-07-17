from __future__ import annotations

import asyncio
from typing import Any

from app.agents.master_orchestrator import MasterOrchestratorAgent
from app.agents.visualization_agent import VisualizationAgent
from app.config import Settings


class StubBedrock:
    def __init__(self, response: Any = None, raise_exc: bool = False) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls = 0

    async def generate_json(self, model_id: str | None, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("bedrock unavailable")
        return self.response


def _agent(bedrock: StubBedrock) -> VisualizationAgent:
    return VisualizationAgent(bedrock, Settings())  # type: ignore[arg-type]


ROWS = [
    {"fiscal_year": "FY24", "value": 12},
    {"fiscal_year": "FY25", "value": 20},
]


def test_valid_llm_spec_is_returned() -> None:
    bedrock = StubBedrock(
        response={
            "chart_type": "line",
            "x_field": "fiscal_year",
            "y_field": "value",
            "series_field": None,
            "title": "Training KPI trend",
        }
    )
    agent = _agent(bedrock)

    result = asyncio.run(agent.build_spec(question="training trend over time", rows=ROWS))

    assert result["error"] is None
    assert result["chart_spec"] == {
        "chart_type": "line",
        "x_field": "fiscal_year",
        "y_field": "value",
        "series_field": None,
        "title": "Training KPI trend",
    }


def test_empty_rows_returns_error_without_calling_bedrock() -> None:
    bedrock = StubBedrock(raise_exc=True)  # would raise if called
    agent = _agent(bedrock)

    result = asyncio.run(agent.build_spec(question="chart it", rows=[]))

    assert result["chart_spec"] is None
    assert result["error"] == "No rows available to visualize."
    assert bedrock.calls == 0


def test_invalid_llm_spec_falls_back_to_heuristic() -> None:
    # chart_type not allowed and x_field not a real column -> normalization rejects it.
    bedrock = StubBedrock(response={"chart_type": "donut", "x_field": "nope", "y_field": "value"})
    agent = _agent(bedrock)

    result = asyncio.run(agent.build_spec(question="compare values", rows=ROWS))

    assert result["error"] is None
    spec = result["chart_spec"]
    assert spec["chart_type"] == "bar"
    assert spec["y_field"] == "value"  # first numeric-looking column
    assert spec["x_field"] == "fiscal_year"
    assert spec["series_field"] is None


def test_bedrock_exception_falls_back_to_heuristic() -> None:
    bedrock = StubBedrock(raise_exc=True)
    agent = _agent(bedrock)

    result = asyncio.run(agent.build_spec(question="plot values", rows=ROWS))

    assert result["error"] is None
    assert result["chart_spec"]["chart_type"] == "bar"
    assert result["chart_spec"]["y_field"] == "value"


def test_fallback_without_numeric_column_reports_error() -> None:
    bedrock = StubBedrock(raise_exc=True)
    agent = _agent(bedrock)

    result = asyncio.run(agent.build_spec(question="chart", rows=[{"a": "x", "b": "y"}]))

    assert result["chart_spec"] is None
    assert result["error"] == "No numeric column available to plot."


def test_heuristic_router_flags_visualization_for_chart_intent() -> None:
    result = MasterOrchestratorAgent._heuristic_route(
        "show the training KPI trend for Malawi over time",
        {"dict": {}, "xml": None},
        {},
    )

    assert result["needs_database"] is True
    assert result["needs_visualization"] is True


def test_heuristic_router_no_visualization_for_plain_lookup() -> None:
    result = MasterOrchestratorAgent._heuristic_route(
        "show total KPI metrics",
        {"dict": {}, "xml": None},
        {},
    )

    assert result["needs_database"] is True
    assert result["needs_visualization"] is False
