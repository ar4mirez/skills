# Testing

Primary sources: the Book's testing chapter (https://doc.rust-lang.org/book/ch11-00-testing.html),
the Cargo targets reference (https://doc.rust-lang.org/cargo/reference/cargo-targets.html),
the proptest book (https://proptest-rs.github.io/proptest/), criterion
(https://bheisler.github.io/criterion.rs/book/), nextest (https://nexte.st), and
`#[sqlx::test]` (https://docs.rs/sqlx/0.9.0/sqlx/attr.test.html). All layouts here
run in the verified reference workspace.

## Contents
- Layers and layout
- Unit tests
- Integration tests
- Doc-tests
- Property tests (proptest)
- Service tests: real Postgres with #[sqlx::test]
- CLI tests
- Benchmarks (criterion)
- Fuzzing
- Miri and sanitizers
- Coverage
- Runner: cargo test vs nextest
- Lints in tests

## Layers and layout

| Layer | Where | Tests |
|---|---|---|
| Unit | `#[cfg(test)] mod tests` at the bottom of the module | Private functions and invariants; the most tests |
| Integration | `tests/*.rs` (each file is its own crate) | The public API only, as a user would call it |
| Doc | `///` and `//!` examples | That the documented usage compiles and works |
| Property | `tests/properties.rs` with proptest | Invariants for all inputs (round trips, idempotence) |
| HTTP | `crates/<api>/tests/*.rs` with `oneshot` and `#[sqlx::test]` | Status codes, validation, and queries against a real schema |
| CLI end to end | `crates/<cli>/tests/*.rs` spawning `CARGO_BIN_EXE_<name>` | Exit codes, stdout, and stderr |
| Bench | `benches/*.rs` (criterion, `harness = false`) | Performance regressions |
| Fuzz | `fuzz/` (cargo-fuzz, nightly) | Parsers of untrusted input |

Shared helpers for integration tests go in `tests/common/mod.rs` (Cargo does
not treat subdirectories of `tests/` as test crates).

## Unit tests

- Name tests for behavior: `rejects_non_canonical_codes`, not `test_parse_2`.
- One behavior per test; use `assert_eq!` with the expected value on the right
  and `assert_matches!` (1.96) for enum shapes.
- Tests may `unwrap()`: the panic message is the failure report. The
  workspace's `clippy.toml` allows it inside `#[test]` functions.
- Return `Result<(), E>` from a test when a chain of `?` reads better than
  unwraps.
- Deterministic by default: no wall clock (`tokio::time::pause()` in async
  tests), no network, no shared global state, and seeded randomness.

## Integration tests

Each `tests/<name>.rs` compiles as a separate crate linking your library, so it
sees only `pub` items. That catches accidental API breakage and keeps the
tests honest. Many files mean many link steps; group related tests into a few
files once link time hurts.

## Doc-tests

- Every public type's docs get a small example. Use `?` in examples with a
  trailing `# Ok::<(), acme_core::Error>(())` line (hidden with `#`).
- `cargo test` runs them (edition 2024 merges doc-tests into one binary, so
  they're fast). **nextest doesn't run doc-tests**, so CI runs
  `cargo test --doc` separately.
- Binary-only crates have no doc-tests, one more reason to put logic in a lib.

## Property tests (proptest)

Use proptest when a function has an invariant you can state: encode and decode
round-trip, parsing is idempotent, output stays within a charset, or sort
output is ordered. See `assets/core-properties.rs`:

```rust
proptest! {
    #[test]
    fn short_code_round_trips(id in any::<u64>()) {
        let code = ShortCode::from_id(id);
        prop_assert_eq!(code.as_str().parse::<ShortCode>().unwrap().to_id(), id);
    }
}
```
Failures shrink to a minimal case and are saved in `proptest-regressions/`.
**Commit that directory**: it replays the failure forever. Use `prop_assert!`
(not `assert!`) inside `proptest!` so shrinking works.

## Service tests: real Postgres with #[sqlx::test]

Don't mock the database. A repository trait with a fake implementation
tests your fake, not your SQL, and it doubles the code. `#[sqlx::test]` gives
each test a **fresh database** (created from `DATABASE_URL`, migrated from
`./migrations`, and dropped afterwards), so tests run in parallel without
interfering:

```rust
#[sqlx::test]
async fn create_show_and_follow(db: PgPool) {
    let res = app(AppState { db }, Duration::from_secs(5))
        .oneshot(Request::get("/up").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
}
```
- `tower::ServiceExt::oneshot` drives the router in-process: no port, no
  server, no flakiness. `http_body_util::BodyExt::collect` reads the body.
- `#[sqlx::test(fixtures("users"))]` loads `tests/fixtures/users.sql` first.
- Locally, `DATABASE_URL` must point at a server where the user can create
  databases. In CI, use a `postgres` service container (see
  `assets/github-ci.yml`).
- Test the contract per route: success, validation (422), conflict (409), and
  not found (404). Don't retest serde for every field.

## CLI tests

Structure the binary as `run(cli, &mut impl Write, impl BufRead) -> Result<()>`
and test it in-process (`assets/cli-main.rs`). Keep a few end-to-end tests
that spawn the real binary through `env!("CARGO_BIN_EXE_acme")` to check exit
codes (0 ok, 1 error, 2 usage) and stderr (`assets/cli-test.rs`). No
assert_cmd needed. Call `Cli::command().debug_assert()` in one test to catch
clap definition errors.

## Benchmarks (criterion)

- `benches/<name>.rs` with `[[bench]] name = "<name>" harness = false` in the
  crate's `Cargo.toml` (`assets/core-bench.rs`).
- Wrap inputs in `std::hint::black_box` so the optimizer can't delete the work.
- `cargo bench -p acme-core` stores baselines in `target/criterion`. Compare
  branches with `--save-baseline main`, then `--baseline main`.
- Benchmarks are noisy on shared CI runners. Run them locally or on dedicated
  hardware, and only gate on large regressions.
- `cargo test --all-targets` compiles benches, so CI still catches bench
  bit-rot without running them.

## Fuzzing

For parsers of untrusted input (file formats, protocols), use cargo-fuzz
(libFuzzer; needs nightly): `cargo +nightly fuzz init`, then
`cargo +nightly fuzz run <target>`. Keep the fuzz crate out of the workspace
members (cargo-fuzz generates its own manifest), and add found crashes as
regular unit tests. For structured inputs, derive `arbitrary::Arbitrary`.

## Miri and sanitizers

- Any crate with `unsafe` runs its tests under **Miri** (nightly):
  `rustup +nightly component add miri`, then `cargo +nightly miri test -p <crate>`.
  Miri detects undefined behavior (out-of-bounds access, use-after-free,
  invalid aliasing, and data races) in the code paths the tests exercise. It
  can't run FFI calls, and it's slow, so give it focused tests.
- Sanitizers are nightly too: `RUSTFLAGS="-Zsanitizer=address" cargo +nightly test
  --target <host-triple>`. Use them for FFI-heavy crates, where Miri can't go.
- Safe-only crates (`unsafe_code = "forbid"`) don't need either.

## Coverage

`cargo llvm-cov` (cargo-llvm-cov 0.9.1; it installs `llvm-tools-preview` on
first run) measures line and region coverage:
```bash
cargo llvm-cov nextest --workspace --lcov --output-path lcov.info
cargo llvm-cov --workspace --html        # local report in target/llvm-cov/html
```
Use coverage to find untested code, not as a target. A floor (for example
`--fail-under-lines 70`) is fine; chasing 100% produces brittle tests.

## Runner: cargo test vs nextest

`cargo test` is the baseline and the default. **cargo-nextest** runs each test
in its own process, in parallel across binaries, with better output, retries
(`--retries 2` for known-flaky tests), and JUnit output. Use it in CI once the
suite takes more than a minute. Remember that it skips doc-tests.

## Lints in tests

The workspace lints still apply to test code. `clippy.toml` sets
`allow-unwrap-in-tests`, `allow-expect-in-tests`, and `allow-print-in-tests`,
but those only cover `#[test]` functions and `#[cfg(test)]` modules, **not
helper functions in `tests/*.rs`**. Put
`#![allow(clippy::unwrap_used, reason = "...")]` at the top of an integration
test file that has helpers (as `assets/api-test.rs` does).
