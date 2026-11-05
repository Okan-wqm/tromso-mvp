//! The ingest service binary: settings from the environment (`env.rs`), JSON logs to stdout, SIGTERM or SIGINT stop
//! it cleanly (queue committed and acknowledged, then DISCONNECT; the broker keeps the session).

use sensors_ingest::{env, supervisor};
use tokio::sync::watch;

#[tokio::main]
async fn main() -> std::process::ExitCode {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();
    let opts = match env::options(|k| std::env::var(k).ok(), |p| std::fs::read_to_string(p)) {
        Ok(o) => o,
        Err(e) => {
            tracing::error!(error = %e, "settings refused");
            return std::process::ExitCode::from(2);
        }
    };
    let (stop, stop_rx) = watch::channel(false);
    tokio::spawn(async move {
        wait_for_signal().await;
        tracing::info!("stop requested: committing and acknowledging what is queued");
        let _ = stop.send(true);
    });
    match supervisor::run(opts, stop_rx).await {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(e) => {
            tracing::error!(error = %e, "ingest failed");
            std::process::ExitCode::FAILURE
        }
    }
}

#[cfg(unix)]
async fn wait_for_signal() {
    use tokio::signal::unix::{SignalKind, signal};
    match (signal(SignalKind::terminate()), signal(SignalKind::interrupt())) {
        (Ok(mut t), Ok(mut i)) => {
            tokio::select! {
                _ = t.recv() => {}
                _ = i.recv() => {}
            }
        }
        _ => {
            let _ = tokio::signal::ctrl_c().await;
        }
    }
}

#[cfg(not(unix))]
async fn wait_for_signal() {
    let _ = tokio::signal::ctrl_c().await;
}
