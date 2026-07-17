from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.final_answer import FinalAnswerAgent
from app.agents.master_orchestrator import MasterOrchestratorAgent
from app.agents.sql_corrector import SQLCorrectorAgent
from app.agents.sql_generator import SQLGeneratorAgent
from app.config import Settings, get_settings
from app.models import AgentGraphResult
from app.services.bedrock import BedrockService
from app.services.chat_memory import ChatMemoryService
from app.services.dashboard_context import DashboardContextService
from app.services.redshift import RedshiftService, is_schema_error
from app.services.result_formatter import format_query_result
from app.services.retry_controller import RetryController
from app.services.schema_cache import SchemaCache
from app.services.sql_validator import SQLValidator, SQLValidatorConfig
from app.state import AgentState

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END = "__end__"
    START = "__start__"
    StateGraph = None


@dataclass
class AgentRuntime:
    settings: Settings
    memory: ChatMemoryService
    schema_cache: SchemaCache
    redshift: RedshiftService
    sql_validator: SQLValidator
    retry_controller: RetryController
    master_orchestrator: MasterOrchestratorAgent
    sql_generator: SQLGeneratorAgent
    sql_corrector: SQLCorrectorAgent
    final_answer: FinalAnswerAgent
    dashboard_context: DashboardContextService = field(default_factory=DashboardContextService)


def build_runtime(settings: Settings | None = None) -> AgentRuntime:
    settings = settings or get_settings()
    bedrock = BedrockService(settings)
    redshift = RedshiftService(settings)
    schema_cache = SchemaCache(
        redshift,
        ttl_seconds=settings.schema_cache_ttl_seconds,
        max_tables_returned=settings.max_schema_tables_returned,
    )
    return AgentRuntime(
        settings=settings,
        memory=ChatMemoryService(settings.mem_db_uri),
        schema_cache=schema_cache,
        redshift=redshift,
        sql_validator=SQLValidator(
            SQLValidatorConfig(default_limit=settings.default_limit, max_limit=settings.max_limit)
        ),
        retry_controller=RetryController(settings.max_sql_retries),
        master_orchestrator=MasterOrchestratorAgent(bedrock, settings),
        sql_generator=SQLGeneratorAgent(bedrock, settings),
        sql_corrector=SQLCorrectorAgent(bedrock, settings),
        final_answer=FinalAnswerAgent(bedrock, settings),
        dashboard_context=DashboardContextService(),
    )


class KPIAnalyticsGraph:
    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime
        self._memory_initialized = False
        self._compiled = self._build_langgraph()

    def _build_langgraph(self) -> Any:
        if StateGraph is None:
            return None

        builder = StateGraph(AgentState)
        builder.add_node("derive_session_id", self.derive_session_id)
        builder.add_node("save_user_message", self.save_user_message)
        builder.add_node("load_chat_memory", self.load_chat_memory)
        builder.add_node("master_orchestrator", self.master_orchestrator)
        builder.add_node("save_orchestrator_decision", self.save_orchestrator_decision)
        builder.add_node("schema_retrieval", self.schema_retrieval)
        builder.add_node("sql_generator", self.sql_generator)
        builder.add_node("sql_validator", self.sql_validator)
        builder.add_node("sql_executor", self.sql_executor)
        builder.add_node("retry_controller", self.retry_controller)
        builder.add_node("sql_corrector", self.sql_corrector)
        builder.add_node("result_formatter", self.result_formatter)
        builder.add_node("final_answer_agent", self.final_answer_agent)
        builder.add_node("final_error_response", self.final_error_response)
        builder.add_node("save_final_response", self.save_final_response)

        builder.add_edge(START, "derive_session_id")
        builder.add_edge("derive_session_id", "save_user_message")
        builder.add_edge("save_user_message", "load_chat_memory")
        builder.add_edge("load_chat_memory", "master_orchestrator")
        builder.add_edge("master_orchestrator", "save_orchestrator_decision")
        builder.add_conditional_edges(
            "save_orchestrator_decision",
            self.route_after_orchestrator,
            {"database": "schema_retrieval", "direct": "final_answer_agent"},
        )
        builder.add_conditional_edges(
            "schema_retrieval",
            self.route_after_schema,
            {"generate": "sql_generator", "error": "final_error_response"},
        )
        builder.add_edge("sql_generator", "sql_validator")
        builder.add_conditional_edges(
            "sql_validator",
            self.route_after_validation,
            {"execute": "sql_executor", "retry": "retry_controller"},
        )
        builder.add_conditional_edges(
            "sql_executor",
            self.route_after_execution,
            {"format": "result_formatter", "retry": "retry_controller"},
        )
        builder.add_conditional_edges(
            "retry_controller",
            self.route_after_retry,
            {"correct": "sql_corrector", "error": "final_error_response"},
        )
        builder.add_edge("sql_corrector", "sql_validator")
        builder.add_edge("result_formatter", "final_answer_agent")
        builder.add_edge("final_answer_agent", "save_final_response")
        builder.add_edge("final_error_response", "save_final_response")
        builder.add_edge("save_final_response", END)
        return builder.compile()

    async def ainvoke(self, initial_state: AgentState) -> AgentState:
        if self._compiled is not None:
            return await self._compiled.ainvoke(initial_state)
        return await self._run_fallback(initial_state)

    async def _run_fallback(self, initial_state: AgentState) -> AgentState:
        state: AgentState = dict(initial_state)
        for node in (
            self.derive_session_id,
            self.save_user_message,
            self.load_chat_memory,
            self.master_orchestrator,
            self.save_orchestrator_decision,
        ):
            state.update(await node(state))

        if self.route_after_orchestrator(state) == "direct":
            state.update(await self.final_answer_agent(state))
            state.update(await self.save_final_response(state))
            return state

        state.update(await self.schema_retrieval(state))
        if self.route_after_schema(state) == "error":
            state.update(await self.final_error_response(state))
            state.update(await self.save_final_response(state))
            return state

        state.update(await self.sql_generator(state))
        while True:
            state.update(await self.sql_validator(state))
            if self.route_after_validation(state) == "retry":
                state.update(await self.retry_controller(state))
                if self.route_after_retry(state) == "correct":
                    state.update(await self.sql_corrector(state))
                    continue
                state.update(await self.final_error_response(state))
                state.update(await self.save_final_response(state))
                return state

            state.update(await self.sql_executor(state))
            if self.route_after_execution(state) == "retry":
                state.update(await self.retry_controller(state))
                if self.route_after_retry(state) == "correct":
                    state.update(await self.sql_corrector(state))
                    continue
                state.update(await self.final_error_response(state))
                state.update(await self.save_final_response(state))
                return state

            state.update(await self.result_formatter(state))
            state.update(await self.final_answer_agent(state))
            state.update(await self.save_final_response(state))
            return state

    async def derive_session_id(self, state: AgentState) -> dict[str, Any]:
        context = state.get("context", {})
        context = context if isinstance(context, dict) else {}
        page_context = context.get("page_context", {}) if isinstance(context, dict) else {}
        page_context_dict = page_context.get("dict") if isinstance(page_context, dict) else None
        session_id = None
        if isinstance(page_context_dict, dict):
            session_id = page_context_dict.get("session_id")
        database = state.get("database") or self.runtime.settings.redshift_database
        user_id = state.get("user_id") or "anonymous"
        # Attach the structural dashboard summary for the current portal route (if any) so the
        # orchestrator and SQL generator understand what the user is likely looking at.
        dashboard_context = self.runtime.dashboard_context.resolve(
            page_context if isinstance(page_context, dict) else {}
        )
        return {
            "session_id": session_id or f"{database}:{user_id}",
            "database": database,
            "retry_count": int(state.get("retry_count", 0) or 0),
            "max_sql_retries": self.runtime.settings.max_sql_retries,
            "context": {**context, "dashboard_context": dashboard_context},
        }

    async def save_user_message(self, state: AgentState) -> dict[str, Any]:
        await self._ensure_memory_initialized()
        await self.runtime.memory.save_message(
            session_id=str(state["session_id"]),
            user_id=state.get("user_id"),
            role="user",
            content=state.get("question", ""),
            metadata={
                "database": state.get("database"),
                "page_context": state.get("context", {}).get("page_context"),
            },
        )
        return {}

    async def load_chat_memory(self, state: AgentState) -> dict[str, Any]:
        await self._ensure_memory_initialized()
        history = await self.runtime.memory.load_history(str(state["session_id"]), limit=20)
        return {"chat_history": history, "memory_loaded": True}

    async def master_orchestrator(self, state: AgentState) -> dict[str, Any]:
        context = state.get("context", {})
        page_context = context.get("page_context", {}) if isinstance(context, dict) else {}
        dashboard_context = context.get("dashboard_context", {}) if isinstance(context, dict) else {}
        result = await self.runtime.master_orchestrator.route(
            question=state.get("question", ""),
            chat_history=state.get("chat_history", []),
            page_context=page_context,
            dashboard_context=dashboard_context,
        )
        return {
            "needs_database": bool(result.get("needs_database")),
            "route_reason": result.get("route_reason", ""),
            "schema_search_terms": result.get("schema_search_terms", []),
        }

    async def save_orchestrator_decision(self, state: AgentState) -> dict[str, Any]:
        await self.runtime.memory.save_message(
            session_id=str(state["session_id"]),
            user_id=state.get("user_id"),
            role="system",
            content=state.get("route_reason", ""),
            metadata={
                "event": "orchestrator_decision",
                "needs_database": state.get("needs_database"),
                "schema_search_terms": state.get("schema_search_terms", []),
            },
        )
        return {}

    async def schema_retrieval(self, state: AgentState) -> dict[str, Any]:
        try:
            context = await self.runtime.schema_cache.get_schema_context(
                search_terms=state.get("schema_search_terms", []),
                database=state.get("database") or self.runtime.settings.redshift_database,
                schema_name=self.runtime.settings.redshift_schema,
                force_refresh=bool(state.get("force_schema_refresh", False)),
            )
        except Exception as exc:
            return {
                "schema_context": {"tables": [], "metadata": {}},
                "query_error": f"Could not load schema context: {str(exc)[:500]}",
                "force_schema_refresh": False,
            }
        if not context.get("tables"):
            return {
                "schema_context": context,
                "query_error": "No relevant schema was found for this question.",
                "force_schema_refresh": False,
            }
        return {"schema_context": context, "query_error": None, "force_schema_refresh": False}

    async def sql_generator(self, state: AgentState) -> dict[str, Any]:
        context = state.get("context", {})
        page_context = context.get("page_context", {}) if isinstance(context, dict) else {}
        dashboard_context = context.get("dashboard_context", {}) if isinstance(context, dict) else {}
        result = await self.runtime.sql_generator.generate(
            question=state.get("question", ""),
            chat_history=state.get("chat_history", []),
            schema_context=state.get("schema_context", {}),
            page_context=page_context,
            dashboard_context=dashboard_context,
        )
        sql = result.get("sql", "")
        if not sql:
            return {
                "generated_sql": "",
                "sql_assumptions": result.get("assumptions", []),
                "query_error": "SQL Generator did not return SQL.",
            }
        return {
            "generated_sql": sql,
            "sql_assumptions": result.get("assumptions", []),
            "query_error": None,
        }

    async def sql_validator(self, state: AgentState) -> dict[str, Any]:
        retry_count = int(state.get("retry_count", 0) or 0)
        candidate = state.get("corrected_sql") if retry_count > 0 else state.get("generated_sql")
        result = self.runtime.sql_validator.validate(candidate)
        if not result.ok:
            return {"validated_sql": "", "query_error": f"SQL validation failed: {result.error}"}
        return {"validated_sql": result.sql, "query_error": None}

    async def sql_executor(self, state: AgentState) -> dict[str, Any]:
        validated_sql = state.get("validated_sql")
        if not validated_sql:
            return {"query_result": None, "query_error": "No validated SQL was available for execution."}

        result = await self.runtime.redshift.execute_sql(validated_sql)
        if result.error:
            updates: dict[str, Any] = {"query_result": None, "query_error": result.error}
            if is_schema_error(result.error):
                refreshed = await self.runtime.schema_cache.get_schema_context(
                    search_terms=state.get("schema_search_terms", []),
                    database=state.get("database") or self.runtime.settings.redshift_database,
                    schema_name=self.runtime.settings.redshift_schema,
                    force_refresh=True,
                )
                updates["schema_context"] = refreshed
            return updates
        return {
            "query_result": result.rows or [],
            "query_error": None,
            "metadata": {"query_truncated": result.truncated},
        }

    async def retry_controller(self, state: AgentState) -> dict[str, Any]:
        return self.runtime.retry_controller.apply(state)

    async def sql_corrector(self, state: AgentState) -> dict[str, Any]:
        failed_sql = state.get("validated_sql") or state.get("corrected_sql") or state.get("generated_sql") or ""
        result = await self.runtime.sql_corrector.correct(
            question=state.get("question", ""),
            chat_history=state.get("chat_history", []),
            schema_context=state.get("schema_context", {}),
            failed_sql=failed_sql,
            query_error=state.get("query_error") or "",
            assumptions=state.get("sql_assumptions", []),
            retry_count=int(state.get("retry_count", 0) or 0),
            max_sql_retries=self.runtime.settings.max_sql_retries,
        )
        corrected_sql = result.get("corrected_sql", "")
        return {
            "corrected_sql": corrected_sql,
            "correction_reason": result.get("correction_reason", ""),
            "query_error": None if corrected_sql else "SQL Corrector did not return SQL.",
        }

    async def result_formatter(self, state: AgentState) -> dict[str, Any]:
        return format_query_result(state.get("query_result"), max_preview_rows=20)

    async def final_answer_agent(self, state: AgentState) -> dict[str, Any]:
        answer = await self.runtime.final_answer.synthesize({**state, "ok": True})
        return {"ok": True, "final_answer": answer}

    async def final_error_response(self, state: AgentState) -> dict[str, Any]:
        final_error = "I could not complete the query after the configured retry limit."
        answer = (
            "## Answer\n\n"
            f"{final_error} Please refine the question or confirm the relevant KPI/table."
        )
        return {
            "ok": False,
            "final_error": final_error,
            "final_answer": answer,
            "retry_count": int(state.get("retry_count", 0) or 0),
            "max_sql_retries": self.runtime.settings.max_sql_retries,
            "query_error": state.get("query_error"),
            "validated_sql": state.get("validated_sql"),
        }

    async def save_final_response(self, state: AgentState) -> dict[str, Any]:
        await self.runtime.memory.save_message(
            session_id=str(state["session_id"]),
            user_id=state.get("user_id"),
            role="assistant",
            content=state.get("final_answer") or state.get("final_error") or "",
            metadata={
                "event": "final_response",
                "ok": state.get("ok"),
                "validated_sql": state.get("validated_sql"),
                "corrected_sql": state.get("corrected_sql"),
                "row_count": state.get("row_count"),
                "query_error": state.get("query_error"),
                "retry_count": state.get("retry_count"),
            },
        )
        return {"memory_saved": True}

    @staticmethod
    def route_after_orchestrator(state: AgentState) -> str:
        return "database" if state.get("needs_database") else "direct"

    @staticmethod
    def route_after_schema(state: AgentState) -> str:
        if state.get("query_error"):
            return "error"
        return "generate"

    @staticmethod
    def route_after_validation(state: AgentState) -> str:
        return "retry" if state.get("query_error") else "execute"

    @staticmethod
    def route_after_execution(state: AgentState) -> str:
        return "retry" if state.get("query_error") else "format"

    @staticmethod
    def route_after_retry(state: AgentState) -> str:
        return "correct" if state.get("can_retry") else "error"

    def result_from_state(self, state: AgentState) -> AgentGraphResult:
        return AgentGraphResult(
            ok=bool(state.get("ok", False)),
            answer=state.get("final_answer") or state.get("final_error") or "",
            needs_database=bool(state.get("needs_database", False)),
            sql_used=state.get("validated_sql") or None,
            row_count=state.get("row_count"),
            preview_markdown=state.get("preview_markdown"),
            error=state.get("final_error") or state.get("query_error"),
            assumptions=state.get("sql_assumptions", []),
            metadata={
                "session_id": state.get("session_id"),
                "database": state.get("database"),
                "retry_count": state.get("retry_count", 0),
                "max_sql_retries": state.get("max_sql_retries", self.runtime.settings.max_sql_retries),
                "route_reason": state.get("route_reason"),
                "schema_search_terms": state.get("schema_search_terms", []),
                "correction_reason": state.get("correction_reason"),
            },
        )

    async def _ensure_memory_initialized(self) -> None:
        if self._memory_initialized:
            return
        await self.runtime.memory.init_db()
        self._memory_initialized = True


_default_graph: KPIAnalyticsGraph | None = None


def get_default_graph() -> KPIAnalyticsGraph:
    global _default_graph
    if _default_graph is None:
        _default_graph = KPIAnalyticsGraph(build_runtime())
    return _default_graph


def set_default_graph_for_tests(graph: KPIAnalyticsGraph | None) -> None:
    global _default_graph
    _default_graph = graph
