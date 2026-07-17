use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct LastLocation {
    pub lat: f64,
    pub lon: f64,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Transaction {
    pub id: String,
    pub account_id: String,
    pub amount: f64,
    pub currency: String,
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub beneficiary_id: Option<String>,
    pub device_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct ScoringContext {
    #[serde(default)]
    pub recent_amounts: Vec<f64>,
    #[serde(default)]
    pub recent_count_last_hour: u32,
    #[serde(default)]
    pub recent_sum_last_hour: f64,
    #[serde(default)]
    pub known_beneficiaries: Vec<String>,
    #[serde(default)]
    pub known_devices: Vec<String>,
    pub last_location: Option<LastLocation>,
}

#[derive(Debug, Deserialize)]
pub struct ScoreRequest {
    pub transaction: Transaction,
    #[serde(default)]
    pub context: ScoringContext,
}

#[derive(Debug, Clone, Serialize)]
pub struct TriggeredRule {
    pub rule: String,
    pub weight: u32,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum RiskBand {
    Low,
    Medium,
    High,
    Critical,
}

impl RiskBand {
    pub fn from_score(score: u32) -> Self {
        match score {
            0..=24 => RiskBand::Low,
            25..=54 => RiskBand::Medium,
            55..=79 => RiskBand::High,
            _ => RiskBand::Critical,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ScoreResponse {
    pub transaction_id: String,
    pub risk_score: u32,
    pub risk_band: RiskBand,
    pub triggered_rules: Vec<TriggeredRule>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AuditAppendRequest {
    pub event_type: String,
    pub subject_id: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AuditEntry {
    pub seq: u64,
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub event_type: String,
    pub subject_id: String,
    pub payload: serde_json::Value,
    pub prev_hash: String,
    pub hash: String,
}

#[derive(Debug, Serialize)]
pub struct VerifyResponse {
    pub valid: bool,
    pub entries_checked: u64,
    pub first_broken_seq: Option<u64>,
}
