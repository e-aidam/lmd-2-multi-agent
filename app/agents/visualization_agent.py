from __future__ import annotations

from typing import Any

from app.agents.prompts import load_prompt
from app.config import Settings
from app.services.bedrock import BedrockService


CHART_TYPES = ("line", "bar", "pie")
# Cap the number of sample rows sent to the LLM; the shape is enough to pick fields.
MAX_SAMPLE_ROWS = 20


class VisualizationAgent:
    """Turns query result rows into a minimal, frontend-renderable chart spec.

    The spec shape is intentionally small so the portal can map it to any charting library:
        {"chart_type": "line"|"bar"|"pie", "x_field": str, "y_field": str,
         "series_field": str | None, "title": str}
    """

    def __init__(self, bedrock: BedrockService, settings: Settings) -> None:
        self.bedrock = bedrock
        self.settings = settings

    async def build_spec(
        self,
        *,
        question: str,
        rows: list[dict[str, Any]] | None,
        page_context: dict[str, Any] | None = None,
        dashboard_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_rows = rows or []
        if not safe_rows:
            return {"chart_spec": None, "error": "No rows available to visualize."}

        columns = list(safe_rows[0].keys())
        if not columns:
            return {"chart_spec": None, "error": "Query result has no columns to visualize."}

        payload = {
            "question": question,
            "columns": columns,
            "sample_rows": safe_rows[:MAX_SAMPLE_ROWS],
            "row_count": len(safe_rows),
            "page_context": page_context or {},
            "dashboard_context": dashboard_context or {},
            "allowed_chart_types": list(CHART_TYPES),
        }
        try:
            result = await self.bedrock.generate_json(
                self.settings.bedrock_model_visualization,
                load_prompt("visualization_agent.md"),
                payload,
            )
            spec = self._normalize_spec(result, columns, question)
            if spec is not None:
                return {"chart_spec": spec, "error": None}
        except Exception:
            pass
        return self._fallback_spec(safe_rows, columns, question)

    @staticmethod
    def _normalize_spec(
        result: Any,
        columns: list[str],
        question: str,
    ) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        chart_type = str(result.get("chart_type") or "").strip().lower()
        x_field = result.get("x_field")
        y_field = result.get("y_field")
        series_field = result.get("series_field")
        if chart_type not in CHART_TYPES:
            return None
        if x_field not in columns or y_field not in columns:
            return None
        if series_field is not None and series_field not in columns:
            series_field = None
        title = str(result.get("title") or "").strip() or _default_title(question)
        return {
            "chart_type": chart_type,
            "x_field": x_field,
            "y_field": y_field,
            "series_field": series_field,
            "title": title,
        }

    @staticmethod
    def _fallback_spec(
        rows: list[dict[str, Any]],
        columns: list[str],
        question: str,
    ) -> dict[str, Any]:
        # Pick the first numeric-looking column as the measure (y), the first other column as x.
        numeric_cols = [col for col in columns if _looks_numeric(rows[0].get(col))]
        if not numeric_cols:
            return {"chart_spec": None, "error": "No numeric column available to plot."}
        y_field = numeric_cols[0]
        x_field = next((col for col in columns if col != y_field), y_field)
        return {
            "chart_spec": {
                "chart_type": "bar",
                "x_field": x_field,
                "y_field": y_field,
                "series_field": None,
                "title": _default_title(question),
            },
            "error": None,
        }


def _default_title(question: str) -> str:
    cleaned = (question or "").strip()
    return cleaned[:120] if cleaned else "Query results"


def _looks_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        candidate = value.strip().replace(",", "")
        if not candidate:
            return False
        try:
            float(candidate)
            return True
        except ValueError:
            return False
    return False
