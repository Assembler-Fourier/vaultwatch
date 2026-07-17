"""Stage 2: the tool-using investigator, on Sonnet.

This is the agent that actually does something an LLM-as-classifier can't:
it decides *what evidence it needs*, fetches it via tool calls, and only
then forms a judgement - a real (bounded) agentic loop, not a single prompt.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.llm.provider import ModelProvider, ToolCall
from app.llm.tools import RESEARCH_TOOL_SCHEMAS, execute_research_tool
from app.models import CaseFile, Transaction, TriageVerdict

EMIT_CASE_FILE_TOOL = {
    "name": "emit_case_file",
    "description": "Emit the final structured case file once enough evidence has been gathered.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "risk_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "linked_accounts": {"type": "array", "items": {"type": "string"}},
            "sanctions_hit": {"type": "boolean"},
            "recommend_compliance_review": {"type": "boolean"},
        },
        "required": ["summary", "risk_score", "evidence", "recommend_compliance_review"],
    },
}

SYSTEM_PROMPT = """You are VaultWatch's Investigator Agent, a senior fraud analyst. A transaction has been \
escalated to you by the triage agent. Use the available tools to gather evidence - transaction history, the \
account's entity graph, and sanctions screening - before forming a judgement. Do not guess at facts you can \
look up. Once you have enough evidence, call emit_case_file exactly once with your findings. Investigate \
efficiently; you have a limited number of tool calls."""

MAX_TURNS = 6

ToolCallObserver = Callable[[str, dict[str, Any], dict[str, Any]], None]


class InvestigatorAgent:
    def __init__(self, provider: ModelProvider, model: str):
        self._provider = provider
        self._model = model

    def run(
        self,
        tx: Transaction,
        triage: TriageVerdict,
        on_tool_call: ToolCallObserver | None = None,
    ) -> CaseFile:
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Investigate transaction {tx.id} on account {tx.account_id} (amount={tx.amount} "
                    f"{tx.currency}, beneficiary={tx.beneficiary_id}). Triage flagged it as "
                    f"'{triage.category}' with fraud_likelihood={triage.fraud_likelihood:.2f}: {triage.reasoning}"
                ),
            }
        ]

        scenario = "high" if triage.fraud_likelihood >= 0.5 else "low"
        tools = RESEARCH_TOOL_SCHEMAS + [EMIT_CASE_FILE_TOOL]

        for _ in range(MAX_TURNS):
            response = self._provider.complete(
                model=self._model,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                replay_family="investigation",
                replay_scenario=scenario,
                replay_vars={"account_id": tx.account_id},
            )

            for call in response.tool_calls:
                if call.name == "emit_case_file":
                    return CaseFile(**call.input)

            if not response.tool_calls:
                break

            messages.append({"role": "assistant", "content": _tool_calls_to_content(response.tool_calls)})

            tool_results = []
            for call in response.tool_calls:
                result = execute_research_tool(call.name, call.input)
                if on_tool_call:
                    on_tool_call(call.name, call.input, result)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result)}
                )
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError("InvestigatorAgent: exceeded max turns without emitting a case file")


def _tool_calls_to_content(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls]
