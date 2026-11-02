import asyncio
import json

import pytest

from app.llm.investigator_agent import InvestigatorAgent
from app.llm.provider import ReplayProvider
from app.models import TriageVerdict, RuleEngineVerdict
from app.reports import render_report
from app.synthetic import generate_entity_graph
from tests.test_agents import make_tx
from tests.test_orchestrator import FakeRiskEngine, build_orchestrator


@pytest.mark.parametrize(
    "name, expected", [("Victor Krantz Holdings", True), ("North Quay Supplies", False)]
)
def test_replay_case_matches_actual_screen_and_entity_graph(name, expected):
    agent = InvestigatorAgent(ReplayProvider(), "replay")
    observations = []
    tx = make_tx(account_id="acct_review", beneficiary_name=name)
    triage = TriageVerdict(
        fraud_likelihood=0.82, category="review", escalate=True, reasoning="test"
    )
    result = agent.run(
        tx, triage, lambda name, args, value: observations.append((name, value))
    )
    assert observations[-1][1]["hit"] == expected
    assert result.sanctions_hit == expected
    assert (
        result.linked_accounts
        == generate_entity_graph(tx.account_id)["linked_accounts"]
    )
    assert ("no match" if not expected else "MATCH") in " ".join(result.evidence)


class RecordingAudit:
    def __init__(self, fail=False):
        self.entries = []
        self.fail = fail

    async def append(self, tx, kind, payload):
        if self.fail:
            raise OSError("disk unavailable")
        row = {
            "seq": len(self.entries) + 1,
            "subject_id": tx,
            "event_type": kind,
            "payload": payload,
        }
        self.entries.append(row)
        return row

    async def verify(self):
        return {"valid": True, "entries_checked": len(self.entries)}


@pytest.mark.asyncio
async def test_complete_cases_have_isolated_audit_and_saved_tool_evidence():
    orchestrator = build_orchestrator(
        FakeRiskEngine(
            RuleEngineVerdict(transaction_id="test", risk_score=80, risk_band="high")
        ),
        [],
    )
    audit = RecordingAudit()
    orchestrator._audit = audit
    results = await asyncio.gather(
        *[
            orchestrator.process_transaction(
                make_tx(
                    id=f"tx_{i}",
                    account_id=f"acct_{i}",
                    amount=9000,
                    beneficiary_name="Victor Krantz Holdings",
                )
            )
            for i in range(2)
        ]
    )
    for i, result in enumerate(results):
        assert result.audit["status"] == "verified"
        assert all(
            entry["subject_id"] == f"tx_{i}" for entry in result.audit["entries"]
        )
        assert result.audit["entries"][0]["event_type"] == "case.opened"
        assert result.audit["entries"][-2]["event_type"] == "case.completed"
        assert result.audit["entries"][-1]["event_type"] == "payment.policy"
        assert result.payment["action"] == "block"
        assert result.payment["simulation_receipt"] is None
        research = [
            e["detail"] for e in result.events if e.get("detail", {}).get("tool")
        ]
        assert research[-1]["result"]["hit"] is True
        assert result.transaction["id"] == f"tx_{i}"
        json.dumps(
            result.as_dict()
        )  # All evidence, including timestamps, must persist as JSON.


@pytest.mark.asyncio
async def test_audit_failure_is_never_reported_as_verified():
    orchestrator = build_orchestrator(
        FakeRiskEngine(
            RuleEngineVerdict(transaction_id="test", risk_score=80, risk_band="high")
        ),
        [],
    )
    orchestrator._audit = RecordingAudit(fail=True)
    result = await orchestrator.process_transaction(make_tx(amount=9000))
    assert result.audit["status"] == "failed"
    assert result.audit["errors"]


def test_report_escapes_untrusted_evidence():
    record = {
        "transaction_id": "<script>alert(1)</script>",
        "result": {
            "transaction": {"account_id": "<img src=x onerror=alert(1)>"},
            "events": [],
            "audit": {"entries": [], "errors": []},
        },
    }
    report = render_report(record, {"verify": {"valid": True}})
    assert "<script>" not in report and "<img" not in report
    assert "&lt;script&gt;" in report


def test_investigated_report_does_not_claim_early_closure_or_known_device():
    record = {
        "transaction_id": "tx_review",
        "result": {
            "transaction": {"account_id": "acct_review"},
            "review": {},
            "stage_reached": "investigation",
            "alert": {"title": "Financial risk alert", "severity": "medium"},
            "case": {"summary": "Review required", "sanctions_hit": False},
            "compliance": None,
            "payment": {"action": "hold", "reasons": ["Review required"]},
        },
    }
    report = render_report(record, {"verify": {"valid": True}})
    assert "Closed after initial checks" not in report
    assert "No compliance draft was requested" in report
    assert "Payment decision: hold" in report
    assert "Device familiarity not recorded" in report
    assert "Recipient familiarity not recorded" in report
    assert "Known device" not in report and "Known recipient" not in report
