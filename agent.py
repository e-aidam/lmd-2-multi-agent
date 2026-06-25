from __future__ import annotations

from typing import Any

from app.config import SettingsError, get_settings
from app.graph import get_default_graph
from app.models import AgentGraphResult
from app.state import AgentState


async def interact(
    user_id: str,
    message: str,
    page_context: dict[str, Any],
    database: str = "kpi_data",
) -> list[str]:
    result = await run_agent_structured(user_id, message, page_context, database)
    return [result.answer]


async def run_agent_structured(
    user_id: str,
    message: str,
    page_context: dict[str, Any],
    database: str = "kpi_data",
) -> AgentGraphResult:
    settings = get_settings()
    database = _resolve_database(database, settings.redshift_database)
    try:
        settings.validate_database(database)
    except SettingsError as exc:
        return AgentGraphResult(
            ok=False,
            answer=f"I'm sorry, I cannot query that database. {exc}",
            needs_database=False,
            error=str(exc),
        )

    graph = get_default_graph()
    initial_state: AgentState = {
        "question": message,
        "user_id": user_id,
        "database": database,
        "context": {"page_context": page_context},
        "retry_count": 0,
        "max_sql_retries": settings.max_sql_retries,
    }
    final_state = await graph.ainvoke(initial_state)
    return graph.result_from_state(final_state)


def _resolve_database(database: str | None, default_database: str) -> str:
    normalized_database = database.strip() if isinstance(database, str) else ""
    return normalized_database or default_database


def format_output(message: str, raw_output: str) -> str:
    return raw_output.strip() or "No response generated"
