// Stage 0 for showcase mode: a lightweight statistical heuristic, not a
// trained model. agents-python runs a real scikit-learn IsolationForest for
// this stage (see agents-python/app/prefilter.py) - reimplementing that in
// TypeScript would mean shipping a native ML dependency into a Vercel
// serverless function for a demo tier that's supposed to be cheap and
// instant. This composite z-score over the same feature set gets the same
// job done (flag genuinely unusual transactions before any LLM call) with
// zero dependencies.

import type { PreFilterVerdict, Transaction } from "./types";

interface ScoringContext {
  recent_amounts: number[];
  recent_count_last_hour: number;
  known_beneficiaries: string[];
  known_devices: string[];
}

export function scorePreFilter(tx: Transaction, ctx: ScoringContext): PreFilterVerdict {
  let z = 0;
  if (ctx.recent_amounts.length >= 3) {
    const mean = ctx.recent_amounts.reduce((a, b) => a + b, 0) / ctx.recent_amounts.length;
    const variance = ctx.recent_amounts.reduce((a, v) => a + (v - mean) ** 2, 0) / ctx.recent_amounts.length;
    const stddev = Math.sqrt(variance) || 1;
    z = Math.abs((tx.amount - mean) / stddev);
  }

  const isNewBeneficiary = tx.beneficiary_id ? !ctx.known_beneficiaries.includes(tx.beneficiary_id) : false;
  const isNewDevice = tx.device_id ? !ctx.known_devices.includes(tx.device_id) : false;
  const highVelocity = ctx.recent_count_last_hour >= 5;

  // Weighted composite, squashed to 0..1. Weights mirror the relative
  // importance of each signal in the Python IsolationForest's feature set
  // without claiming to reproduce its exact decision boundary.
  const raw =
    Math.min(z / 4, 1) * 0.5 +
    (isNewBeneficiary ? 0.25 : 0) +
    (isNewDevice ? 0.1 : 0) +
    (highVelocity ? 0.15 : 0);

  const anomalyScore = Math.max(0, Math.min(1, raw));
  return { anomaly_score: anomalyScore, is_anomaly: anomalyScore >= 0.35 };
}
