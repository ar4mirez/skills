//! Typed configuration, read from the environment exactly once at startup.
use std::fmt;
use std::num::ParseIntError;
use std::time::Duration;

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("missing required environment variable {0}")]
    Missing(&'static str),
    #[error("environment variable {name} is invalid: {source}")]
    Invalid {
        name: &'static str,
        source: ParseIntError,
    },
    #[error("environment variable {0} is out of range")]
    OutOfRange(&'static str),
}

/// Service configuration. `Debug` is hand-written so secrets never reach logs.
#[derive(Clone)]
pub struct Config {
    pub database_url: String,
    pub port: u16,
    pub db_max_connections: u32,
    pub request_timeout: Duration,
}

impl Config {
    /// Reads the process environment.
    pub fn from_env() -> Result<Self, ConfigError> {
        Self::from_lookup(|key| std::env::var(key).ok())
    }

    /// Reads from any key/value source. Tests pass a closure over a map instead of
    /// mutating the process environment (`std::env::set_var` is `unsafe` in edition 2024).
    pub fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Result<Self, ConfigError> {
        let number = |name: &'static str, default: u64| -> Result<u64, ConfigError> {
            get(name).map_or(Ok(default), |v| {
                v.parse()
                    .map_err(|source| ConfigError::Invalid { name, source })
            })
        };
        let port = number("PORT", 3000)?;
        let max_conn = number("DB_MAX_CONNECTIONS", 10)?;
        Ok(Self {
            database_url: get("DATABASE_URL").ok_or(ConfigError::Missing("DATABASE_URL"))?,
            port: u16::try_from(port).map_err(|_| ConfigError::OutOfRange("PORT"))?,
            db_max_connections: u32::try_from(max_conn)
                .map_err(|_| ConfigError::OutOfRange("DB_MAX_CONNECTIONS"))?,
            request_timeout: Duration::from_secs(number("REQUEST_TIMEOUT_SECS", 10)?),
        })
    }
}

impl fmt::Debug for Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Config")
            .field("database_url", &"<redacted>")
            .field("port", &self.port)
            .field("db_max_connections", &self.db_max_connections)
            .field("request_timeout", &self.request_timeout)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn lookup(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        move |key| map.get(key).cloned()
    }

    #[test]
    fn defaults_apply() {
        let cfg =
            Config::from_lookup(lookup(&[("DATABASE_URL", "postgres://u:secret@h/db")])).unwrap();
        assert_eq!(cfg.port, 3000);
        assert_eq!(cfg.request_timeout, Duration::from_secs(10));
        assert!(
            !format!("{cfg:?}").contains("secret"),
            "Debug must redact the URL"
        );
    }

    #[test]
    fn missing_and_invalid() {
        assert!(matches!(
            Config::from_lookup(lookup(&[])),
            Err(ConfigError::Missing("DATABASE_URL"))
        ));
        let bad = Config::from_lookup(lookup(&[("DATABASE_URL", "x"), ("PORT", "http")]));
        assert!(matches!(
            bad,
            Err(ConfigError::Invalid { name: "PORT", .. })
        ));
    }
}
