"""The pipeline orchestrator: rules -> ML pre-filter -> Haiku triage ->
Sonnet investigation -> Sonnet compliance drafting, with early exits at
every stage, plus fusion against account-security events from gateway-go.

This is deliberately a plain async function pipeline, not a framework: the
whole point of the architecture is legible cost/latency-aware routing, and
a bespoke orchestrator makes that routing logic inspectable in one place
rather than hidden behind a generic "agent graph" abstraction.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.audit import AuditClient
from app.llm.compliance_agent import ComplianceAgent
from app.llm.investigator_agent import InvestigatorAgent
from app.llm.provider import ModelProvider
from app.llm.triage_agent import TriageAgent
from app.models import (
    AgentEvent,
    Alert,
    CaseFile,
    ComplianceReport,
    PipelineStage,
    PreFilterVerdict,
    RuleEngineVerdict,
    ScoringContext,
    SecurityEvent,
    Transaction,
    TriageVerdict,
)
from app.prefilter import AnomalyPreFilter
from app.payments import apply_payment_control
from app.risk_engine import RiskEngineClient
from app.synthetic import build_scoring_context

EventSink = Callable[[AgentEvent | Alert], Awaitable[None]]

# Financial risk below this never leaves stage 0 even with a recent
# security event - a fused alert still needs a real financial signal.
RULES_ESCALATION_THRESHOLD = 25
SECURITY_EVENT_WINDOW = timedelta(minutes=10)


class PipelineResult:
    def __init__(self) -> None:
        self.transaction: dict = {}
        self.context: dict = {}
        self.review: dict = {}
        self.events: list[dict] = []
        self.model_mode = "unknown"
        self.audit: dict = {"status": "not_configured", "entries": [], "errors": []}
        self.stage_reached: PipelineStage = PipelineStage.CLOSED
        self.rules: RuleEngineVerdict | None = None
        self.prefilter: PreFilterVerdict | None = None
        self.triage: TriageVerdict | None = None
        self.case: CaseFile | None = None
        self.compliance: ComplianceReport | None = None
        self.alert: Alert | None = None
        self.payment: dict | None = None

    def as_dict(self) -> dict[str, Any]:
        # mode="json" is load-bearing: Alert carries a `datetime` timestamp
        # field, and plain model_dump() leaves it as a Python datetime
        # object that json.dumps() (used by PostgresCaseStore) can't
        # serialize.
        return {
            "transaction": self.transaction, "context": self.context, "review": self.review,
            "events": self.events, "model_mode": self.model_mode, "audit": self.audit,
            "stage_reached": self.stage_reached.value,
            "rules": self.rules.model_dump(mode="json") if self.rules else None,
            "prefilter": self.prefilter.model_dump(mode="json") if self.prefilter else None,
            "triage": self.triage.model_dump(mode="json") if self.triage else None,
            "case": self.case.model_dump(mode="json") if self.case else None,
            "compliance": self.compliance.model_dump(mode="json") if self.compliance else None,
            "alert": self.alert.model_dump(mode="json") if self.alert else None,
            "payment": self.payment,
        }


class Orchestrator:
    def __init__(
        self,
        *,
        risk_engine: RiskEngineClient,
        prefilter: AnomalyPreFilter,
        provider: ModelProvider,
        haiku_model: str,
        sonnet_model: str,
        event_sink: EventSink | None = None,
        audit: AuditClient | None = None,
    ) -> None:
        self._audit = audit
        self._provider = provider
        self._risk_engine = risk_engine
        self._prefilter = prefilter
        self._triage = TriageAgent(provider, haiku_model)
        self._investigator = InvestigatorAgent(provider, sonnet_model)
        self._compliance = ComplianceAgent(provider, sonnet_model)
        self._event_sink = event_sink
        self._recent_security_events: dict[str, list[tuple[datetime, SecurityEvent]]] = defaultdict(list)

    def record_security_event(self, event: SecurityEvent) -> None:
        if not event.account_id:
            return
        now = datetime.now(timezone.utc)
        bucket = self._recent_security_events[event.account_id]
        bucket.append((now, event))
        cutoff = now - SECURITY_EVENT_WINDOW
        self._recent_security_events[event.account_id] = [(t, e) for t, e in bucket if t > cutoff]

    def _recent_security_event(self, account_id: str) -> SecurityEvent | None:
        cutoff = datetime.now(timezone.utc) - SECURITY_EVENT_WINDOW
        bucket = [e for t, e in self._recent_security_events.get(account_id, []) if t > cutoff]
        return bucket[-1] if bucket else None

    async def _emit(self, event: AgentEvent | Alert) -> None:
        if self._event_sink:
            await self._event_sink(event)

    async def process_transaction(self, tx: Transaction, context: ScoringContext | None = None,
                                  review: dict | None = None) -> PipelineResult:
        result = PipelineResult()
        ctx = context or ScoringContext(**build_scoring_context(tx.account_id, tx.amount))
        result.transaction = tx.model_dump(mode="json")
        result.context = ctx.model_dump(mode="json")
        result.review = review or {}
        result.model_mode = "live" if self._provider.is_live else "replay"

        async def record(event_type: str, payload: dict) -> None:
            if self._audit:
                try:
                    receipt = await self._audit.append(tx.id, event_type, payload)
                    result.audit["entries"].append(receipt)
                except Exception:
                    result.audit["errors"].append(f"Could not persist {event_type}")

        async def emit(event: AgentEvent | Alert) -> None:
            payload = event.model_dump(mode="json")
            result.events.append(payload)
            await record(f"pipeline.{event.stage.value if isinstance(event, AgentEvent) else 'alert'}", payload)
            await self._emit(event)

        async def finish() -> PipelineResult:
            await record("case.completed", {"stage": result.stage_reached.value,
                         "case": result.case.model_dump() if result.case else None,
                         "compliance": result.compliance.model_dump() if result.compliance else None})
            if self._audit:
                try:
                    verification = await self._audit.verify()
                    result.audit["verification"] = verification
                    result.audit["checked_at"] = datetime.now(timezone.utc).isoformat()
                    result.audit["status"] = ("verified" if verification["valid"] and not result.audit["errors"]
                                              else "failed")
                except Exception:
                    result.audit["errors"].append("Audit verification unavailable")
                    result.audit["status"] = "unavailable"
            await apply_payment_control(result, self._audit)
            return result

        await record("case.opened", {"transaction": result.transaction, "context": result.context,
                                    "review": result.review, "model_mode": result.model_mode})

        rules = await self._risk_engine.score(tx, ctx)
        result.rules = rules
        await emit(
            AgentEvent(
                transaction_id=tx.id,
                account_id=tx.account_id,
                stage=PipelineStage.RULES,
                label=f"Rules engine: {rules.risk_score}/100 ({rules.risk_band})",
                detail=rules.model_dump(),
            )
        )

        prefilter_verdict = self._prefilter.score(tx, ctx)
        result.prefilter = prefilter_verdict
        await emit(
            AgentEvent(
                transaction_id=tx.id,
                account_id=tx.account_id,
                stage=PipelineStage.PREFILTER,
                label=f"ML pre-filter: anomaly_score={prefilter_verdict.anomaly_score:.2f}",
                detail=prefilter_verdict.model_dump(),
            )
        )

        if rules.risk_score < RULES_ESCALATION_THRESHOLD and not prefilter_verdict.is_anomaly:
            result.stage_reached = PipelineStage.CLOSED
            await emit(
                AgentEvent(
                    transaction_id=tx.id,
                    account_id=tx.account_id,
                    stage=PipelineStage.CLOSED,
                    label="Closed at stage 0 - no anomaly signal, no LLM call made",
                    detail={},
                )
            )
            return await finish()

        triage = await asyncio.to_thread(self._triage.run, tx, ctx, rules, prefilter_verdict)
        result.triage = triage
        result.stage_reached = PipelineStage.TRIAGE
        await emit(
            AgentEvent(
                transaction_id=tx.id,
                account_id=tx.account_id,
                stage=PipelineStage.TRIAGE,
                label=f"Triage ({result.model_mode}): {triage.category} (fraud_likelihood={triage.fraud_likelihood:.2f})",
                detail=triage.model_dump(),
            )
        )

        if not triage.escalate:
            result.stage_reached = PipelineStage.CLOSED
            await emit(
                AgentEvent(
                    transaction_id=tx.id,
                    account_id=tx.account_id,
                    stage=PipelineStage.CLOSED,
                    label="Closed at triage - not escalated to investigation",
                    detail={},
                )
            )
            return await finish()

        tool_events: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

        def capture_tool_call(name: str, tool_input: dict[str, Any], tool_result: dict[str, Any]) -> None:
            tool_events.append((name, tool_input, tool_result))

        case = await asyncio.to_thread(self._investigator.run, tx, triage, capture_tool_call, rules.risk_score)
        result.case = case
        result.stage_reached = PipelineStage.INVESTIGATION

        for name, tool_input, tool_result in tool_events:
            await emit(
                AgentEvent(
                    transaction_id=tx.id,
                    account_id=tx.account_id,
                    stage=PipelineStage.INVESTIGATION,
                    label=f"Investigator ({result.model_mode}) called {name}({tool_input})",
                    detail={"tool": name, "input": tool_input, "result": tool_result},
                )
            )

        await emit(
            AgentEvent(
                transaction_id=tx.id,
                account_id=tx.account_id,
                stage=PipelineStage.INVESTIGATION,
                label=f"Investigation complete: risk_score={case.risk_score}",
                detail=case.model_dump(),
            )
        )

        compliance_report: ComplianceReport | None = None
        if case.recommend_compliance_review:
            compliance_report = await asyncio.to_thread(self._compliance.run, tx, case)
            result.compliance = compliance_report
            result.stage_reached = PipelineStage.COMPLIANCE
            await emit(
                AgentEvent(
                    transaction_id=tx.id,
                    account_id=tx.account_id,
                    stage=PipelineStage.COMPLIANCE,
                    label="Compliance narrative drafted",
                    detail=compliance_report.model_dump(),
                )
            )

        security_event = self._recent_security_event(tx.account_id)
        if security_event:
            result.stage_reached = PipelineStage.FUSION
            await emit(
                AgentEvent(
                    transaction_id=tx.id,
                    account_id=tx.account_id,
                    stage=PipelineStage.FUSION,
                    label=f"Fused with recent security event: {security_event.type}",
                    detail=security_event.model_dump(),
                )
            )

        severity = self._severity_for(case.risk_score, bool(security_event))
        alert = Alert(
            transaction_id=tx.id,
            account_id=tx.account_id,
            severity=severity,
            title="Fused fraud + account-security alert" if security_event else "Financial risk alert",
            detail={
                "case": case.model_dump(),
                "security_event": security_event.model_dump() if security_event else None,
            },
            fused_with_security_event=bool(security_event),
        )
        result.alert = alert
        await emit(alert)

        return await finish()

    @staticmethod
    def _severity_for(risk_score: int, has_security_event: bool) -> str:
        if has_security_event and risk_score >= 50:
            return "critical"
        if risk_score >= 70:
            return "high"
        if risk_score >= 40:
            return "medium"
        return "low"
