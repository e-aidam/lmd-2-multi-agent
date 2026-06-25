from __future__ import annotations

from typing import Any

from app.agents.prompts import load_prompt
from app.config import Settings
from app.services.bedrock import BedrockService


class SQLGeneratorAgent:
    def __init__(self, bedrock: BedrockService, settings: Settings) -> None:
        self.bedrock = bedrock
        self.settings = settings

    async def generate(
        self,
        *,
        question: str,
        chat_history: list[dict[str, str]],
        schema_context: dict[str, Any],
        page_context: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "question": question,
            "chat_history": chat_history,
            "schema_context": schema_context,
            "page_context": page_context,
            "database_rules": {
                "database": self.settings.redshift_database,
                "schema": self.settings.redshift_schema,
                "default_limit": self.settings.default_limit,
                "max_limit": self.settings.max_limit,
            },
        }
        try:
            result = await self.bedrock.generate_json(
                self.settings.bedrock_model_sql,
                load_prompt("sql_generator.md"),
                payload,
            )
            return {
                "sql": str(result.get("sql") or ""),
                "assumptions": _string_list(result.get("assumptions")),
                "confidence": str(result.get("confidence") or "low"),
            }
        except Exception:
            return self._fallback_sql(schema_context)

    def _fallback_sql(self, schema_context: dict[str, Any]) -> dict[str, Any]:
        tables = schema_context.get("tables", []) or []
        if not tables:
            return {"sql": "", "assumptions": ["No matching schema context was available."], "confidence": "low"}
        table = tables[0]
        table_schema = table.get("table_schema") or self.settings.redshift_schema
        table_name = table.get("table_name")
        return {
            "sql": f"SELECT COUNT(1) AS row_count FROM {table_schema}.{table_name}",
            "assumptions": ["Using a conservative row count fallback because SQL generation was unavailable."],
            "confidence": "low",
        }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]

