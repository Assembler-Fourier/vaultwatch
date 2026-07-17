use crate::models::{RiskBand, ScoreRequest, ScoreResponse, TriggeredRule};

/// Earth radius in km, used for the haversine impossible-travel check.
const EARTH_RADIUS_KM: f64 = 6371.0;

/// Fastest plausible ground/air travel speed a legitimate customer could
/// achieve between two logins/transactions. Above this, we assume the
/// credentials are being used from two places at once.
const IMPOSSIBLE_TRAVEL_KMH: f64 = 900.0;

fn haversine_km(a_lat: f64, a_lon: f64, b_lat: f64, b_lon: f64) -> f64 {
    let (lat1, lon1, lat2, lon2) = (
        a_lat.to_radians(),
        a_lon.to_radians(),
        b_lat.to_radians(),
        b_lon.to_radians(),
    );
    let dlat = lat2 - lat1;
    let dlon = lon2 - lon1;
    let h = (dlat / 2.0).sin().powi(2) + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().powi(2);
    2.0 * EARTH_RADIUS_KM * h.sqrt().asin()
}

fn mean_stddev(values: &[f64]) -> Option<(f64, f64)> {
    if values.len() < 3 {
        return None;
    }
    let mean = values.iter().sum::<f64>() / values.len() as f64;
    let variance =
        values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / values.len() as f64;
    Some((mean, variance.sqrt()))
}

/// Evaluates every rule against a transaction + its scoring context and
/// returns a capped 0-100 risk score with the rules that fired.
///
/// This is intentionally deterministic and LLM-free: it is the cheap,
/// always-on layer that runs before anything more expensive (the
/// scikit-learn pre-filter and the Claude agent tiers in agents-python)
/// ever sees the transaction.
pub fn score(req: &ScoreRequest) -> ScoreResponse {
    let tx = &req.transaction;
    let ctx = &req.context;
    let mut triggered: Vec<TriggeredRule> = Vec::new();

    // Rule: velocity by count in the last hour.
    if ctx.recent_count_last_hour >= 5 {
        triggered.push(TriggeredRule {
            rule: "velocity_count".into(),
            weight: 25,
            detail: format!(
                "{} transactions in the last hour (threshold 5)",
                ctx.recent_count_last_hour
            ),
        });
    }

    // Rule: velocity by cumulative amount in the last hour.
    let hourly_total = ctx.recent_sum_last_hour + tx.amount;
    if hourly_total > 5000.0 {
        triggered.push(TriggeredRule {
            rule: "velocity_amount".into(),
            weight: 20,
            detail: format!(
                "cumulative amount in the last hour is {hourly_total:.2} (threshold 5000.00)"
            ),
        });
    }

    // Rule: amount is a statistical outlier vs the account's own history.
    if let Some((mean, stddev)) = mean_stddev(&ctx.recent_amounts) {
        if stddev > 0.0 {
            let z = (tx.amount - mean) / stddev;
            if z > 3.0 {
                triggered.push(TriggeredRule {
                    rule: "amount_outlier".into(),
                    weight: 30,
                    detail: format!(
                        "amount {:.2} is {z:.1} standard deviations above the account mean ({mean:.2})",
                        tx.amount
                    ),
                });
            }
        }
    }

    // Rule: impossible travel between the last known location and this one.
    if let (Some(last), Some(lat), Some(lon)) = (&ctx.last_location, tx.lat, tx.lon) {
        let dist_km = haversine_km(last.lat, last.lon, lat, lon);
        let hours = (tx.timestamp - last.timestamp).num_seconds() as f64 / 3600.0;
        if hours > 0.0 {
            let speed_kmh = dist_km / hours;
            if speed_kmh > IMPOSSIBLE_TRAVEL_KMH {
                triggered.push(TriggeredRule {
                    rule: "impossible_travel".into(),
                    weight: 40,
                    detail: format!(
                        "{dist_km:.0}km in {hours:.2}h implies {speed_kmh:.0}km/h (threshold {IMPOSSIBLE_TRAVEL_KMH:.0}km/h)"
                    ),
                });
            }
        }
    }

    // Rule: paying a beneficiary that has never been seen on this account
    // for a materially large amount.
    if let Some(ben) = &tx.beneficiary_id {
        if !ctx.known_beneficiaries.iter().any(|b| b == ben) && tx.amount > 1000.0 {
            triggered.push(TriggeredRule {
                rule: "new_beneficiary_high_value".into(),
                weight: 25,
                detail: format!(
                    "first payment to beneficiary {ben} for {:.2} (threshold 1000.00)",
                    tx.amount
                ),
            });
        }
    }

    // Rule: transaction from a device never associated with this account.
    if let Some(dev) = &tx.device_id {
        if !ctx.known_devices.is_empty() && !ctx.known_devices.iter().any(|d| d == dev) {
            triggered.push(TriggeredRule {
                rule: "new_device".into(),
                weight: 10,
                detail: format!("device {dev} has not been seen on this account before"),
            });
        }
    }

    let risk_score = triggered.iter().map(|r| r.weight).sum::<u32>().min(100);

    ScoreResponse {
        transaction_id: tx.id.clone(),
        risk_score,
        risk_band: RiskBand::from_score(risk_score),
        triggered_rules: triggered,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{LastLocation, ScoringContext, Transaction};
    use chrono::{Duration, Utc};

    fn base_tx() -> Transaction {
        Transaction {
            id: "tx_1".into(),
            account_id: "acct_1".into(),
            amount: 40.0,
            currency: "EUR".into(),
            timestamp: Utc::now(),
            lat: Some(53.3498),
            lon: Some(-6.2603),
            beneficiary_id: Some("ben_known".into()),
            device_id: Some("dev_known".into()),
        }
    }

    fn base_ctx() -> ScoringContext {
        ScoringContext {
            recent_amounts: vec![38.0, 42.0, 35.0, 50.0, 44.0],
            recent_count_last_hour: 1,
            recent_sum_last_hour: 40.0,
            known_beneficiaries: vec!["ben_known".into()],
            known_devices: vec!["dev_known".into()],
            last_location: Some(LastLocation {
                lat: 53.3498,
                lon: -6.2603,
                timestamp: Utc::now() - Duration::hours(1),
            }),
        }
    }

    #[test]
    fn normal_transaction_scores_low() {
        let req = ScoreRequest {
            transaction: base_tx(),
            context: base_ctx(),
        };
        let resp = score(&req);
        assert_eq!(resp.risk_score, 0);
        assert!(resp.triggered_rules.is_empty());
    }

    #[test]
    fn impossible_travel_is_detected() {
        let mut tx = base_tx();
        // Dublin -> New York in six minutes is not possible commercially.
        tx.lat = Some(40.7128);
        tx.lon = Some(-74.0060);
        let mut ctx = base_ctx();
        ctx.last_location = Some(LastLocation {
            lat: 53.3498,
            lon: -6.2603,
            timestamp: tx.timestamp - Duration::minutes(6),
        });

        let resp = score(&ScoreRequest {
            transaction: tx,
            context: ctx,
        });

        assert!(resp
            .triggered_rules
            .iter()
            .any(|r| r.rule == "impossible_travel"));
        assert!(resp.risk_score >= 40);
    }

    #[test]
    fn amount_outlier_is_detected() {
        let mut tx = base_tx();
        tx.amount = 5000.0; // way above the ~40 average in base_ctx
        let resp = score(&ScoreRequest {
            transaction: tx,
            context: base_ctx(),
        });
        assert!(resp
            .triggered_rules
            .iter()
            .any(|r| r.rule == "amount_outlier"));
    }

    #[test]
    fn new_beneficiary_high_value_is_detected() {
        let mut tx = base_tx();
        tx.beneficiary_id = Some("ben_unknown".into());
        tx.amount = 2500.0;
        let mut ctx = base_ctx();
        ctx.recent_amounts = vec![2000.0, 2100.0, 1900.0, 2200.0]; // avoid also tripping outlier
        let resp = score(&ScoreRequest {
            transaction: tx,
            context: ctx,
        });
        assert!(resp
            .triggered_rules
            .iter()
            .any(|r| r.rule == "new_beneficiary_high_value"));
    }

    #[test]
    fn multiple_rules_stack_and_cap_at_100() {
        let mut tx = base_tx();
        tx.amount = 9000.0;
        tx.beneficiary_id = Some("ben_unknown".into());
        tx.device_id = Some("dev_unknown".into());
        tx.lat = Some(-33.8688);
        tx.lon = Some(151.2093); // Sydney

        let mut ctx = base_ctx();
        ctx.recent_count_last_hour = 6;
        ctx.recent_sum_last_hour = 4000.0;
        ctx.last_location = Some(LastLocation {
            lat: 53.3498,
            lon: -6.2603,
            timestamp: tx.timestamp - Duration::minutes(10),
        });

        let resp = score(&ScoreRequest {
            transaction: tx,
            context: ctx,
        });
        assert!(resp.risk_score <= 100);
        assert!(resp.triggered_rules.len() >= 4);
        assert_eq!(resp.risk_score, 100);
    }
}
