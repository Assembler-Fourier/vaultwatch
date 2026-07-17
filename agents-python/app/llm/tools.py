"""Research tools exposed to the investigator agent via Claude's tool-use.

Each tool is backed by the synthetic data generators in app.synthetic - in a
production system these would call real internal services (a case
management system, a graph database, a real sanctions-screening vendor).
"""

from __future__ import annotations

from typing import Any

from app.synthetic import check_sanctions_list, generate_entity_graph, generate_transaction_history

RESEARCH_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_transaction_history",
        "description": "Fetch an account's recent transaction history to establish its normal spending baseline.",
        "input_schema": {
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
        },
    },
    {
        "name": "get_entity_graph",
        "description": "Fetch accounts linked to the given account via shared device, beneficiary, or other identifiers.",
        "input_schema": {
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
        },
    },
    {
        "name": "check_sanctions_list",
        "description": "Screen a name against the sanctions/watchlist.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def execute_research_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    if name == "get_transaction_history":
        return {"history": generate_transaction_history(tool_input["account_id"])}
    if name == "get_entity_graph":
        return generate_entity_graph(tool_input["account_id"])
    if name == "check_sanctions_list":
        return check_sanctions_list(tool_input["name"])
    raise ValueError(f"unknown research tool: {name}")
