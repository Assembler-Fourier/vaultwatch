"""A server-side gate for synthetic payments only. No bank or payment provider."""

import hashlib
from datetime import datetime, timezone

POLICY_VERSION = "local-demo-v2"


def payment_policy(result: dict) -> tuple[str, list[str]]:
    """Use explicit evidence, never the scenario name or a browser-supplied action."""
    rules = result.get("rules") or {}
    case = result.get("case") or {}
    alert = result.get("alert") or {}
    if case.get("sanctions_hit"):
        return "block", ["Synthetic watchlist match found in the investigation."]
    severity = alert.get("severity") or rules.get("risk_band")
    if severity == "critical":
        return "block", ["Critical risk: simulated payment execution is blocked."]
    if severity == "high":
        return "hold", ["High risk: payment paused for human review; execution is withheld."]
    if result.get("audit", {}).get("status") != "verified":
        return "hold", ["Processing evidence could not be verified; do not proceed."]
    if not rules or not result.get("prefilter"):
        return "hold", ["Required risk checks are missing."]
    if (alert or rules.get("risk_score", 0) >= 25
            or result["prefilter"].get("is_anomaly")
            or (result.get("triage") or {}).get("escalate")
            or case.get("recommend_compliance_review")):
        return "hold", ["A risk signal remains; a human review is required."]
    return "allow", ["Completed initial checks found no signal requiring a hold or block."]


def simulate_execution(transaction: dict) -> dict:
    """A reproducible receipt, not an external write, debit, transfer or settlement."""
    return {
        "id": "sim_" + hashlib.sha256(transaction["id"].encode()).hexdigest()[:16],
        "status": "simulated_complete",
        "amount": transaction["amount"],
        "currency": transaction.get("currency", "EUR"),
    }


async def apply_payment_control(result, audit) -> None:
    action, reasons = payment_policy(result.as_dict())
    policy_action = action
    timestamp = datetime.now(timezone.utc).isoformat()
    event = {
        "type": "agent_event", "stage": "payment",
        "transaction_id": result.transaction["id"],
        "account_id": result.transaction["account_id"],
        "timestamp": timestamp,
        "label": f"Payment policy: {action}",
        "detail": {"policy_version": POLICY_VERSION, "action": action, "reasons": reasons,
                   "scope": "simulation_only"},
    }
    result.events.append(event)
    verified = False
    if audit:
        try:
            receipt = await audit.append(result.transaction["id"], "payment.policy", event)
            result.audit["entries"].append(receipt)
            verification = await audit.verify()
            result.audit["verification"] = verification
            result.audit["checked_at"] = datetime.now(timezone.utc).isoformat()
            verified = verification["valid"] and not result.audit["errors"]
            result.audit["status"] = "verified" if verified else "failed"
        except Exception:
            result.audit["errors"].append("Payment policy audit could not be verified")
            if result.audit["status"] != "failed":
                result.audit["status"] = "unavailable"
    if action == "allow" and not verified:
        action = "hold"
        reasons = ["Payment policy could not be recorded and verified; execution was withheld."]
    # This is the enforcement boundary. Blocked/held cases never call the simulator.
    execution = simulate_execution(result.transaction) if action == "allow" else None
    result.payment = {
        "action": action, "policy_action": policy_action, "policy_version": POLICY_VERSION,
        "reasons": reasons, "decided_at": timestamp, "scope": "simulation_only",
        "execution_status": "simulated_complete" if execution else "not_executed",
        "simulation_receipt": execution,
    }
