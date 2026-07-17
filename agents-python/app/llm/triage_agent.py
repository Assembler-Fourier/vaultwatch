"""Stage 1: fast triage on Haiku.

Only transactions the rules engine or the ML pre-filter already flagged
reach this agent. Its job is cheap and narrow: decide whether the case is
worth a senior (and much more expensive, tool-using) investigation.
"""

from __future__ import annotations

from app.llm.provider import ModelProvider
from app.models import PreFilterVerdict, RuleEngineVerdict, ScoringContext, Transaction, TriageVerdict

EMIT_TRIAGE_VERDICT_TOOL = {
    "name": "emit_triage_verdict",
    "description": "Emit the structured fraud-triage verdict for this transaction.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fraud_likelihood": {"type": "number", "minimum": 0, "maximum": 1},
            "category": {"type": "string"},
            "escalate": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["fraud_likelihood", "category", "escalate", "reasoning"],
    },
}

SYSTEM_PROMPT = """You are VaultWatch's Triage Agent, a fast first-pass fraud reviewer for a fintech's \
transaction stream. You are given a transaction plus two cheap upstream signals: a deterministic \
rules-engine verdict and a statistical anomaly pre-filter score. Decide whether the case needs a slower, \
tool-using investigation by a senior agent. Bias toward NOT escalating unless the evidence genuinely \
warrants it - escalation is expensive and should be reserved for cases that look like real fraud, not \
routine spending variation. Respond by calling emit_triage_verdict exactly once."""


class TriageAgent:
    def __init__(self, provider: ModelProvider, model: str):
        self._provider = provider
        self._model = model

    def run(
        self,
        tx: Transaction,
        ctx: ScoringContext,
        rules: RuleEngineVerdict,
        prefilter: PreFilterVerdict,
    ) -> TriageVerdict:
        triggered = [r.get("rule") for r in rules.triggered_rules]
        user_content = (
            f"Transaction {tx.id} on account {tx.account_id}: amount={tx.amount} {tx.currency}, "
            f"beneficiary={tx.beneficiary_id}, device={tx.device_id}.\n"
            f"Rules engine: risk_score={rules.risk_score} band={rules.risk_band} triggered={triggered}.\n"
            f"Pre-filter: anomaly_score={prefilter.anomaly_score:.2f} is_anomaly={prefilter.is_anomaly}."
        )
        messages = [{"role": "user", "content": user_content}]

        scenario = "high" if (rules.risk_score >= 50 or prefilter.is_anomaly) else "low"

        response = self._provider.complete(
            model=self._model,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[EMIT_TRIAGE_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "emit_triage_verdict"},
            replay_family="triage",
            replay_scenario=scenario,
        )

        for call in response.tool_calls:
            if call.name == "emit_triage_verdict":
                return TriageVerdict(**call.input)

        raise RuntimeError("TriageAgent: model did not emit a triage verdict")
