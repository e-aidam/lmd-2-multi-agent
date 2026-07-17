from __future__ import annotations

import re
from typing import Any

from app.agents.prompts import load_prompt
from app.config import Settings
from app.services.bedrock import BedrockService


class MasterOrchestratorAgent:
    def __init__(self, bedrock: BedrockService, settings: Settings) -> None:
        self.bedrock = bedrock
        self.settings = settings

    async def route(
        self,
        *,
        question: str,
        chat_history: list[dict[str, str]],
        page_context: dict[str, Any],
        dashboard_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dashboard_context = dashboard_context or {}
        payload = {
            "question": question,
            "chat_history": chat_history,
            "page_context": page_context,
            "dashboard_context": dashboard_context,
        }
        try:
            result = await self.bedrock.generate_json(
                self.settings.bedrock_model_master,
                load_prompt("master_orchestrator.md"),
                payload,
            )
            return {
                "needs_database": bool(result.get("needs_database")),
                "needs_visualization": bool(result.get("needs_visualization")),
                "route_reason": str(result.get("route_reason") or "Routing decision produced by Master Orchestrator."),
                "schema_search_terms": _clean_terms(result.get("schema_search_terms")),
            }
        except Exception:
            return self._heuristic_route(question, page_context, dashboard_context)

    @staticmethod
    def _heuristic_route(
        question: str,
        page_context: dict[str, Any],
        dashboard_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lowered = question.lower()
        db_markers = {
            "total",
            "count",
            "trend",
            "compare",
            "comparison",
            "quarter",
            "fy",
            "country",
            "countries",
            "kpi",
            "metric",
            "metrics",
            "service",
            "delivery",
            "dashboard",
            "malawi",
            "narrative",
            "performance",
        }
        no_db_markers = ("what is", "define", "explain", "how does", "help me understand")
        needs_database = any(marker in lowered for marker in db_markers) and not lowered.startswith(no_db_markers)
        viz_markers = ("chart", "graph", "plot", "trend", "compare", "over time", "visualize", "visualise", "visualization")
        needs_visualization = needs_database and any(marker in lowered for marker in viz_markers)
        terms = extract_search_terms(question)
        terms.extend(extract_search_terms(_stringify_context(page_context)))
        terms.extend(extract_search_terms(_stringify_context(dashboard_context or {})))
        return {
            "needs_database": needs_database,
            "needs_visualization": needs_visualization,
            "route_reason": (
                "The question appears to ask for KPI data from the warehouse."
                if needs_database
                else "The question can be answered without querying the database."
            ),
            "schema_search_terms": _clean_terms(terms),
        }


def extract_search_terms(text: str) -> list[str]:
    stopwords = {
        "about",
        "across",
        "after",
        "before",
        "between",
        "count",
        "data",
        "database",
        "during",
        "from",
        "give",
        "last",
        "latest",
        "many",
        "metric",
        "metrics",
        "over",
        "please",
        "query",
        "show",
        "table",
        "that",
        "this",
        "total",
        "what",
        "when",
        "where",
        "which",
        "with",
        "year",
    }
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower())
    return [token for token in tokens if token not in stopwords]


def _clean_terms(value: Any) -> list[str]:
    terms = value if isinstance(value, list) else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for term in terms:
        text = str(term).strip().lower()
        if text and text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned[:12]


def _stringify_context(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_stringify_context(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_stringify_context(item) for item in value)
    return "" if value is None else str(value)

