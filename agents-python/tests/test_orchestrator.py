from datetime import datetime, timezone

import pytest

from app.llm.provider import ReplayProvider
from app.models import AgentEvent, PipelineStage, RuleEngineVerdict, ScoringContext, SecurityEvent, Transaction
from app.orchestrator import Orchestrator
from app.prefilter import AnomalyPreFilter
from app.synthetic import account_profile


class FakeRiskEngine:
    def __init__(self, verdict: RuleEngineVerdict):
        self.verdict = verdict
        self.calls = 0

    async def score(self, tx: Transaction, ctx: ScoringContext) -> RuleEngineVerdict:
        self.calls += 1
        return self.verdict


def make_tx(**overrides) -> Transaction:
    # The orchestrator re-derives its ScoringContext internally from the
    # synthetic account profile (keyed only by account_id), so a
    # "known"/normal transaction has to actually use that profile's
    # beneficiary/device/typical amount to read as normal to the prefilter.
    account_id = overrides.get("account_id", "acct_1")
    profile = account_profile(account_id)
    base = dict(
        id="tx_1",
        account_id=account_id,
        amount=profile.typical_amount,
        timestamp=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc),
        beneficiary_id=profile.known_beneficiaries[0],
        device_id=profile.known_devices[0],
    )
    base.update(overrides)
    return Transaction(**base)


def build_orchestrator(risk_engine, events: list):
    prefilter = AnomalyPreFilter()
    prefilter.fit()

    async def sink(event):
        events.append(event)

    return Orchestrator(
        risk_engine=risk_engine,
        prefilter=prefilter,
        provider=ReplayProvider(),
        haiku_model="replay-haiku",
        sonnet_model="replay-sonnet",
        event_sink=sink,
    )


@pytest.mark.asyncio
async def test_low_risk_transaction_closes_at_stage_zero_without_llm_calls() -> None:
    events: list = []
    risk_engine = FakeRiskEngine(
        RuleEngineVerdict(transaction_id="tx_1", risk_score=0, risk_band="low", triggered_rules=[])
    )
    orchestrator = build_orchestrator(risk_engine, events)

    result = await orchestrator.process_transaction(make_tx())

    assert result.stage_reached == PipelineStage.CLOSED
    assert result.triage is None
    assert result.case is None
    assert any(e.stage == PipelineStage.CLOSED for e in events if isinstance(e, AgentEvent))


@pytest.mark.asyncio
async def test_high_risk_transaction_escalates_through_compliance_and_raises_alert() -> None:
    events: list = []
    risk_engine = FakeRiskEngine(
        RuleEngineVerdict(
            transaction_id="tx_1",
            risk_score=80,
            risk_band="critical",
            triggered_rules=[{"rule": "amount_outlier", "weight": 30, "detail": "..."}],
        )
    )
    orchestrator = build_orchestrator(risk_engine, events)

    result = await orchestrator.process_transaction(
        make_tx(account_id="acct_high_risk", amount=9000.0, beneficiary_id="ben_unknown")
    )

    assert result.stage_reached in (PipelineStage.COMPLIANCE, PipelineStage.FUSION)
    assert result.triage is not None and result.triage.escalate is True
    assert result.case is not None
    assert result.compliance is not None
    assert result.alert is not None
    assert result.alert.severity in ("high", "critical")

    stages_seen = {e.stage for e in events if isinstance(e, AgentEvent)}
    assert PipelineStage.TRIAGE in stages_seen
    assert PipelineStage.INVESTIGATION in stages_seen
    assert PipelineStage.COMPLIANCE in stages_seen


@pytest.mark.asyncio
async def test_recent_security_event_fuses_into_critical_alert() -> None:
    events: list = []
    risk_engine = FakeRiskEngine(
        RuleEngineVerdict(
            transaction_id="tx_1",
            risk_score=80,
            risk_band="critical",
            triggered_rules=[{"rule": "amount_outlier", "weight": 30, "detail": "..."}],
        )
    )
    orchestrator = build_orchestrator(risk_engine, events)
    orchestrator.record_security_event(
        SecurityEvent(type="impossible_travel", account_id="acct_fused", severity="high", detail={})
    )

    result = await orchestrator.process_transaction(
        make_tx(account_id="acct_fused", amount=9000.0, beneficiary_id="ben_unknown")
    )

    assert result.alert is not None
    assert result.alert.fused_with_security_event is True
    assert result.alert.severity == "critical"
    assert any(e.stage == PipelineStage.FUSION for e in events if isinstance(e, AgentEvent))


@pytest.mark.asyncio
async def test_security_event_outside_window_does_not_fuse() -> None:
    from datetime import timedelta

    events: list = []
    risk_engine = FakeRiskEngine(
        RuleEngineVerdict(transaction_id="tx_1", risk_score=80, risk_band="critical", triggered_rules=[])
    )
    orchestrator = build_orchestrator(risk_engine, events)

    # Manually inject a stale event far outside the fusion window.
    stale_time = datetime.now(timezone.utc) - timedelta(hours=2)
    orchestrator._recent_security_events["acct_stale"] = [  # noqa: SLF001 - test whitebox access
        (stale_time, SecurityEvent(type="brute_force_ip", account_id="acct_stale", severity="critical", detail={}))
    ]

    result = await orchestrator.process_transaction(
        make_tx(account_id="acct_stale", amount=9000.0, beneficiary_id="ben_unknown")
    )

    assert result.alert is not None
    assert result.alert.fused_with_security_event is False
