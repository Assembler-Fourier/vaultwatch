mod audit;
mod models;
mod rules;

use axum::{
    extract::{Query, State},
    routing::{get, post},
    Json, Router,
};
use models::{AuditAppendRequest, ScoreRequest};
use serde::Deserialize;
use std::path::PathBuf;
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

struct AppState {
    audit: audit::AuditLog,
}

async fn health() -> &'static str {
    "ok"
}

async fn score_transaction(
    Json(req): Json<ScoreRequest>,
) -> Json<models::ScoreResponse> {
    Json(rules::score(&req))
}

async fn append_audit(
    State(state): State<Arc<AppState>>,
    Json(req): Json<AuditAppendRequest>,
) -> Json<models::AuditEntry> {
    let entry = state.audit.append(req.event_type, req.subject_id, req.payload);
    Json(entry)
}

async fn verify_audit(State(state): State<Arc<AppState>>) -> Json<models::VerifyResponse> {
    Json(state.audit.verify())
}

#[derive(Deserialize)]
struct RecentParams {
    limit: Option<usize>,
}

async fn recent_audit(
    State(state): State<Arc<AppState>>,
    Query(params): Query<RecentParams>,
) -> Json<Vec<models::AuditEntry>> {
    Json(state.audit.recent(params.limit.unwrap_or(50)))
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let audit_path: PathBuf = std::env::var("AUDIT_LOG_PATH")
        .unwrap_or_else(|_| "./data/audit.log".to_string())
        .into();

    let audit = audit::AuditLog::open(audit_path).expect("failed to open audit log");
    let state = Arc::new(AppState { audit });

    let app = Router::new()
        .route("/healthz", get(health))
        .route("/v1/score", post(score_transaction))
        .route("/v1/audit/append", post(append_audit))
        .route("/v1/audit/verify", get(verify_audit))
        .route("/v1/audit/recent", get(recent_audit))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8081);
    let addr = format!("0.0.0.0:{port}");
    tracing::info!("engine-rust listening on {addr}");

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
