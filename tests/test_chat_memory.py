import asyncio

from app.config import Settings
from app.graph import AgentRuntime, KPIAnalyticsGraph
from app.services.chat_memory import ChatMemoryService
from app.services.redshift import QueryExecution
from app.services.retry_controller import RetryController
from app.services.sql_validator import SQLValidator
from tests.test_graph_routes import (
    FakeCorrector,
    FakeFinalAnswer,
    FakeGenerator,
    FakeMaster,
    FakeMemory,
    FakeRedshift,
    FakeSchemaCache,
)


def test_derive_session_id_uses_page_context_session_id() -> None:
    runtime = AgentRuntime(
        settings=Settings(),
        memory=FakeMemory(),  # type: ignore[arg-type]
        schema_cache=FakeSchemaCache(),  # type: ignore[arg-type]
        redshift=FakeRedshift([QueryExecution(rows=[{"id": 1}], error=None)]),  # type: ignore[arg-type]
        sql_validator=SQLValidator(),
        retry_controller=RetryController(1),
        master_orchestrator=FakeMaster(False),  # type: ignore[arg-type]
        sql_generator=FakeGenerator(),  # type: ignore[arg-type]
        sql_corrector=FakeCorrector(),  # type: ignore[arg-type]
        final_answer=FakeFinalAnswer(),  # type: ignore[arg-type]
    )
    graph = KPIAnalyticsGraph(runtime)

    result = asyncio.run(
        graph.derive_session_id(
            {
                "user_id": "u1",
                "database": "kpi_data",
                "context": {"page_context": {"dict": {"session_id": "portal-session"}}},
            }
        )
    )

    assert result["session_id"] == "portal-session"


def test_derive_session_id_falls_back_to_database_and_user() -> None:
    runtime = AgentRuntime(
        settings=Settings(),
        memory=FakeMemory(),  # type: ignore[arg-type]
        schema_cache=FakeSchemaCache(),  # type: ignore[arg-type]
        redshift=FakeRedshift([QueryExecution(rows=[{"id": 1}], error=None)]),  # type: ignore[arg-type]
        sql_validator=SQLValidator(),
        retry_controller=RetryController(1),
        master_orchestrator=FakeMaster(False),  # type: ignore[arg-type]
        sql_generator=FakeGenerator(),  # type: ignore[arg-type]
        sql_corrector=FakeCorrector(),  # type: ignore[arg-type]
        final_answer=FakeFinalAnswer(),  # type: ignore[arg-type]
    )
    graph = KPIAnalyticsGraph(runtime)

    result = asyncio.run(
        graph.derive_session_id(
            {
                "user_id": "u1",
                "database": "kpi_data",
                "context": {"page_context": {"dict": {}}},
            }
        )
    )

    assert result["session_id"] == "kpi_data:u1"


def test_chat_memory_noops_without_mem_db_uri() -> None:
    service = ChatMemoryService(None)

    asyncio.run(service.init_db())
    asyncio.run(service.save_message("s1", "user", "hello"))
    history = asyncio.run(service.load_history("s1"))

    assert history == []

