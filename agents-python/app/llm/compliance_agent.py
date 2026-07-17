"""Stage 3: compliance narrative drafting, on Sonnet.

Only reached when the investigator recommends it. Drafts a SAR-shaped
narrative referencing regulatory obligations in general terms - explicitly
a synthetic demonstration, never presented as a real filing or legal advice.
"""

from __future__ import annotations

from app.llm.provider import ModelProvider
from app.models import CaseFile, ComplianceReport, Transaction

EMIT_COMPLIANCE_REPORT_TOOL = {
    "name": "emit_compliance_report",
    "description": "Emit the structured compliance narrative for this case.",
    "input_schema": {
        "type": "object",
        "properties": {
            "narrative": {"type": "string"},
            "obligations_referenced": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["narrative"],
    },
}

SYSTEM_PROMPT = """You are VaultWatch's Compliance Agent. You are given a confirmed high-risk case file and \
must draft a SAR-style narrative summarizing the suspicious activity in plain, factual language suitable for \
a compliance officer's review queue, referencing relevant regulatory obligations in general terms. This is a \
SYNTHETIC DEMONSTRATION only - never claim to be a real filing or legal advice. Call emit_compliance_report \
exactly once."""


class ComplianceAgent:
    def __init__(self, provider: ModelProvider, model: str):
        self._provider = provider
        self._model = model

    def run(self, tx: Transaction, case: CaseFile) -> ComplianceReport:
        messages = [
            {
                "role": "user",
                "content": (
                    f"Case file for transaction {tx.id} (account {tx.account_id}): {case.summary}\n"
                    f"Risk score: {case.risk_score}\nEvidence: {'; '.join(case.evidence)}"
                ),
            }
        ]

        response = self._provider.complete(
            model=self._model,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[EMIT_COMPLIANCE_REPORT_TOOL],
            tool_choice={"type": "tool", "name": "emit_compliance_report"},
            replay_family="compliance",
            replay_scenario="high",
            replay_vars={"account_id": tx.account_id},
        )

        for call in response.tool_calls:
            if call.name == "emit_compliance_report":
                return ComplianceReport(**call.input)

        raise RuntimeError("ComplianceAgent: model did not emit a compliance report")
