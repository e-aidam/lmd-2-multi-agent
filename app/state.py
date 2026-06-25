from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    user_id: str | None
    session_id: str | None
    database: str
    context: dict[str, Any]

    chat_history: list[dict[str, str]]
    memory_loaded: bool
    memory_saved: bool

    needs_database: bool
    route_reason: str

    schema_context: dict[str, Any]
    schema_search_terms: list[str]

    generated_sql: str
    validated_sql: str
    sql_assumptions: list[str]

    query_result: list[dict[str, Any]] | None
    query_error: str | None

    corrected_sql: str
    correction_reason: str

    retry_count: int
    max_sql_retries: int
    can_retry: bool

    final_answer: str
    preview_markdown: str | None
    row_count: int | None
    ok: bool
    final_error: str | None
