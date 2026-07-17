from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DASHBOARD_CONTEXT_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard_context.json"


class DashboardContextService:
    """Loads structured, per-dashboard summaries (KPIs, chart types, filters) keyed by route slug.

    The summaries are checked into this repo at ``app/data/dashboard_context.json`` and mirror the
    KPI dashboard pages in the separate Next.js portal repo. Loading is best-effort: a missing or
    invalid fixture yields an empty map rather than raising, so the agent degrades gracefully.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DASHBOARD_CONTEXT_PATH
        self._data = self._load(self._path)

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        # Drop metadata keys (prefixed with "_") so only route entries remain.
        return {key: value for key, value in raw.items() if not key.startswith("_") and isinstance(value, dict)}

    @property
    def routes(self) -> list[str]:
        return list(self._data.keys())

    def for_route(self, route: str | None) -> dict[str, Any]:
        """Return a copy of the dashboard summary for a route slug, or ``{}`` if unknown."""
        slug = self._normalize_route(route)
        if slug is None:
            return {}
        entry = self._data.get(slug)
        return dict(entry) if isinstance(entry, dict) else {}

    def resolve(self, page_context: dict[str, Any]) -> dict[str, Any]:
        """Resolve the dashboard summary from a ``{"dict": <frontend payload>, "xml": ...}`` envelope.

        Looks for the route slug under the frontend payload's ``route`` key (falling back to
        ``page``/``pathname``/``path``). Returns ``{}`` when no known dashboard route is present.
        """
        payload = page_context.get("dict") if isinstance(page_context, dict) else None
        if not isinstance(payload, dict):
            return {}
        for key in ("route", "page", "pathname", "path"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                entry = self.for_route(value)
                if entry:
                    return entry
        return {}

    @staticmethod
    def _normalize_route(route: str | None) -> str | None:
        if not isinstance(route, str):
            return None
        slug = route.strip().lower()
        if not slug:
            return None
        # Accept full pathnames like "/kpi-dashboard/malawi" by taking the last non-empty segment.
        slug = slug.strip("/").split("/")[-1]
        # Normalize separators so "sierra-leone" / "sierra leone" match the "sierra_leone" slug.
        slug = slug.replace(" ", "_").replace("-", "_")
        # "global_scale" is stored with a hyphen; map the underscore form back.
        if slug == "global_scale":
            return "global-scale"
        return slug
