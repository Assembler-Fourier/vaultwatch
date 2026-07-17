// TS port of engine-rust's deterministic rules engine (src/rules.rs).
// Showcase mode has no separate Rust service to call, so the same rule
// logic is reimplemented here rather than stubbed out - the scoring
// behaviour a reviewer sees in the live demo is real, not decorative.

import type { RuleEngineVerdict, Transaction, TriggeredRule } from "./types";

const EARTH_RADIUS_KM = 6371.0;
const IMPOSSIBLE_TRAVEL_KMH = 900.0;

interface ScoringContext {
  recent_amounts: number[];
  recent_count_last_hour: number;
  recent_sum_last_hour: number;
  known_beneficiaries: string[];
  known_devices: string[];
  last_location: { lat: number; lon: number; timestamp: string } | null;
}

function haversineKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const [lat1, lon1, lat2, lon2] = [toRad(aLat), toRad(aLon), toRad(bLat), toRad(bLon)];
  const dlat = lat2 - lat1;
  const dlon = lon2 - lon1;
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

function meanStddev(values: number[]): [number, number] | null {
  if (values.length < 3) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, v) => a + (v - mean) ** 2, 0) / values.length;
  return [mean, Math.sqrt(variance)];
}

export function scoreTransaction(tx: Transaction, ctx: ScoringContext): RuleEngineVerdict {
  const triggered: TriggeredRule[] = [];

  if (ctx.recent_count_last_hour >= 5) {
    triggered.push({
      rule: "velocity_count",
      weight: 25,
      detail: `${ctx.recent_count_last_hour} transactions in the last hour (threshold 5)`,
    });
  }

  const hourlyTotal = ctx.recent_sum_last_hour + tx.amount;
  if (hourlyTotal > 5000) {
    triggered.push({
      rule: "velocity_amount",
      weight: 20,
      detail: `cumulative amount in the last hour is ${hourlyTotal.toFixed(2)} (threshold 5000.00)`,
    });
  }

  const stats = meanStddev(ctx.recent_amounts);
  if (stats) {
    const [mean, stddev] = stats;
    if (stddev > 0) {
      const z = (tx.amount - mean) / stddev;
      if (z > 3.0) {
        triggered.push({
          rule: "amount_outlier",
          weight: 30,
          detail: `amount ${tx.amount.toFixed(2)} is ${z.toFixed(1)} standard deviations above the account mean (${mean.toFixed(2)})`,
        });
      }
    }
  }

  if (ctx.last_location && tx.lat != null && tx.lon != null) {
    const dist = haversineKm(ctx.last_location.lat, ctx.last_location.lon, tx.lat, tx.lon);
    const hours = (new Date(tx.timestamp).getTime() - new Date(ctx.last_location.timestamp).getTime()) / 3.6e6;
    if (hours > 0) {
      const speed = dist / hours;
      if (speed > IMPOSSIBLE_TRAVEL_KMH) {
        triggered.push({
          rule: "impossible_travel",
          weight: 40,
          detail: `${dist.toFixed(0)}km in ${hours.toFixed(2)}h implies ${speed.toFixed(0)}km/h (threshold ${IMPOSSIBLE_TRAVEL_KMH}km/h)`,
        });
      }
    }
  }

  if (tx.beneficiary_id && !ctx.known_beneficiaries.includes(tx.beneficiary_id) && tx.amount > 1000) {
    triggered.push({
      rule: "new_beneficiary_high_value",
      weight: 25,
      detail: `first payment to beneficiary ${tx.beneficiary_id} for ${tx.amount.toFixed(2)} (threshold 1000.00)`,
    });
  }

  if (tx.device_id && ctx.known_devices.length > 0 && !ctx.known_devices.includes(tx.device_id)) {
    triggered.push({
      rule: "new_device",
      weight: 10,
      detail: `device ${tx.device_id} has not been seen on this account before`,
    });
  }

  const riskScore = Math.min(100, triggered.reduce((sum, r) => sum + r.weight, 0));
  const riskBand = riskScore >= 80 ? "critical" : riskScore >= 55 ? "high" : riskScore >= 25 ? "medium" : "low";

  return { transaction_id: tx.id, risk_score: riskScore, risk_band: riskBand, triggered_rules: triggered };
}
