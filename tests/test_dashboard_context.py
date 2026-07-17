from __future__ import annotations

from app.agents.master_orchestrator import MasterOrchestratorAgent
from app.services.dashboard_context import DashboardContextService


def test_resolve_returns_entry_for_known_route() -> None:
    service = DashboardContextService()

    entry = service.resolve({"dict": {"route": "malawi", "session_id": "s1"}, "xml": None})

    assert entry["program"] == "Malawi"
    assert entry["route"] == "malawi"
    assert "Cross Cutting" in entry["theory_of_change_levels"]
    assert entry["kpis_by_level"]  # non-empty real KPI lists


def test_for_route_normalizes_separators_and_pathnames() -> None:
    service = DashboardContextService()

    # Hyphen/space variants of "sierra_leone" resolve to the same entry.
    assert service.for_route("sierra-leone")["program"] == "Sierra Leone"
    assert service.for_route("Sierra Leone")["program"] == "Sierra Leone"
    # Full pathname resolves via its last segment; "global-scale" keeps its hyphen key.
    assert service.resolve({"dict": {"pathname": "/kpi-dashboard/global-scale"}})["program"] == "Global"


def test_resolve_unknown_or_missing_route_is_empty() -> None:
    service = DashboardContextService()

    assert service.resolve({"dict": {"route": "atlantis"}}) == {}
    assert service.resolve({"dict": {"session_id": "s1"}}) == {}
    assert service.resolve({"dict": None}) == {}
    assert service.resolve({}) == {}


def test_missing_fixture_degrades_to_empty(tmp_path) -> None:
    service = DashboardContextService(path=tmp_path / "does_not_exist.json")

    assert service.routes == []
    assert service.for_route("malawi") == {}


def test_heuristic_router_folds_dashboard_terms_into_search_terms() -> None:
    service = DashboardContextService()
    dashboard_context = service.for_route("malawi")

    # page_context intentionally carries no "malawi" signal, so its presence in the search
    # terms can only come from the dashboard context being folded in.
    result = MasterOrchestratorAgent._heuristic_route(
        "Show KPI metrics",
        {"dict": {"session_id": "s1"}, "xml": None},
        dashboard_context,
    )

    assert result["needs_database"] is True
    assert "malawi" in result["schema_search_terms"]
