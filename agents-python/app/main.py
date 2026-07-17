"""VaultWatch agents-python: FastAPI service hosting the multi-agent
fraud/security pipeline, a live WebSocket feed, and a background synthetic
transaction generator so the dashboard always has something to show."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis_asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import CaseStore, InMemoryCaseStore, PostgresCaseStore
from app.llm.provider import get_provider
from app.models import AgentEvent, Alert, SecurityEvent, Transaction
from app.orchestrator import Orchestrator
from app.prefilter import AnomalyPreFilter
from app.risk_engine import HttpRiskEngineClient
from app.synthetic import generate_demo_transaction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaultwatch.agents")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
state: dict[str, Any] = {}


async def broadcast_event(event: AgentEvent | Alert) -> None:
    await manager.broadcast(json.loads(event.model_dump_json()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    prefilter = AnomalyPreFilter()
    prefilter.fit()

    provider = get_provider(settings)
    logger.info("model provider live=%s mode=%s", provider.is_live, settings.mode)

    risk_engine = HttpRiskEngineClient(settings.engine_rust_url)

    case_store: CaseStore
    if settings.database_url:
        case_store = await PostgresCaseStore.connect(settings.database_url)
        logger.info("using PostgresCaseStore")
    else:
        case_store = InMemoryCaseStore()
        logger.info("DATABASE_URL not set - using InMemoryCaseStore")

    orchestrator = Orchestrator(
        risk_engine=risk_engine,
        prefilter=prefilter,
        provider=provider,
        haiku_model=settings.haiku_model,
        sonnet_model=settings.sonnet_model,
        event_sink=broadcast_event,
    )

    state["orchestrator"] = orchestrator
    state["case_store"] = case_store

    tasks = [
        asyncio.create_task(_security_event_listener(orchestrator)),
        asyncio.create_task(_synthetic_transaction_loop(orchestrator, case_store)),
    ]

    yield

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="VaultWatch Agents", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _security_event_listener(orchestrator: Orchestrator) -> None:
    try:
        client = redis_asyncio.from_url(settings.redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe("security.events")
        logger.info("subscribed to security.events on %s", settings.redis_url)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                payload = json.loads(message["data"])
                event = SecurityEvent(**payload)
                orchestrator.record_security_event(event)
                await manager.broadcast({"type": "security_event", **payload})
            except Exception:
                logger.exception("failed to process security event")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("security event listener unavailable (redis unreachable) - fusion alerts disabled")


async def _synthetic_transaction_loop(orchestrator: Orchestrator, case_store: CaseStore) -> None:
    """Generates a synthetic transaction every few seconds so the live feed
    always has activity, occasionally minting a deliberately risky one so
    the full escalation chain (through to compliance) gets exercised."""
    try:
        while True:
            await asyncio.sleep(random.uniform(4, 9))
            force_risky = random.random() < 0.3
            tx = Transaction(**generate_demo_transaction(force_risky=force_risky))
            try:
                result = await orchestrator.process_transaction(tx)
                await case_store.save(tx.id, tx.account_id, result.as_dict())
            except Exception:
                logger.exception("pipeline run failed for synthetic transaction %s", tx.id)
    except asyncio.CancelledError:
        raise


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/cases/recent")
async def recent_cases(limit: int = 50) -> list[dict[str, Any]]:
    return await state["case_store"].recent(limit)


@app.post("/v1/pipeline/run")
async def run_pipeline(force_risky: bool = False) -> dict[str, Any]:
    orchestrator: Orchestrator = state["orchestrator"]
    tx = Transaction(**generate_demo_transaction(force_risky=force_risky))
    result = await orchestrator.process_transaction(tx)
    await state["case_store"].save(tx.id, tx.account_id, result.as_dict())
    return {"transaction": tx.model_dump(mode="json"), **result.as_dict()}


WS_IDLE_PING_SECONDS = 20


@app.websocket("/v1/stream")
async def stream(ws: WebSocket) -> None:
    """The client never sends anything on this socket - it's server push
    only - so a plain `receive_text()` loop can leave a connection that
    dropped without a clean close handshake (e.g. a hard page navigation)
    sitting in ConnectionManager forever: it would only be noticed the next
    time something is broadcast and the send happens to fail, and some
    transports don't fail that send promptly. Pinging on an idle timeout
    turns a passive "wait for a broadcast to expose the dead socket" into
    an active liveness check, so ConnectionManager can't accumulate stale
    entries just from clients reloading the page.
    """
    await manager.connect(ws)
    try:
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=WS_IDLE_PING_SECONDS)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
    except Exception:
        # Covers WebSocketDisconnect (clean close) and anything else the
        # transport can raise for a connection that's gone bad; either way
        # the socket needs to come out of the connection set.
        manager.disconnect(ws)
