//! Acme short-link service. `main.rs` only wires process concerns (config, telemetry,
//! signals); everything testable lives here so integration tests can build the same router.
pub mod config;
pub mod error;
pub mod links;

use std::time::Duration;

use axum::http::StatusCode;
use axum::{Router, routing::get};
use sqlx::PgPool;
use tower_http::catch_panic::CatchPanicLayer;
use tower_http::limit::RequestBodyLimitLayer;
use tower_http::request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer};
use tower_http::timeout::TimeoutLayer;
use tower_http::trace::TraceLayer;

/// Shared, cheaply cloneable handler state. `PgPool` is already an `Arc` inside:
/// never wrap it in another `Arc` or a `Mutex`.
#[derive(Debug, Clone)]
pub struct AppState {
    pub db: PgPool,
}

/// Builds the full application: routes plus the tower middleware stack.
pub fn app(state: AppState, request_timeout: Duration) -> Router {
    Router::new()
        .route("/up", get(|| async { "ok" }))
        .merge(links::router())
        .with_state(state)
        // Layers wrap everything added before them; the last one added runs first.
        .layer(RequestBodyLimitLayer::new(64 * 1024))
        .layer(TimeoutLayer::with_status_code(
            StatusCode::REQUEST_TIMEOUT,
            request_timeout,
        ))
        .layer(CatchPanicLayer::new())
        .layer(TraceLayer::new_for_http())
        .layer(PropagateRequestIdLayer::x_request_id())
        .layer(SetRequestIdLayer::x_request_id(MakeRequestUuid))
}
