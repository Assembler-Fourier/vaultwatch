"""Case/alert persistence.

Mirrors gateway-go's graceful-degradation pattern: if DATABASE_URL isn't
set, we fall back to an in-memory store instead of failing to start, which
is what lets the whole stack run with `docker compose up` and no manual
provisioning step.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any, Protocol

import asyncpg


class CaseStore(Protocol):
    async def save(self, transaction_id: str, account_id: str, result: dict[str, Any]) -> None: ...
    async def recent(self, limit: int = 50) -> list[dict[str, Any]]: ...


class InMemoryCaseStore:
    def __init__(self, capacity: int = 500):
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)

    async def save(self, transaction_id: str, account_id: str, result: dict[str, Any]) -> None:
        self._items.appendleft(
            {"transaction_id": transaction_id, "account_id": account_id, "result": result}
        )

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._items)[:limit]


class PostgresCaseStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def connect(cls, database_url: str) -> "PostgresCaseStore":
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    id BIGSERIAL PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    result JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_cases_created_at ON cases (created_at DESC);
                """
            )
        return cls(pool)

    async def save(self, transaction_id: str, account_id: str, result: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO cases (transaction_id, account_id, result) VALUES ($1, $2, $3)",
                transaction_id,
                account_id,
                json.dumps(result),
            )

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT transaction_id, account_id, result FROM cases ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [
            {"transaction_id": r["transaction_id"], "account_id": r["account_id"], "result": json.loads(r["result"])}
            for r in rows
        ]
