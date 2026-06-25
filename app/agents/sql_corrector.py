from __future__ import annotations

from typing import Any

from app.agents.prompts import load_prompt
from app.config import Settings
from app.services.bedrock import BedrockService


class SQLCorrectorAgent:
    def __init__(self, bedrock: BedrockService, settings: Settings) -> None:
        self.bedrock = bedrock
        self.settings = settings

    async def correct(
        self,
        *,
        question: str,
        chat_history: list[dict[str, str]],
        schema_context: dict[str, Any],
        failed_sql: str,
        query_error: str,
        assumptions: list[str],
        retry_count: int,
        max_sql_retries: int,
    ) -> dict[str, Any]:
        payload = {
            "question": question,
            "chat_history": chat_history,
            "schema_context": schema_context,
            "failed_sql": failed_sql,
            "query_error": query_error,
            "assumptions": assumptions,
            "retry_count": retry_count,
            "max_sql_retries": max_sql_retries,
        }
        try:
            result = await self.bedrock.generate_json(
                self.settings.bedrock_model_corrector,
                load_prompt("sql_corrector.md"),
                payload,
            )
            return {
                "corrected_sql": str(result.get("corrected_sql") or ""),
                "correction_reason": str(result.get("correction_reason") or "Corrected SQL."),
            }
        except Exception:
            return {
                "corrected_sql": failed_sql,
                "correction_reason": "Retried the same SQL because the SQL Corrector was unavailable.",
            }

