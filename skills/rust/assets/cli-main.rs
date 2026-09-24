//! `acme`: turn text into slugs and ids into short codes (and back).
//!
//! Exit codes: 0 success, 1 runtime error, 2 usage error (clap's default).
use std::io::{self, BufRead, Write};
use std::process::ExitCode;

use acme_core::{ShortCode, Slug};
use anyhow::{Context, Result};
use clap::{Parser, Subcommand};

/// Slugs and short codes for Acme links.
#[derive(Debug, Parser)]
#[command(version, about)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Normalize text into a URL slug. Reads lines from stdin when no TEXT is given.
    Slug {
        /// Text to slugify.
        text: Option<String>,
    },
    /// Encode a numeric id as a base62 short code.
    Encode {
        /// The id to encode.
        id: u64,
    },
    /// Decode a base62 short code back to its id.
    Decode {
        /// The short code to decode.
        code: String,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let stdout = io::stdout();
    match run(cli, &mut stdout.lock(), io::stdin().lock()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            // `{:#}` prints the whole context chain on one line: "decoding \"x\": invalid ..."
            #[expect(clippy::print_stderr, reason = "the CLI's error channel")]
            {
                eprintln!("error: {err:#}");
            }
            ExitCode::FAILURE
        }
    }
}

/// All logic takes its I/O as parameters, so tests drive it without spawning a process.
fn run(cli: Cli, out: &mut impl Write, input: impl BufRead) -> Result<()> {
    match cli.command {
        Command::Slug { text: Some(text) } => {
            writeln!(
                out,
                "{}",
                Slug::parse(&text).with_context(|| format!("slugifying {text:?}"))?
            )?;
        }
        Command::Slug { text: None } => {
            for line in input.lines() {
                let line = line.context("reading stdin")?;
                writeln!(
                    out,
                    "{}",
                    Slug::parse(&line).with_context(|| format!("slugifying {line:?}"))?
                )?;
            }
        }
        Command::Encode { id } => writeln!(out, "{}", ShortCode::from_id(id))?,
        Command::Decode { code } => {
            let parsed: ShortCode = code.parse().with_context(|| format!("decoding {code:?}"))?;
            writeln!(out, "{}", parsed.to_id())?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run_args(args: &[&str], stdin: &str) -> Result<String> {
        let cli = Cli::try_parse_from(std::iter::once("acme").chain(args.iter().copied()))?;
        let mut out = Vec::new();
        run(cli, &mut out, stdin.as_bytes())?;
        Ok(String::from_utf8(out)?)
    }

    #[test]
    fn slug_from_arg_and_stdin() {
        assert_eq!(
            run_args(&["slug", "Hello World"], "").unwrap(),
            "hello-world\n"
        );
        assert_eq!(run_args(&["slug"], "A b\nC d\n").unwrap(), "a-b\nc-d\n");
    }

    #[test]
    fn encode_decode() {
        assert_eq!(run_args(&["encode", "125"], "").unwrap(), "21\n");
        assert_eq!(run_args(&["decode", "21"], "").unwrap(), "125\n");
        assert!(run_args(&["decode", "!!"], "").is_err());
    }

    #[test]
    fn clap_definition_is_valid() {
        use clap::CommandFactory;
        Cli::command().debug_assert();
    }
}
