from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import asyncio
from typing import Any

from app.config import Settings


SCHEMA_METADATA_SQL = """
SELECT
    table_schema,
    table_name,
    column_name,
    data_type,
    ordinal_position
FROM information_schema.columns
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_schema, table_name, ordinal_position
""".strip()


@dataclass(frozen=True)
class QueryExecution:
    rows: list[dict[str, Any]] | None
    error: str | None
    truncated: bool = False


def is_schema_error(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in (
            "relation does not exist",
            "column does not exist",
            "schema does not exist",
            "undefined_table",
            "undefined_column",
        )
    )


class RedshiftService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute_sql(self, sql: str) -> QueryExecution:
        return await asyncio.to_thread(self._execute_sql_sync, sql)

    async def load_full_schema(self, database: str, schema_name: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._load_full_schema_sync, database, schema_name)

    def _connect(self) -> Any:
        if not all(
            [
                self.settings.redshift_host,
                self.settings.redshift_user,
                self.settings.redshift_password,
            ]
        ):
            raise RuntimeError("Redshift connection settings are incomplete.")
        try:
            import redshift_connector
        except ImportError as exc:
            raise RuntimeError("redshift_connector package is not installed.") from exc

        return redshift_connector.connect(
            host=self.settings.redshift_host,
            port=self.settings.redshift_port,
            database=self.settings.redshift_database,
            user=self.settings.redshift_user,
            password=self.settings.redshift_password,
            timeout=self.settings.query_timeout_seconds,
        )

    def _execute_sql_sync(self, sql: str) -> QueryExecution:
        connection = None
        try:
            connection = self._connect()
            cursor = connection.cursor()
            try:
                timeout_ms = self.settings.query_timeout_seconds * 1000
                cursor.execute(f"SET statement_timeout TO {timeout_ms}")
            except Exception:
                pass
            cursor.execute(sql)
            columns = [description[0] for description in cursor.description or []]
            raw_rows = cursor.fetchmany(self.settings.max_limit + 1)
            truncated = len(raw_rows) > self.settings.max_limit
            rows = [
                {column: _jsonable(value) for column, value in zip(columns, row, strict=False)}
                for row in raw_rows[: self.settings.max_limit]
            ]
            return QueryExecution(rows=rows, error=None, truncated=truncated)
        except Exception as exc:
            return QueryExecution(rows=None, error=_safe_error(exc))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def _load_full_schema_sync(self, database: str, schema_name: str | None = None) -> dict[str, Any]:
        if database != self.settings.redshift_database:
            raise RuntimeError(f"Database '{database}' is not configured.")

        sql = SCHEMA_METADATA_SQL
        connection = None
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
        except Exception as exc:
            raise RuntimeError(_safe_error(exc)) from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

        tables: dict[tuple[str, str], dict[str, Any]] = {}
        for table_schema, table_name, column_name, data_type, ordinal_position in rows:
            if schema_name and table_schema != schema_name:
                continue
            key = (table_schema, table_name)
            table = tables.setdefault(
                key,
                {
                    "table_schema": table_schema,
                    "table_name": table_name,
                    "columns": [],
                },
            )
            table["columns"].append(
                {
                    "column_name": column_name,
                    "data_type": data_type,
                    "ordinal_position": ordinal_position,
                }
            )

        return {"tables": list(tables.values())}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        text = type(exc).__name__
    return text[:1000]

