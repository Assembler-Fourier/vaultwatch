import random
from collections import Counter
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import main, payments
from app.demo import balanced_batch
from app.models import PreFilterVerdict, RuleEngineVerdict, Alert, CaseFile
from app.orchestrator import PipelineResult
from tests.test_review import RecordingAudit


def clean_result():
    result = PipelineResult()
    result.transaction = {"id": "tx_gate", "account_id": "acct_gate", "amount": 50, "currency": "EUR"}
    result.rules = RuleEngineVerdict(transaction_id="tx_gate", risk_score=0, risk_band="low")
    result.prefilter = PreFilterVerdict(anomaly_score=0, is_anomaly=False)
    result.audit["status"] = "verified"
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", ["critical", "watchlist", "rules"])
async def test_block_prevents_execution_even_without_valid_audit(monkeypatch, signal):
    result = clean_result()
    if signal in {"high", "critical"}:
        result.alert = Alert(transaction_id="tx_gate", account_id="acct_gate", severity=signal, title="Risk")
    elif signal == "watchlist":
        result.case = CaseFile(summary="Match", risk_score=20, sanctions_hit=True, recommend_compliance_review=True)
    else:
        result.rules.risk_score = 100
        result.rules.risk_band = "critical"
    simulator = Mock(side_effect=AssertionError("Blocked payment executed"))
    monkeypatch.setattr(payments, "simulate_execution", simulator)
    await payments.apply_payment_control(result, RecordingAudit(fail=True))
    assert result.payment["action"] == "block"
    assert result.payment["execution_status"] == "not_executed"
    simulator.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", ["medium", "high", "anomaly", "rules", "missing"])
async def test_uncertain_payment_is_held(monkeypatch, signal):
    result = clean_result()
    if signal in {"medium", "high"}:
        result.alert = Alert(transaction_id="tx_gate", account_id="acct_gate", severity=signal, title="Review")
        if signal == "high":
            result.rules.risk_score = 100
            result.rules.risk_band = "critical"
    elif signal == "anomaly":
        result.prefilter.is_anomaly = True
    elif signal == "rules":
        result.rules.risk_score = 25
    else:
        result.rules = None
    simulator = Mock()
    monkeypatch.setattr(payments, "simulate_execution", simulator)
    await payments.apply_payment_control(result, RecordingAudit())
    assert result.payment["action"] == "hold"
    simulator.assert_not_called()


@pytest.mark.asyncio
async def test_clear_payment_only_executes_after_policy_receipt_is_verified(monkeypatch):
    result, audit = clean_result(), RecordingAudit()
    original = payments.simulate_execution

    def execute(tx):
        assert audit.entries[-1]["event_type"] == "payment.policy"
        assert result.audit["status"] == "verified"
        return original(tx)

    monkeypatch.setattr(payments, "simulate_execution", execute)
    await payments.apply_payment_control(result, audit)
    assert result.payment["action"] == "allow"
    assert result.payment["execution_status"] == "simulated_complete"
    assert result.payment["simulation_receipt"]["id"].startswith("sim_")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "broken", "missing"])
async def test_audit_failure_holds_otherwise_clear_payment(monkeypatch, failure):
    result = clean_result()
    audit = RecordingAudit(fail=failure == "write")
    if failure == "broken":
        async def broken():
            return {"valid": False, "entries_checked": 1}
        audit.verify = broken
    simulator = Mock()
    monkeypatch.setattr(payments, "simulate_execution", simulator)
    await payments.apply_payment_control(result, None if failure == "missing" else audit)
    assert result.payment["action"] == "hold"
    assert result.payment["simulation_receipt"] is None
    simulator.assert_not_called()


@pytest.mark.parametrize("seed", [1, 17, 42])
def test_balanced_batch_has_every_scenario_without_changing_mix(seed):
    items = balanced_batch(random.Random(seed))
    assert len(items) == 10
    assert Counter(r.scenario for r in items) == {
        "normal": 5, "review": 2, "unusual": 1, "sanctions": 1, "takeover": 1,
    }
    assert all(r.amount > 0 for r in items)
    assert all(r.origin == r.destination for r in items if r.scenario in {"normal", "review"})
    assert all(r.origin != r.destination for r in items if r.scenario in {"unusual", "sanctions", "takeover"})
    assert items != balanced_batch(random.Random(seed + 1))


@pytest.mark.asyncio
async def test_batch_retains_successes_and_reports_partial_failure(monkeypatch):
    monkeypatch.setenv("DEMO_CONTROLS", "true")
    monkeypatch.setitem(main.state, "provider", Mock(is_live=False))
    calls = []

    async def run(request):
        calls.append(request)
        if len(calls) == 3:
            raise HTTPException(503, "dependency down")
        return {"transaction": {"id": f"tx_{len(calls)}"}}

    monkeypatch.setattr(main, "demo_run", run)
    result = await main.demo_batch()
    assert len(calls) == 10 and len(result["results"]) == 9
    assert len(result["failures"]) == 1 and result["failures"][0]["index"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,live,status", [(False, False, 404), (True, True, 409)])
async def test_batch_requires_enabled_controls_and_replay(monkeypatch, enabled, live, status):
    monkeypatch.setenv("DEMO_CONTROLS", str(enabled).lower())
    monkeypatch.setitem(main.state, "provider", Mock(is_live=live))
    with pytest.raises(HTTPException) as error:
        await main.demo_batch()
    assert error.value.status_code == status
