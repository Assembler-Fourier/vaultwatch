"""Persist processing evidence to the Rust hash chain. Never pretend failed writes passed."""

from typing import Any

import httpx


class AuditClient:
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10)

    async def append(
        self, transaction_id: str, event_type: str, payload: dict[str, Any]
    ) -> dict:
        response = await self.client.post(
            "/v1/audit/append",
            json={
                "event_type": event_type,
                "subject_id": transaction_id,
                "payload": payload,
            },
        )
        response.raise_for_status()
        return response.json()

    async def verify(self) -> dict:
        response = await self.client.get("/v1/audit/verify")
        response.raise_for_status()
        return response.json()
