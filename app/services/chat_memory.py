from __future__ import annotations

from typing import Any
import json


class ChatMemoryService:
    def __init__(self, mem_db_uri: str | None) -> None:
        self.mem_db_uri = mem_db_uri
        self._pool: Any = None

    @property
    def enabled(self) -> bool:
        return bool(self.mem_db_uri)

    async def init_db(self) -> None:
        if not self.enabled:
            return
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_chat_memory (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_chat_memory_session_created
                ON agent_chat_memory (session_id, created_at DESC)
                """
            )

    async def load_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        if not self.enabled:
            return []
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT role, content
                FROM agent_chat_memory
                WHERE session_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        pool = await self._get_pool()
        metadata_json = json.dumps(metadata or {})
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO agent_chat_memory (session_id, user_id, role, content, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                session_id,
                user_id,
                role,
                content,
                metadata_json,
            )

    async def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError("asyncpg package is required for MEM_DB_URI chat memory.") from exc
        self._pool = await asyncpg.create_pool(self.mem_db_uri)
        return self._pool

