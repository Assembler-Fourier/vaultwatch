// Showcase-mode pipeline orchestrator - a TS port of agents-python's
// app/orchestrator.py, adapted from a streaming background-loop model to a
// stateless request/response model (each call runs one transaction through
// every stage and returns the full trace at once), which is what a Vercel
// serverless function needs.

import { appendAuditEntry } from "./audit";
import { runComplianceAgent, runInvestigatorAgent, runTriageAgent } from "./llm/agents";
import type { ModelProvider } from "./llm/provider";
import { scorePreFilter } from "./prefilter";
import { scoreTransaction } from "./rules";
import { buildScoringContext } from "./synthetic";
import type { AgentEvent, Alert, PipelineResult, Transaction } from "./types";

const RULES_ESCALATION_THRESHOLD = 25;

function utcNow(): string {
  return new Date().toISOString();
}

function severityFor(riskScore: number): Alert["severity"] {
  if (riskScore >= 70) return "high";
  if (riskScore >= 40) return "medium";
  return "low";
}

export async function runPipeline(
  provider: ModelProvider,
  tx: Transaction,
): Promise<{ events: (AgentEvent | Alert)[]; result: PipelineResult }> {
  const events: (AgentEvent | Alert)[] = [];
  const push = (stage: AgentEvent["stage"], label: string, detail: Record<string, unknown>) => {
    events.push({
      type: "agent_event",
      transaction_id: tx.id,
      account_id: tx.account_id,
      stage,
      label,
      detail,
      timestamp: utcNow(),
    });
  };

  const ctx = buildScoringContext(tx.account_id, tx.amount);
  await appendAuditEntry("case.opened", tx.account_id, { transaction_id: tx.id, amount: tx.amount });

  const rules = scoreTransaction(tx, ctx);
  push("rules", `Rules engine: ${rules.risk_score}/100 (${rules.risk_band})`, rules as unknown as Record<string, unknown>);

  const prefilter = scorePreFilter(tx, ctx);
  push("prefilter", `Heuristic pre-filter: anomaly_score=${prefilter.anomaly_score.toFixed(2)}`, prefilter as unknown as Record<string, unknown>);

  const result: PipelineResult = {
    stage_reached: "closed",
    rules,
    prefilter,
    triage: null,
    case: null,
    compliance: null,
    alert: null,
  };

  if (rules.risk_score < RULES_ESCALATION_THRESHOLD && !prefilter.is_anomaly) {
    push("closed", "Closed at stage 0 - no anomaly signal, no LLM call made", {});
    await appendAuditEntry("case.closed", tx.account_id, { transaction_id: tx.id, stage: "closed" });
    return { events, result };
  }

  const triage = await runTriageAgent(provider, tx, rules, prefilter);
  result.triage = triage;
  result.stage_reached = "triage";
  push("triage", `Haiku triage: ${triage.category} (fraud_likelihood=${triage.fraud_likelihood.toFixed(2)})`, triage as unknown as Record<string, unknown>);

  if (!triage.escalate) {
    result.stage_reached = "closed";
    push("closed", "Closed at triage - not escalated to investigation", {});
    await appendAuditEntry("case.closed", tx.account_id, { transaction_id: tx.id, stage: "closed" });
    return { events, result };
  }

  const caseFile = await runInvestigatorAgent(provider, tx, triage, (name, input) => {
    push("investigation", `Sonnet investigator called ${name}(${JSON.stringify(input)})`, { tool: name, input });
  });
  result.case = caseFile;
  result.stage_reached = "investigation";
  push("investigation", `Investigation complete: risk_score=${caseFile.risk_score}`, caseFile as unknown as Record<string, unknown>);

  if (caseFile.recommend_compliance_review) {
    const compliance = await runComplianceAgent(provider, tx, caseFile);
    result.compliance = compliance;
    result.stage_reached = "compliance";
    push("compliance", "Compliance narrative drafted", compliance as unknown as Record<string, unknown>);
  }

  const severity = severityFor(caseFile.risk_score);
  const alert: Alert = {
    type: "alert",
    transaction_id: tx.id,
    account_id: tx.account_id,
    severity,
    title: "Financial risk alert",
    detail: { case: caseFile },
    fused_with_security_event: false,
    timestamp: utcNow(),
  };
  result.alert = alert;
  events.push(alert); // the alert streams alongside agent events in the same trace

  await appendAuditEntry("case.closed", tx.account_id, {
    transaction_id: tx.id,
    stage: result.stage_reached,
    risk_score: caseFile.risk_score,
  });

  return { events, result };
}
