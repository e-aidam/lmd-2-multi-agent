import asyncio

from app.services.schema_cache import SchemaCache


class FakeLoader:
    def __init__(self) -> None:
        self.calls = 0

    async def load_full_schema(self, database: str, schema_name: str | None = None) -> dict:
        self.calls += 1
        return {
            "tables": [
                {
                    "table_schema": "public",
                    "table_name": "mlw_upskill_training",
                    "columns": [
                        {"column_name": "country", "data_type": "varchar", "ordinal_position": 1},
                        {"column_name": "fy_q", "data_type": "varchar", "ordinal_position": 2},
                    ],
                },
                {
                    "table_schema": "public",
                    "table_name": "finance_summary",
                    "columns": [
                        {"column_name": "amount", "data_type": "integer", "ordinal_position": 1},
                    ],
                },
            ]
        }


def test_schema_cache_filters_expected_structure() -> None:
    loader = FakeLoader()
    cache = SchemaCache(loader, ttl_seconds=86400, max_tables_returned=25)

    result = asyncio.run(cache.get_schema_context(["training", "chw"], "kpi_data", "public"))

    assert loader.calls == 1
    assert result["tables"][0]["table_name"] == "mlw_upskill_training"
    assert result["tables"][0]["columns"][0]["column_name"] == "country"
    assert result["metadata"]["cache_hit"] is False


def test_schema_cache_hits_cached_snapshot() -> None:
    loader = FakeLoader()
    cache = SchemaCache(loader, ttl_seconds=86400, max_tables_returned=25)

    asyncio.run(cache.get_schema_context(["training"], "kpi_data", "public"))
    result = asyncio.run(cache.get_schema_context(["finance"], "kpi_data", "public"))

    assert loader.calls == 1
    assert result["metadata"]["cache_hit"] is True
    assert result["tables"][0]["table_name"] == "finance_summary"


def test_schema_cache_force_refresh() -> None:
    loader = FakeLoader()
    cache = SchemaCache(loader, ttl_seconds=86400, max_tables_returned=25)

    asyncio.run(cache.get_schema_context(["training"], "kpi_data", "public"))
    asyncio.run(cache.get_schema_context(["training"], "kpi_data", "public", force_refresh=True))

    assert loader.calls == 2


def test_schema_cache_empty_matches() -> None:
    loader = FakeLoader()
    cache = SchemaCache(loader, ttl_seconds=86400, max_tables_returned=25)

    result = asyncio.run(cache.get_schema_context(["nonexistent"], "kpi_data", "public"))

    assert result["tables"] == []

