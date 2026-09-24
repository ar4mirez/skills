//! Process wiring: config, telemetry, database, migrations, and graceful shutdown.
use std::net::{Ipv4Addr, SocketAddr};

use acme_api::config::Config;
use acme_api::{AppState, app};
use anyhow::Context;
use sqlx::postgres::PgPoolOptions;
use tokio::net::TcpListener;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let config = Config::from_env().context("loading configuration")?;
    tracing::info!(?config, "starting");

    let db = PgPoolOptions::new()
        .max_connections(config.db_max_connections)
        .connect(&config.database_url)
        .await
        .context("connecting to Postgres")?;
    // Embedded at compile time; Postgres advisory locks make concurrent boots safe.
    sqlx::migrate!()
        .run(&db)
        .await
        .context("running migrations")?;

    let listener = TcpListener::bind(SocketAddr::from((Ipv4Addr::UNSPECIFIED, config.port)))
        .await
        .with_context(|| format!("binding port {}", config.port))?;
    tracing::info!(addr = %listener.local_addr()?, "listening");

    axum::serve(
        listener,
        app(AppState { db: db.clone() }, config.request_timeout),
    )
    .with_graceful_shutdown(shutdown_signal())
    .await
    .context("serving HTTP")?;

    db.close().await;
    tracing::info!("stopped");
    Ok(())
}

/// Resolves on Ctrl-C or SIGTERM (what `docker stop` and Kamal send), letting in-flight
/// requests finish before the process exits.
async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(err) = tokio::signal::ctrl_c().await {
            tracing::error!(%err, "cannot listen for Ctrl-C");
        }
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut sig) => {
                sig.recv().await;
            }
            Err(err) => tracing::error!(%err, "cannot listen for SIGTERM"),
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
    tracing::info!("shutdown signal received");
}
