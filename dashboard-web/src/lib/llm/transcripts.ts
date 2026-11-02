// Canned, deterministic responses used by ReplayProvider - a TS port of
// agents-python/app/llm/transcripts.py. Shaped exactly like what the live
// agents ask Claude to produce (same tool names, same JSON fields).

export type ReplayStep = { tool: string; input: Record<string, unknown> } | { text: string };

export function triageStep(scenario: string): ReplayStep {
  if (scenario === "high") {
    return {
      tool: "emit_triage_verdict",
      input: {
        fraud_likelihood: 0.82,
        category: "potential_account_takeover",
        escalate: true,
        reasoning:
          "The transaction stacks a statistical amount outlier with a first-time beneficiary, and the pre-filter and rules engine both flagged it independently. That combination is consistent with a compromised account being drained rather than normal spending drift.",
      },
    };
  }
  return {
    tool: "emit_triage_verdict",
    input: {
      fraud_likelihood: 0.04,
      category: "normal_activity",
      escalate: false,
      reasoning:
        "Amount, beneficiary and device are all consistent with this account's recent history; no rules or pre-filter signals fired above threshold.",
    },
  };
}

export function investigationSteps(scenario: string, accountId: string, beneficiaryName = "Unspecified demo beneficiary",
  results: Record<string, Record<string, unknown>> = {}, amount = 0): ReplayStep[] {
  const history = (results.get_transaction_history?.history ?? []) as { amount: number }[];
  const linked = (results.get_entity_graph?.linked_accounts ?? []) as string[];
  const screen = results.check_sanctions_list ?? {};
  const hit = screen.hit === true;
  const average = history.length ? history.reduce((sum, row) => sum + row.amount, 0) / history.length : 0;
  const evidence = [
    `Payment ${amount.toFixed(2)} EUR; ${history.length} synthetic historical payments average ${average.toFixed(2)}.`,
    `Synthetic entity graph returned ${linked.length} linked accounts.`,
    `Synthetic watchlist ${hit ? "MATCH" : "no match"} for ${String(screen.query ?? beneficiaryName)}.`,
  ];
  if (scenario === "high") return [
    { tool: "get_transaction_history", input: { account_id: accountId } },
    { tool: "get_entity_graph", input: { account_id: accountId } },
    { tool: "check_sanctions_list", input: { name: beneficiaryName } },
    { tool: "emit_case_file", input: {
      summary: `Account ${accountId} was escalated by triage. ${evidence.join(" ")}`,
      risk_score: Math.min(95, 70 + (hit ? 15 : 0) + linked.length * 3), evidence,
      linked_accounts: linked, sanctions_hit: hit, recommend_compliance_review: true,
    } },
  ];
  return [{ tool: "emit_case_file", input: {
    summary: "Triage did not identify a high-risk pattern; no research tools were requested.",
    risk_score: 12, evidence: [], linked_accounts: [], sanctions_hit: false, recommend_compliance_review: false,
  } }];
}

export function complianceStep(accountId: string, summary = "", evidence = ""): ReplayStep {
  return { tool: "emit_compliance_report", input: {
    narrative: `SYNTHETIC DRAFT - ${summary} ${summary.includes(evidence) ? "" : evidence} Manual review recommended. No payment was blocked and no regulatory report was filed.`,
    obligations_referenced: ["Internal review of suspicious activity (synthetic demonstration)"],
  } };
}
