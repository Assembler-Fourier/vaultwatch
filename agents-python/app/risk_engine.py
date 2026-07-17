"""Client for engine-rust's deterministic /v1/score endpoint - the stage
that runs before either the ML pre-filter or any Claude call."""

from __future__ import annotations

from typing import Protocol

import httpx

from app.models import RuleEngineVerdict, ScoringContext, Transaction


class RiskEngineClient(Protocol):
    async def score(self, tx: Transaction, ctx: ScoringContext) -> RuleEngineVerdict: ...


class HttpRiskEngineClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=5.0)

    async def score(self, tx: Transaction, ctx: ScoringContext) -> RuleEngineVerdict:
        payload = {
            "transaction": tx.model_dump(mode="json"),
            "context": ctx.model_dump(mode="json"),
        }
        response = await self._client.post(f"{self._base_url}/v1/score", json=payload)
        response.raise_for_status()
        return RuleEngineVerdict(**response.json())
