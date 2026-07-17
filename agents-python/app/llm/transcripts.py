"""Canned, deterministic responses used by ReplayProvider.

These are shaped exactly like what the live agents ask Claude to produce
(same tool names, same JSON schema) - they exist so the pipeline is fully
exercisable with zero API cost, not as test fixtures.
"""

from __future__ import annotations

from typing import Any


def triage_step(scenario: str) -> dict[str, Any]:
    if scenario == "high":
        return {
            "tool": "emit_triage_verdict",
            "input": {
                "fraud_likelihood": 0.82,
                "category": "potential_account_takeover",
                "escalate": True,
                "reasoning": (
                    "The transaction stacks a statistical amount outlier with a first-time "
                    "beneficiary, and the pre-filter and rules engine both flagged it "
                    "independently. That combination is consistent with a compromised "
                    "account being drained rather than normal spending drift."
                ),
            },
        }
    return {
        "tool": "emit_triage_verdict",
        "input": {
            "fraud_likelihood": 0.04,
            "category": "normal_activity",
            "escalate": False,
            "reasoning": (
                "Amount, beneficiary and device are all consistent with this account's "
                "recent history; no rules or pre-filter signals fired above threshold."
            ),
        },
    }


def investigation_steps(scenario: str, account_id: str = "acct_unknown", **_: Any) -> list[dict[str, Any]]:
    if scenario == "high":
        return [
            {"tool": "get_transaction_history", "input": {"account_id": account_id}},
            {"tool": "get_entity_graph", "input": {"account_id": account_id}},
            {"tool": "check_sanctions_list", "input": {"name": "Victor Krantz Holdings"}},
            {
                "tool": "emit_case_file",
                "input": {
                    "summary": (
                        f"Account {account_id} sent an out-of-pattern high-value payment to a "
                        "beneficiary never seen before on this account. Transaction history shows "
                        "a stable spending baseline that this payment breaks sharply. The entity "
                        "graph shows shared-device links to other accounts opened in a short "
                        "window, a pattern consistent with a fraud ring rather than an isolated "
                        "compromised account."
                    ),
                    "risk_score": 87,
                    "evidence": [
                        "Transaction amount is a statistical outlier vs. 12 recent transactions",
                        "Beneficiary has no prior payment history on this account",
                        "Entity graph shows shared-device links to other recently opened accounts",
                        "Sanctions screen against synthetic watchlist returned no direct hit",
                    ],
                    "linked_accounts": [f"acct_{account_id[-4:]}1", f"acct_{account_id[-4:]}2"],
                    "sanctions_hit": False,
                    "recommend_compliance_review": True,
                },
            },
        ]
    return [
        {
            "tool": "emit_case_file",
            "input": {
                "summary": f"Account {account_id}'s activity is consistent with its established baseline.",
                "risk_score": 12,
                "evidence": ["No material deviation from the account's transaction history"],
                "linked_accounts": [],
                "sanctions_hit": False,
                "recommend_compliance_review": False,
            },
        },
    ]


def compliance_step(scenario: str, account_id: str = "acct_unknown", **_: Any) -> dict[str, Any]:
    return {
        "tool": "emit_compliance_report",
        "input": {
            "narrative": (
                f"SYNTHETIC DRAFT - account {account_id} exhibited a sharp deviation from its "
                "established transaction pattern, sending a high-value payment to a previously "
                "unseen beneficiary. The receiving account shares device fingerprints with "
                "multiple other recently opened accounts, a pattern consistent with mule-account "
                "activity. Recommend manual review and, if confirmed, filing consistent with the "
                "institution's AML program before further funds movement."
            ),
            "obligations_referenced": [
                "EU AMLD5/6 - suspicious transaction reporting obligation",
                "Central Bank of Ireland - Criminal Justice (Money Laundering and Terrorist "
                "Financing) Act 2010 (as amended) reporting expectations",
            ],
        },
    }
