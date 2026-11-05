//! The service's settings from the environment (compose). No secret is ever read from the environment: the database
//! password and the broker passwords come from files (docker secrets).
//!
//! | Variable | Default | Meaning |
//! |---|---|---|
//! | `INGEST_DB` | (required) | libpq string without password, e.g. `host=db dbname=balik user=sensors_ingest` |
//! | `INGEST_DB_PASSWORD_FILE` | `/run/secrets/sensors_ingest_db` | the role's password (first line) |
//! | `INGEST_SECRETS_DIR` | `/run/secrets` | where each connection's `secret_file` is |
//! | `INGEST_MQTT_CA_FILE` | `/etc/ssl/certs/ca-certificates.crt` | CA bundle for TLS connections |
//! | `INGEST_HTTP` | `0.0.0.0:8080` | /healthz and /decode |
//! | `INGEST_BATCH_MS` | 250 | longest wait before a batch is committed |
//! | `INGEST_BATCH_MAX` | 20000 | largest batch |
//! | `INGEST_QUEUE` | 40000 | queue between readers and writer (>= broker `max_inflight_messages`, 20000) |

use crate::service::Settings;
use crate::supervisor::Options;
use std::str::FromStr;

/// Builds the options from a variable lookup and a file reader (both injected for tests).
pub fn options(
    var: impl Fn(&str) -> Option<String>,
    read: impl Fn(&str) -> std::io::Result<String>,
) -> Result<Options, String> {
    let conninfo = var("INGEST_DB").filter(|s| !s.trim().is_empty()).ok_or("INGEST_DB is not set")?;
    let parsed = tokio_postgres::Config::from_str(&conninfo).map_err(|e| format!("INGEST_DB: {e}"))?;
    if parsed.get_password().is_some() {
        return Err("INGEST_DB must not hold a password: put it in INGEST_DB_PASSWORD_FILE".into());
    }
    let pw_file = var("INGEST_DB_PASSWORD_FILE").unwrap_or_else(|| "/run/secrets/sensors_ingest_db".into());
    let password = read(&pw_file).map_err(|e| format!("INGEST_DB_PASSWORD_FILE {pw_file}: {e}"))?;
    let password = password.lines().next().unwrap_or("").to_string();
    fn num<T: std::str::FromStr + PartialOrd + From<u8>>(
        var: &impl Fn(&str) -> Option<String>,
        name: &str,
        default: T,
    ) -> Result<T, String> {
        match var(name) {
            None => Ok(default),
            Some(s) => match s.trim().parse::<T>() {
                Ok(v) if v >= T::from(1u8) => Ok(v),
                _ => Err(format!("{name}={s:?} is not a positive whole number")),
            },
        }
    }
    let mut settings = Settings::new(&conninfo);
    settings.password = Some(password);
    settings.batch_ms = num(&var, "INGEST_BATCH_MS", 250u64)?;
    settings.batch_max = num(&var, "INGEST_BATCH_MAX", 20_000usize)?;
    let queue_capacity = num(&var, "INGEST_QUEUE", 40_000usize)?;
    let http = var("INGEST_HTTP").unwrap_or_else(|| "0.0.0.0:8080".into());
    let http_addr = Some(http.parse().map_err(|e| format!("INGEST_HTTP={http:?}: {e}"))?);
    Ok(Options {
        settings,
        secrets_dir: var("INGEST_SECRETS_DIR").unwrap_or_else(|| "/run/secrets".into()).into(),
        ca_file: var("INGEST_MQTT_CA_FILE").unwrap_or_else(|| "/etc/ssl/certs/ca-certificates.crt".into()),
        queue_capacity,
        http_addr,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn run(vars: &[(&str, &str)], files: &[(&str, &str)]) -> Result<Options, String> {
        let v: HashMap<String, String> = vars.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect();
        let f: HashMap<String, String> = files.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect();
        options(
            |k| v.get(k).cloned(),
            |p| f.get(p).cloned().ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, p.to_string())),
        )
    }

    #[test]
    fn defaults_and_the_password_from_its_file() {
        let o = run(
            &[("INGEST_DB", "host=db dbname=balik user=sensors_ingest")],
            &[("/run/secrets/sensors_ingest_db", "s3cret\n")],
        )
        .unwrap();
        assert_eq!(o.settings.conninfo, "host=db dbname=balik user=sensors_ingest");
        assert_eq!(o.settings.password.as_deref(), Some("s3cret"));
        assert_eq!(o.settings.role, None);
        // bench: a 20000-message broker window drains 9074 msg/s, a 5000 window 5278 (BENCH.md)
        assert_eq!((o.settings.batch_ms, o.settings.batch_max, o.queue_capacity), (250, 20_000, 40_000));
        assert_eq!(o.http_addr, Some("0.0.0.0:8080".parse().unwrap()));
        assert_eq!(o.secrets_dir, std::path::PathBuf::from("/run/secrets"));
    }

    #[test]
    fn a_missing_database_or_password_file_or_a_bad_number_is_refused_with_its_name() {
        assert!(run(&[], &[]).unwrap_err().contains("INGEST_DB"));
        assert!(run(&[("INGEST_DB", "host=db")], &[]).unwrap_err().contains("sensors_ingest_db"));
        let e =
            run(&[("INGEST_DB", "host=db"), ("INGEST_BATCH_MS", "soon")], &[("/run/secrets/sensors_ingest_db", "x")])
                .unwrap_err();
        assert!(e.contains("INGEST_BATCH_MS"), "{e}");
        let e = run(&[("INGEST_DB", "host=db"), ("INGEST_QUEUE", "0")], &[("/run/secrets/sensors_ingest_db", "x")])
            .unwrap_err();
        assert!(e.contains("INGEST_QUEUE"), "{e}");
    }

    #[test]
    fn a_password_in_the_connection_string_is_refused() {
        let e = run(&[("INGEST_DB", "host=db password=oops")], &[("/run/secrets/sensors_ingest_db", "x")]).unwrap_err();
        assert!(e.contains("password"), "{e}");
    }
}
