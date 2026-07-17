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

export function investigationSteps(scenario: string, accountId: string): ReplayStep[] {
  if (scenario === "high") {
    return [
      { tool: "get_transaction_history", input: { account_id: accountId } },
      { tool: "get_entity_graph", input: { account_id: accountId } },
      { tool: "check_sanctions_list", input: { name: "Victor Krantz Holdings" } },
      {
        tool: "emit_case_file",
        input: {
          summary: `Account ${accountId} sent an out-of-pattern high-value payment to a beneficiary never seen before on this account. Transaction history shows a stable spending baseline that this payment breaks sharply. The entity graph shows shared-device links to other accounts opened in a short window, a pattern consistent with a fraud ring rather than an isolated compromised account.`,
          risk_score: 87,
          evidence: [
            "Transaction amount is a statistical outlier vs. 12 recent transactions",
            "Beneficiary has no prior payment history on this account",
            "Entity graph shows shared-device links to other recently opened accounts",
            "Sanctions screen against synthetic watchlist returned no direct hit",
          ],
          linked_accounts: [`acct_${accountId.slice(-4)}1`, `acct_${accountId.slice(-4)}2`],
          sanctions_hit: false,
          recommend_compliance_review: true,
        },
      },
    ];
  }
  return [
    {
      tool: "emit_case_file",
      input: {
        summary: `Account ${accountId}'s activity is consistent with its established baseline.`,
        risk_score: 12,
        evidence: ["No material deviation from the account's transaction history"],
        linked_accounts: [],
        sanctions_hit: false,
        recommend_compliance_review: false,
      },
    },
  ];
}

export function complianceStep(accountId: string): ReplayStep {
  return {
    tool: "emit_compliance_report",
    input: {
      narrative: `SYNTHETIC DRAFT - account ${accountId} exhibited a sharp deviation from its established transaction pattern, sending a high-value payment to a previously unseen beneficiary. The receiving account shares device fingerprints with multiple other recently opened accounts, a pattern consistent with mule-account activity. Recommend manual review and, if confirmed, filing consistent with the institution's AML program before further funds movement.`,
      obligations_referenced: [
        "EU AMLD5/6 - suspicious transaction reporting obligation",
        "Central Bank of Ireland - Criminal Justice (Money Laundering and Terrorist Financing) Act 2010 (as amended) reporting expectations",
      ],
    },
  };
}
