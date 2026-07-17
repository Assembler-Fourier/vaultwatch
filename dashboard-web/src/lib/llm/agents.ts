// The three-tier agent pipeline - a TS port of agents-python's
// llm/triage_agent.py, llm/investigator_agent.py and llm/compliance_agent.py.
// Kept in one file here (vs. three in the Python service) since showcase
// mode's request/response model means there's no long-lived process state
// to separate out.

import type Anthropic from "@anthropic-ai/sdk";
import { HAIKU_MODEL, SONNET_MODEL } from "../config";
import type {
  CaseFile,
  ComplianceReport,
  PreFilterVerdict,
  RuleEngineVerdict,
  Transaction,
  TriageVerdict,
} from "../types";
import type { ModelProvider, ToolCall } from "./provider";
import { executeResearchTool, RESEARCH_TOOL_SCHEMAS } from "./tools";

const EMIT_TRIAGE_VERDICT_TOOL = {
  name: "emit_triage_verdict",
  description: "Emit the structured fraud-triage verdict for this transaction.",
  input_schema: {
    type: "object",
    properties: {
      fraud_likelihood: { type: "number", minimum: 0, maximum: 1 },
      category: { type: "string" },
      escalate: { type: "boolean" },
      reasoning: { type: "string" },
    },
    required: ["fraud_likelihood", "category", "escalate", "reasoning"],
  },
};

const TRIAGE_SYSTEM_PROMPT = `You are VaultWatch's Triage Agent, a fast first-pass fraud reviewer for a fintech's transaction stream. You are given a transaction plus two cheap upstream signals: a deterministic rules-engine verdict and a statistical anomaly pre-filter score. Decide whether the case needs a slower, tool-using investigation by a senior agent. Bias toward NOT escalating unless the evidence genuinely warrants it. Respond by calling emit_triage_verdict exactly once.`;

export async function runTriageAgent(
  provider: ModelProvider,
  tx: Transaction,
  rules: RuleEngineVerdict,
  prefilter: PreFilterVerdict,
): Promise<TriageVerdict> {
  const triggered = rules.triggered_rules.map((r) => r.rule);
  const userContent =
    `Transaction ${tx.id} on account ${tx.account_id}: amount=${tx.amount} ${tx.currency}, ` +
    `beneficiary=${tx.beneficiary_id}, device=${tx.device_id}.\n` +
    `Rules engine: risk_score=${rules.risk_score} band=${rules.risk_band} triggered=${JSON.stringify(triggered)}.\n` +
    `Pre-filter: anomaly_score=${prefilter.anomaly_score.toFixed(2)} is_anomaly=${prefilter.is_anomaly}.`;

  const scenario = rules.risk_score >= 50 || prefilter.is_anomaly ? "high" : "low";

  const response = await provider.complete({
    model: HAIKU_MODEL,
    system: TRIAGE_SYSTEM_PROMPT,
    messages: [{ role: "user", content: userContent }],
    tools: [EMIT_TRIAGE_VERDICT_TOOL],
    toolChoice: { type: "tool", name: "emit_triage_verdict" },
    replayFamily: "triage",
    replayScenario: scenario,
  });

  const call = response.toolCalls.find((c) => c.name === "emit_triage_verdict");
  if (!call) throw new Error("TriageAgent: model did not emit a triage verdict");
  return call.input as unknown as TriageVerdict;
}

const EMIT_CASE_FILE_TOOL = {
  name: "emit_case_file",
  description: "Emit the final structured case file once enough evidence has been gathered.",
  input_schema: {
    type: "object",
    properties: {
      summary: { type: "string" },
      risk_score: { type: "integer", minimum: 0, maximum: 100 },
      evidence: { type: "array", items: { type: "string" } },
      linked_accounts: { type: "array", items: { type: "string" } },
      sanctions_hit: { type: "boolean" },
      recommend_compliance_review: { type: "boolean" },
    },
    required: ["summary", "risk_score", "evidence", "recommend_compliance_review"],
  },
};

const INVESTIGATION_SYSTEM_PROMPT = `You are VaultWatch's Investigator Agent, a senior fraud analyst. A transaction has been escalated to you by the triage agent. Use the available tools to gather evidence - transaction history, the account's entity graph, and sanctions screening - before forming a judgement. Do not guess at facts you can look up. Once you have enough evidence, call emit_case_file exactly once with your findings. Investigate efficiently; you have a limited number of tool calls.`;

const MAX_INVESTIGATION_TURNS = 6;

export type ToolCallObserver = (name: string, input: Record<string, unknown>, result: Record<string, unknown>) => void;

export async function runInvestigatorAgent(
  provider: ModelProvider,
  tx: Transaction,
  triage: TriageVerdict,
  onToolCall?: ToolCallObserver,
): Promise<CaseFile> {
  const messages: Anthropic.MessageParam[] = [
    {
      role: "user",
      content:
        `Investigate transaction ${tx.id} on account ${tx.account_id} (amount=${tx.amount} ${tx.currency}, ` +
        `beneficiary=${tx.beneficiary_id}). Triage flagged it as '${triage.category}' with ` +
        `fraud_likelihood=${triage.fraud_likelihood.toFixed(2)}: ${triage.reasoning}`,
    },
  ];

  const scenario = triage.fraud_likelihood >= 0.5 ? "high" : "low";
  const tools = [...RESEARCH_TOOL_SCHEMAS, EMIT_CASE_FILE_TOOL];

  for (let turn = 0; turn < MAX_INVESTIGATION_TURNS; turn++) {
    const response = await provider.complete({
      model: SONNET_MODEL,
      system: INVESTIGATION_SYSTEM_PROMPT,
      messages,
      tools,
      replayFamily: "investigation",
      replayScenario: scenario,
      replayVars: { account_id: tx.account_id },
    });

    const finalCall = response.toolCalls.find((c) => c.name === "emit_case_file");
    if (finalCall) {
      return finalCall.input as unknown as CaseFile;
    }

    if (response.toolCalls.length === 0) break;

    messages.push({ role: "assistant", content: toolCallsToContent(response.toolCalls) });

    const toolResults: Anthropic.ToolResultBlockParam[] = [];
    for (const call of response.toolCalls) {
      const result = executeResearchTool(call.name, call.input);
      onToolCall?.(call.name, call.input, result);
      toolResults.push({ type: "tool_result", tool_use_id: call.id, content: JSON.stringify(result) });
    }
    messages.push({ role: "user", content: toolResults });
  }

  throw new Error("InvestigatorAgent: exceeded max turns without emitting a case file");
}

function toolCallsToContent(toolCalls: ToolCall[]): Anthropic.ToolUseBlockParam[] {
  return toolCalls.map((c) => ({ type: "tool_use", id: c.id, name: c.name, input: c.input }));
}

const EMIT_COMPLIANCE_REPORT_TOOL = {
  name: "emit_compliance_report",
  description: "Emit the structured compliance narrative for this case.",
  input_schema: {
    type: "object",
    properties: {
      narrative: { type: "string" },
      obligations_referenced: { type: "array", items: { type: "string" } },
    },
    required: ["narrative"],
  },
};

const COMPLIANCE_SYSTEM_PROMPT = `You are VaultWatch's Compliance Agent. You are given a confirmed high-risk case file and must draft a SAR-style narrative summarizing the suspicious activity in plain, factual language, referencing relevant regulatory obligations in general terms. This is a SYNTHETIC DEMONSTRATION only - never claim to be a real filing or legal advice. Call emit_compliance_report exactly once.`;

const DEFAULT_DISCLAIMER =
  "Synthetic demonstration output only. Not legal or regulatory advice, and not a real Suspicious Activity Report.";

export async function runComplianceAgent(
  provider: ModelProvider,
  tx: Transaction,
  caseFile: CaseFile,
): Promise<ComplianceReport> {
  const userContent =
    `Case file for transaction ${tx.id} (account ${tx.account_id}): ${caseFile.summary}\n` +
    `Risk score: ${caseFile.risk_score}\nEvidence: ${caseFile.evidence.join("; ")}`;

  const response = await provider.complete({
    model: SONNET_MODEL,
    system: COMPLIANCE_SYSTEM_PROMPT,
    messages: [{ role: "user", content: userContent }],
    tools: [EMIT_COMPLIANCE_REPORT_TOOL],
    toolChoice: { type: "tool", name: "emit_compliance_report" },
    replayFamily: "compliance",
    replayVars: { account_id: tx.account_id },
  });

  const call = response.toolCalls.find((c) => c.name === "emit_compliance_report");
  if (!call) throw new Error("ComplianceAgent: model did not emit a compliance report");
  const input = call.input as { narrative: string; obligations_referenced?: string[] };
  return {
    narrative: input.narrative,
    obligations_referenced: input.obligations_referenced ?? [],
    disclaimer: DEFAULT_DISCLAIMER,
  };
}
