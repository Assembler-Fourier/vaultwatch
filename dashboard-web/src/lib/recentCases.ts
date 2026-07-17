// In-memory recent-cases list for showcase mode, mirroring agents-python's
// InMemoryCaseStore fallback (app/db.py). Same caveat as audit.ts: lives
// for the lifetime of a warm serverless instance, not guaranteed durable.

import type { PipelineResult, Transaction } from "./types";

export interface CaseRecord {
  transaction: Transaction;
  result: PipelineResult;
  recorded_at: string;
}

const CAPACITY = 100;
const cases: CaseRecord[] = [];

export function recordCase(transaction: Transaction, result: PipelineResult): void {
  cases.unshift({ transaction, result, recorded_at: new Date().toISOString() });
  if (cases.length > CAPACITY) cases.length = CAPACITY;
}

export function recentCases(limit = 50): CaseRecord[] {
  return cases.slice(0, limit);
}
