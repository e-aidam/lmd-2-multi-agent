from __future__ import annotations

import json
from typing import Any

from app.agents.prompts import load_prompt
from app.config import Settings
from app.services.bedrock import BedrockService


class FinalAnswerAgent:
    def __init__(self, bedrock: BedrockService, settings: Settings) -> None:
        self.bedrock = bedrock
        self.settings = settings

    async def synthesize(self, state: dict[str, Any]) -> str:
        context = state.get("context") or {}
        payload = {
            "question": state.get("question"),
            "chat_history": state.get("chat_history", []),
            "page_context": context.get("page_context") if isinstance(context, dict) else None,
            "needs_database": state.get("needs_database"),
            "route_reason": state.get("route_reason"),
            "sql_used": state.get("validated_sql"),
            "row_count": state.get("row_count"),
            "preview_markdown": state.get("preview_markdown"),
            "chart_spec": state.get("chart_spec"),
            "assumptions": state.get("sql_assumptions", []),
            "query_error": state.get("query_error"),
        }
        try:
            return await self.bedrock.generate_text(
                self.settings.bedrock_model_final,
                load_prompt("final_answer.md"),
                json.dumps(payload, default=str),
            )
        except Exception:
            return self._fallback_answer(state)

    @staticmethod
    def _fallback_answer(state: dict[str, Any]) -> str:
        if not state.get("ok", True) or state.get("final_error"):
            return state.get("final_answer") or "## Answer\n\nI could not complete that request."

        if not state.get("needs_database"):
            route_reason = state.get("route_reason") or "This question does not require a database query."
            return f"## Answer\n\n{route_reason}"

        parts = ["## Answer"]
        row_count = state.get("row_count")
        if row_count is None:
            parts.append("\nThe query completed.")
        elif row_count == 0:
            parts.append("\nThe query completed but returned no rows.")
        else:
            parts.append(f"\nThe query returned {row_count} row(s).")

        sql_used = state.get("validated_sql")
        if sql_used:
            parts.append(f"\n## SQL Used\n\n```sql\n{sql_used}\n```")

        # When a chart is being shown, reference it with a short caption instead of
        # repeating the full result table.
        chart_spec = state.get("chart_spec")
        if isinstance(chart_spec, dict) and chart_spec.get("chart_type"):
            title = chart_spec.get("title") or "the query results"
            chart_type = chart_spec.get("chart_type")
            x_field = chart_spec.get("x_field")
            y_field = chart_spec.get("y_field")
            parts.append(
                f"\n## Chart\n\nShowing a {chart_type} chart of {title} "
                f"({y_field} by {x_field})."
            )
        else:
            preview = state.get("preview_markdown")
            if preview:
                parts.append(f"\n## Data Preview\n\n{preview}")

        assumptions = state.get("sql_assumptions") or []
        if assumptions:
            joined = "\n".join(f"- {item}" for item in assumptions)
            parts.append(f"\n## Assumptions\n\n{joined}")

        return "\n".join(parts)

