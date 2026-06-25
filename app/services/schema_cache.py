from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Protocol


class SchemaMetadataLoader(Protocol):
    async def load_full_schema(self, database: str, schema_name: str | None = None) -> dict[str, Any]:
        ...


@dataclass
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


class InMemorySchemaCacheStore:
    def __init__(self) -> None:
        self._items: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._items.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._items[key] = _CacheEntry(value=value, expires_at=time.time() + ttl_seconds)


class SchemaCache:
    def __init__(
        self,
        loader: SchemaMetadataLoader,
        *,
        ttl_seconds: int = 86400,
        max_tables_returned: int = 25,
        store: InMemorySchemaCacheStore | None = None,
    ) -> None:
        self.loader = loader
        self.ttl_seconds = ttl_seconds
        self.max_tables_returned = max_tables_returned
        self.store = store or InMemorySchemaCacheStore()

    @staticmethod
    def cache_key(database: str, schema_name: str | None) -> str:
        schema_part = schema_name or "all"
        return f"agent:schema:redshift:{database}:{schema_part}"

    async def get_schema_context(
        self,
        search_terms: list[str],
        database: str,
        schema_name: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        key = self.cache_key(database, schema_name)
        cached = None if force_refresh else self.store.get(key)
        cache_hit = cached is not None

        if cached is None:
            snapshot = await self.loader.load_full_schema(database=database, schema_name=schema_name)
            cached = self._build_envelope(snapshot, database, schema_name)
            self.store.set(key, cached, self.ttl_seconds)

        filtered = self._filter_tables(cached.get("tables", []), search_terms)
        return {
            "tables": filtered,
            "metadata": {
                "cache_hit": cache_hit,
                "cached_at": cached.get("cached_at"),
                "force_refresh": force_refresh,
                "search_terms": search_terms,
                "matched_table_count": len(filtered),
                "database": database,
                "schema": schema_name,
            },
        }

    @staticmethod
    def _build_envelope(snapshot: dict[str, Any], database: str, schema_name: str | None) -> dict[str, Any]:
        return {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "database": database,
            "schema": schema_name,
            "tables": snapshot.get("tables", []),
        }

    def _filter_tables(self, tables: list[dict[str, Any]], search_terms: list[str]) -> list[dict[str, Any]]:
        normalized_terms = [term.strip().lower() for term in search_terms if term and term.strip()]
        if not normalized_terms:
            return tables[: self.max_tables_returned]

        matches: list[tuple[int, dict[str, Any]]] = []
        for table in tables:
            score = self._score_table(table, normalized_terms)
            if score > 0:
                matches.append((score, table))

        matches.sort(key=lambda item: (-item[0], item[1].get("table_schema", ""), item[1].get("table_name", "")))
        return [table for _, table in matches[: self.max_tables_returned]]

    @staticmethod
    def _score_table(table: dict[str, Any], terms: list[str]) -> int:
        table_name = str(table.get("table_name", "")).lower()
        schema = str(table.get("table_schema", "")).lower()
        description = str(table.get("description", "")).lower()
        columns = table.get("columns", []) or []
        column_text = " ".join(str(column.get("column_name", "")).lower() for column in columns)
        searchable = f"{schema} {table_name} {description} {column_text}"

        score = 0
        for term in terms:
            compact = term.replace("-", "_").replace(" ", "_")
            if term in searchable or compact in searchable:
                score += 1
            if table_name.startswith(compact[:3]):
                score += 1
        return score

