"""VaultWatch agents-python: FastAPI service hosting the multi-agent
fraud/security pipeline, a live WebSocket feed, and a background synthetic
transaction generator so the dashboard always has something to show."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis_asyncio
from fastapi import FastAPI, WebSocket, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from app.audit import AuditClient
from app.demo import DemoRequest, create_scenario, balanced_batch
from app.reports import render_report
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

    audit = AuditClient(settings.engine_rust_url)
    orchestrator = Orchestrator(
        risk_engine=risk_engine,
        prefilter=prefilter,
        provider=provider,
        haiku_model=settings.haiku_model,
        sonnet_model=settings.sonnet_model,
        event_sink=broadcast_event,
        audit=audit,
    )

    state["orchestrator"] = orchestrator
    state["case_store"] = case_store
    state["provider"] = provider

    tasks = [
        asyncio.create_task(_security_event_listener(orchestrator)),

    ]

    if os.getenv("AUTO_GENERATE", "true").lower() == "true":
        tasks.append(asyncio.create_task(_synthetic_transaction_loop(orchestrator, case_store)))

    yield

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await audit.client.aclose()
    await risk_engine._client.aclose()
    if isinstance(case_store, PostgresCaseStore):
        await case_store._pool.close()


app = FastAPI(title="VaultWatch Agents", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _security_event_listener(orchestrator: Orchestrator) -> None:
    # A Redis restart must not silently disable correlation until Python restarts.
    while True:
        state["security_feed"] = "reconnecting"
        try:
            async with redis_asyncio.from_url(settings.redis_url) as client:
                async with client.pubsub() as pubsub:
                    await pubsub.subscribe("security.events")
                    async for message in pubsub.listen():
                        if message["type"] == "subscribe":
                            state["security_feed"] = "online"
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
            state["security_feed"] = "reconnecting"
            logger.warning("security event listener disconnected; retrying in two seconds")
        await asyncio.sleep(2)


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
async def recent_cases(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await state["case_store"].recent(limit)


@app.post("/v1/pipeline/run")
async def run_pipeline(force_risky: bool = False) -> dict[str, Any]:
    orchestrator: Orchestrator = state["orchestrator"]
    tx = Transaction(**generate_demo_transaction(force_risky=force_risky))
    result = await orchestrator.process_transaction(tx)
    await state["case_store"].save(tx.id, tx.account_id, result.as_dict())
    await manager.broadcast({"type": "case_saved", "transaction_id": tx.id})
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


@app.get("/v1/status")
async def status() -> dict:
    services = {"python": "online", "security_feed": state.get("security_feed", "reconnecting")}
    async with httpx.AsyncClient(timeout=2) as client:
        async def check(name, url):
            try:
                response = await client.get(url)
                services[name] = "online" if response.is_success else "unavailable"
            except httpx.HTTPError:
                services[name] = "unavailable"
        await asyncio.gather(check("rust", settings.engine_rust_url + "/healthz"),
                             check("go", os.getenv("GATEWAY_GO_URL", "http://gateway-go:8080") + "/healthz"))
    try:
        await state["case_store"].recent(1)
        services["postgres"] = "online" if settings.database_url else "not configured"
    except Exception:
        services["postgres"] = "unavailable"
    try:
        async with redis_asyncio.from_url(settings.redis_url) as redis:
            await redis.ping()
        services["redis"] = "online"
    except Exception:
        services["redis"] = "unavailable"
    return {"model_mode": "live" if state["provider"].is_live else "replay", "services": services,
            "storage": "postgres" if settings.database_url else "memory", "checked_at": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/audit")
async def audit_status() -> dict:
    try:
        verification = await state["orchestrator"]._audit.verify()
        return {"verify": verification, "checked_at": datetime.now(timezone.utc).isoformat()}
    except Exception as error:
        raise HTTPException(503, "Audit service unavailable") from error


@app.post("/v1/demo/run")
async def demo_run(request: DemoRequest) -> dict:
    if os.getenv("DEMO_CONTROLS", "false").lower() != "true":
        raise HTTPException(404, "Local demo controls are disabled")
    try:
        tx, ctx, review = await create_scenario(request, state["orchestrator"])
        result = await state["orchestrator"].process_transaction(tx, ctx, review)
        await state["case_store"].save(tx.id, tx.account_id, result.as_dict())
        await manager.broadcast({"type": "case_saved", "transaction_id": tx.id})
        return {"transaction": tx.model_dump(mode="json"), **result.as_dict()}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except (httpx.HTTPError, RuntimeError) as error:
        raise HTTPException(503, "Scenario could not finish. Check the service indicators and retry; no case was reported as complete.") from error


@app.post("/v1/demo/batch")
async def demo_batch() -> dict:
    if os.getenv("DEMO_CONTROLS", "false").lower() != "true":
        raise HTTPException(404, "Local demo controls are disabled")
    if state["provider"].is_live:
        raise HTTPException(409, "Balanced batches require replay mode")
    batch_id = "batch_" + uuid4().hex[:12]
    results, failures = [], []
    # Sequential processing keeps the demo readable and bounds service pressure.
    for index, request in enumerate(balanced_batch(), 1):
        try:
            result = await demo_run(request)
            results.append(result)
        except Exception:
            logger.exception("batch %s item %s failed", batch_id, index)
            failures.append({"index": index, "scenario": request.scenario,
                             "message": "Not confirmed complete. Check recent cases and service status before rerunning."})
        await manager.broadcast({"type": "batch_progress", "batch_id": batch_id,
                                 "completed": index, "total": 10})
    return {"batch_id": batch_id, "requested": 10, "mix": {"normal": 5, "review": 2, "unusual": 1, "sanctions": 1, "takeover": 1},
            "results": results, "failures": failures}


async def load_case(transaction_id: str) -> dict:
    record = await state["case_store"].get(transaction_id)
    if not record:
        raise HTTPException(404, "Case not found")
    return record


@app.get("/v1/cases/{transaction_id}")
async def case_detail(transaction_id: str) -> dict:
    return await load_case(transaction_id)


@app.get("/v1/cases/{transaction_id}/report.json")
async def json_report(transaction_id: str):
    record = await load_case(transaction_id)
    return JSONResponse(record, headers={"Content-Disposition": 'attachment; filename="vaultwatch-report.json"'})


@app.get("/v1/cases/{transaction_id}/report", response_class=HTMLResponse)
async def printable_report(transaction_id: str):
    record = await load_case(transaction_id)
    try:
        verification = await audit_status()
    except HTTPException:
        verification = {"status": "unavailable", "verify": None}
    return HTMLResponse(render_report(record, verification))
