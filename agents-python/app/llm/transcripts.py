"""Canned, deterministic responses used by ReplayProvider.

These are shaped exactly like what the live agents ask Claude to produce
(same tool names, same JSON schema) - they exist so the pipeline is fully
exercisable with zero API cost, not as test fixtures.
"""

from __future__ import annotations

from typing import Any


def triage_step(scenario: str, rules: dict | None = None, prefilter: dict | None = None) -> dict[str, Any]:
    if scenario == "high":
        return {
            "tool": "emit_triage_verdict",
            "input": {
                "fraud_likelihood": 0.82,
                "category": "potential_account_takeover" if any(r.get("rule") == "impossible_travel" for r in (rules or {}).get("triggered_rules", [])) else "unusual_activity",
                "escalate": True,
                "reasoning": (
                    f"Rules score {(rules or {}).get('risk_score', 'unknown')}. "
                    f"Triggered: {', '.join(r['rule'] for r in (rules or {}).get('triggered_rules', [])) or 'none'}. "
                    f"Statistical anomaly: {(prefilter or {}).get('is_anomaly', False)}. "
                    "Replay triage escalates these signals for evidence gathering."
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


def investigation_steps(
    scenario: str, account_id: str = "acct_unknown", beneficiary_name: str = "Unspecified demo beneficiary",
    evidence: dict | None = None, amount: float = 0, currency: str = "EUR", rules_score: int = 0, **_: Any,
) -> list[dict[str, Any]]:
    evidence = evidence or {}
    history = evidence.get("get_transaction_history", {}).get("history", [])
    linked = evidence.get("get_entity_graph", {}).get("linked_accounts", [])
    screen = evidence.get("check_sanctions_list", {})
    hit = bool(screen.get("hit", False))
    mean = sum(row["amount"] for row in history) / len(history) if history else 0
    facts = [
        f"Payment {amount:.2f} {currency}; {len(history)} synthetic historical payments average {mean:.2f}.",
        f"Synthetic entity graph returned {len(linked)} linked accounts.",
        f"Synthetic watchlist {'MATCH' if hit else 'no match'} for {screen.get('query', beneficiary_name)}.",
    ]
    summary = f"Account {account_id} was escalated by triage. " + " ".join(facts)
    # Investigation can downgrade an initial suspicion when returned evidence is moderate.
    base = 70 if rules_score >= 50 or (mean > 0 and amount >= mean * 3) else 40
    score = min(95, (85 if hit else base) + len(linked) * 3)
    case = {"summary": summary, "risk_score": score,
            "evidence": facts, "linked_accounts": linked, "sanctions_hit": hit,
            "recommend_compliance_review": score >= 70 or hit}
    if scenario == "high":
        return [
            {"tool": "get_transaction_history", "input": {"account_id": account_id}},
            {"tool": "get_entity_graph", "input": {"account_id": account_id}},
            {"tool": "check_sanctions_list", "input": {"name": beneficiary_name}},
            {"tool": "emit_case_file", "input": case},
        ]
    return [{"tool": "emit_case_file", "input": {
        "summary": "Triage did not identify a high-risk pattern; no research tools were requested.",
        "risk_score": 12, "evidence": [], "linked_accounts": [], "sanctions_hit": False,
        "recommend_compliance_review": False,
    }}]


def compliance_step(scenario: str, account_id: str = "acct_unknown", case_summary: str = "",
                    evidence: list[str] | None = None, **_: Any) -> dict[str, Any]:
    return {"tool": "emit_compliance_report", "input": {
        "narrative": f"SYNTHETIC DRAFT - {case_summary} " + " ".join(item for item in (evidence or []) if item not in case_summary)
                     + " Manual review recommended. This risk narrative precedes the separate payment decision. No real funds moved and no regulatory report was filed.",
        "obligations_referenced": ["Internal review of suspicious activity (synthetic demonstration)"],
    }}
