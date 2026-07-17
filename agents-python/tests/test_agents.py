from datetime import datetime, timezone

from app.llm.compliance_agent import ComplianceAgent
from app.llm.investigator_agent import InvestigatorAgent
from app.llm.provider import ReplayProvider
from app.llm.triage_agent import TriageAgent
from app.models import CaseFile, PreFilterVerdict, RuleEngineVerdict, ScoringContext, Transaction, TriageVerdict


def make_tx(**overrides) -> Transaction:
    base = dict(
        id="tx_1",
        account_id="acct_1",
        amount=42.0,
        timestamp=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc),
        beneficiary_id="ben_known",
        device_id="dev_known",
    )
    base.update(overrides)
    return Transaction(**base)


def test_triage_agent_does_not_escalate_low_risk_signals() -> None:
    provider = ReplayProvider()
    agent = TriageAgent(provider, model="replay-model")

    rules = RuleEngineVerdict(transaction_id="tx_1", risk_score=0, risk_band="low", triggered_rules=[])
    prefilter = PreFilterVerdict(anomaly_score=0.1, is_anomaly=False)

    verdict = agent.run(make_tx(), ScoringContext(), rules, prefilter)

    assert isinstance(verdict, TriageVerdict)
    assert verdict.escalate is False


def test_triage_agent_escalates_high_risk_signals() -> None:
    provider = ReplayProvider()
    agent = TriageAgent(provider, model="replay-model")

    rules = RuleEngineVerdict(
        transaction_id="tx_1",
        risk_score=75,
        risk_band="high",
        triggered_rules=[{"rule": "amount_outlier", "weight": 30, "detail": "..."}],
    )
    prefilter = PreFilterVerdict(anomaly_score=0.9, is_anomaly=True)

    verdict = agent.run(make_tx(amount=9000.0), ScoringContext(), rules, prefilter)

    assert verdict.escalate is True
    assert verdict.fraud_likelihood > 0.5


def test_investigator_agent_low_risk_case_emits_case_file_without_tool_calls() -> None:
    provider = ReplayProvider()
    agent = InvestigatorAgent(provider, model="replay-model")
    triage = TriageVerdict(fraud_likelihood=0.1, category="normal_activity", escalate=True, reasoning="edge case")

    case = agent.run(make_tx(), triage)

    assert isinstance(case, CaseFile)
    assert case.recommend_compliance_review is False


def test_investigator_agent_high_risk_case_calls_research_tools_then_emits_case_file() -> None:
    provider = ReplayProvider()
    observed_calls: list[str] = []
    agent = InvestigatorAgent(provider, model="replay-model")
    triage = TriageVerdict(
        fraud_likelihood=0.82, category="potential_account_takeover", escalate=True, reasoning="stacked signals"
    )

    case = agent.run(make_tx(account_id="acct_high_risk"), triage, on_tool_call=lambda name, i, r: observed_calls.append(name))

    assert observed_calls == ["get_transaction_history", "get_entity_graph", "check_sanctions_list"]
    assert case.recommend_compliance_review is True
    assert case.risk_score >= 70


def test_compliance_agent_produces_disclaimer_and_narrative() -> None:
    provider = ReplayProvider()
    agent = ComplianceAgent(provider, model="replay-model")
    case = CaseFile(
        summary="suspicious pattern",
        risk_score=87,
        evidence=["evidence 1"],
        recommend_compliance_review=True,
    )

    report = agent.run(make_tx(), case)

    assert "SYNTHETIC" in report.narrative
    assert report.disclaimer  # default disclaimer always present
    assert len(report.obligations_referenced) > 0
