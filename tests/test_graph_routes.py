import asyncio
from typing import Any

from app.config import Settings
from app.graph import AgentRuntime, KPIAnalyticsGraph
from app.services.redshift import QueryExecution
from app.services.retry_controller import RetryController
from app.services.sql_validator import SQLValidator, SQLValidatorConfig


class FakeMemory:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def init_db(self) -> None:
        return None

    async def load_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        return [{"role": item["role"], "content": item["content"]} for item in self.saved if item["session_id"] == session_id]

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.saved.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "user_id": user_id,
                "metadata": metadata or {},
            }
        )


class FakeSchemaCache:
    def __init__(self) -> None:
        self.calls = 0
        self.force_refreshes = 0

    async def get_schema_context(
        self,
        search_terms: list[str],
        database: str,
        schema_name: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        self.calls += 1
        if force_refresh:
            self.force_refreshes += 1
        return {
            "tables": [
                {
                    "table_schema": "public",
                    "table_name": "metrics",
                    "columns": [{"column_name": "id", "data_type": "integer"}],
                }
            ],
            "metadata": {"force_refresh": force_refresh},
        }


class FakeRedshift:
    def __init__(self, results: list[QueryExecution]) -> None:
        self.results = results
        self.calls = 0

    async def execute_sql(self, sql: str) -> QueryExecution:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return QueryExecution(rows=[{"id": 1}], error=None)


class FakeMaster:
    def __init__(self, needs_database: bool) -> None:
        self.needs_database = needs_database

    async def route(self, **_: Any) -> dict[str, Any]:
        return {
            "needs_database": self.needs_database,
            "route_reason": "route",
            "schema_search_terms": ["metrics"],
        }


class FakeGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {"sql": "SELECT id FROM public.metrics", "assumptions": ["test"], "confidence": "high"}


class FakeCorrector:
    def __init__(self) -> None:
        self.calls = 0

    async def correct(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {"corrected_sql": "SELECT id FROM public.metrics", "correction_reason": "fixed"}


class FakeFinalAnswer:
    async def synthesize(self, state: dict[str, Any]) -> str:
        return state.get("final_answer") or "## Answer\n\nok"


def build_graph(
    *,
    needs_database: bool,
    redshift_results: list[QueryExecution] | None = None,
    max_retries: int = 1,
) -> tuple[KPIAnalyticsGraph, FakeSchemaCache, FakeRedshift, FakeGenerator, FakeCorrector, FakeMemory]:
    settings = Settings(max_sql_retries=max_retries)
    memory = FakeMemory()
    schema_cache = FakeSchemaCache()
    redshift = FakeRedshift(redshift_results or [QueryExecution(rows=[{"id": 1}], error=None)])
    generator = FakeGenerator()
    corrector = FakeCorrector()
    runtime = AgentRuntime(
        settings=settings,
        memory=memory,
        schema_cache=schema_cache,  # type: ignore[arg-type]
        redshift=redshift,  # type: ignore[arg-type]
        sql_validator=SQLValidator(SQLValidatorConfig(default_limit=100, max_limit=1000)),
        retry_controller=RetryController(max_retries),
        master_orchestrator=FakeMaster(needs_database),  # type: ignore[arg-type]
        sql_generator=generator,  # type: ignore[arg-type]
        sql_corrector=corrector,  # type: ignore[arg-type]
        final_answer=FakeFinalAnswer(),  # type: ignore[arg-type]
    )
    return KPIAnalyticsGraph(runtime), schema_cache, redshift, generator, corrector, memory


def initial_state() -> dict[str, Any]:
    return {
        "question": "How many metrics?",
        "user_id": "u1",
        "database": "kpi_data",
        "context": {"page_context": {"dict": {"session_id": "s1"}, "xml": "<ctx />"}},
        "retry_count": 0,
    }


def test_no_database_question_routes_to_final_answer_directly() -> None:
    graph, schema_cache, redshift, generator, corrector, memory = build_graph(needs_database=False)

    state = asyncio.run(graph.ainvoke(initial_state()))

    assert state["ok"] is True
    assert schema_cache.calls == 0
    assert redshift.calls == 0
    assert generator.calls == 0
    assert corrector.calls == 0
    assert [item["role"] for item in memory.saved] == ["user", "system", "assistant"]


def test_database_question_routes_through_sql_execution() -> None:
    graph, schema_cache, redshift, generator, corrector, _ = build_graph(needs_database=True)

    state = asyncio.run(graph.ainvoke(initial_state()))

    assert state["ok"] is True
    assert schema_cache.calls == 1
    assert generator.calls == 1
    assert redshift.calls == 1
    assert corrector.calls == 0
    assert state["row_count"] == 1


def test_corrector_runs_only_when_retry_controller_allows_it() -> None:
    graph, schema_cache, redshift, _, corrector, _ = build_graph(
        needs_database=True,
        redshift_results=[
            QueryExecution(rows=None, error="ERROR: column does not exist"),
            QueryExecution(rows=[{"id": 1}], error=None),
        ],
        max_retries=1,
    )

    state = asyncio.run(graph.ainvoke(initial_state()))

    assert state["ok"] is True
    assert redshift.calls == 2
    assert corrector.calls == 1
    assert schema_cache.force_refreshes == 1
    assert state["retry_count"] == 1


def test_final_error_after_retry_exhaustion() -> None:
    graph, _, redshift, _, corrector, _ = build_graph(
        needs_database=True,
        redshift_results=[QueryExecution(rows=None, error="timeout")],
        max_retries=0,
    )

    state = asyncio.run(graph.ainvoke(initial_state()))

    assert state["ok"] is False
    assert redshift.calls == 1
    assert corrector.calls == 0
    assert state["final_error"] == "I could not complete the query after the configured retry limit."

