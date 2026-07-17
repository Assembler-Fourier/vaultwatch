// Shared shapes across the dashboard. These deliberately mirror the Pydantic
// models in agents-python (app/models.py) and the Rust structs in
// engine-rust (src/models.rs) so the same JSON works whether it came from
// the real backend (full mode) or the in-process TS pipeline (showcase mode).

export interface Transaction {
  id: string;
  account_id: string;
  amount: number;
  currency: string;
  timestamp: string;
  lat?: number | null;
  lon?: number | null;
  beneficiary_id?: string | null;
  device_id?: string | null;
}

export interface TriggeredRule {
  rule: string;
  weight: number;
  detail: string;
}

export interface RuleEngineVerdict {
  transaction_id: string;
  risk_score: number;
  risk_band: "low" | "medium" | "high" | "critical";
  triggered_rules: TriggeredRule[];
}

export interface PreFilterVerdict {
  anomaly_score: number;
  is_anomaly: boolean;
}

export interface TriageVerdict {
  fraud_likelihood: number;
  category: string;
  escalate: boolean;
  reasoning: string;
}

export interface CaseFile {
  summary: string;
  risk_score: number;
  evidence: string[];
  linked_accounts: string[];
  sanctions_hit: boolean;
  recommend_compliance_review: boolean;
}

export interface ComplianceReport {
  narrative: string;
  obligations_referenced: string[];
  disclaimer: string;
}

export type PipelineStage =
  | "rules"
  | "prefilter"
  | "triage"
  | "investigation"
  | "compliance"
  | "fusion"
  | "closed";

export interface AgentEvent {
  type: "agent_event";
  transaction_id: string;
  account_id: string;
  stage: PipelineStage;
  label: string;
  detail: Record<string, unknown>;
  timestamp: string;
}

export interface Alert {
  type: "alert";
  transaction_id: string;
  account_id: string;
  severity: "low" | "medium" | "high" | "critical";
  title: string;
  detail: Record<string, unknown>;
  fused_with_security_event: boolean;
  timestamp: string;
}

export interface SecurityEvent {
  type: string;
  account_id?: string | null;
  severity: string;
  detail: Record<string, unknown>;
  timestamp?: string | null;
}

export interface PipelineResult {
  stage_reached: PipelineStage;
  rules: RuleEngineVerdict | null;
  prefilter: PreFilterVerdict | null;
  triage: TriageVerdict | null;
  case: CaseFile | null;
  compliance: ComplianceReport | null;
  alert: Alert | null;
}

export interface PipelineRunResponse {
  transaction: Transaction;
  events: (AgentEvent | Alert)[];
  result: PipelineResult;
  model_mode: "live" | "replay";
}
