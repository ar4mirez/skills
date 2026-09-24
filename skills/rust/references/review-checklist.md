# Rust code review checklist

Report findings **ranked by severity**. Give each one a file and line, what's
wrong, why it matters, and the concrete fix (code). Run
`python3 scripts/audit.py <root>` first for the structural checks it can
detect, then read the code for what it can't.

## Contents
- Critical: security and soundness
- High: correctness and reliability
- Medium: design and maintainability
- Low: hygiene
- How to write the review

## Critical: security and soundness

- [ ] SQL built with `format!` or string concatenation (or sqlx 0.9's
      `AssertSqlSafe(format!(..))`) instead of bind parameters or
      `QueryBuilder::push_bind`.
- [ ] `unsafe` without a `// SAFETY:` justification, `unsafe` in a crate
      that should `forbid` it, or unsound code (creating `&mut` aliases,
      `transmute` between unrelated types, `from_raw_parts` with an unchecked
      length).
- [ ] Hard-coded credentials, secrets in `Debug` output or logs, or secrets
      baked in with `env!`.
- [ ] `std::env::set_var`/`remove_var` at runtime (unsafe in 2024; UB with
      concurrent readers).
- [ ] Untrusted input without bounds: no body limit, unbounded `Vec`/`String`
      growth, unchecked integer arithmetic on lengths or money, or paths
      joined without a root check.
- [ ] Internal errors (SQL, driver, panic text) returned to clients.
- [ ] Missing authorization or tenant scoping on a query.

## High: correctness and reliability

- [ ] A std `Mutex`/`RwLock` guard held across `.await`.
- [ ] Blocking calls in async code: `std::thread::sleep`, `std::fs`,
      `reqwest::blocking`, CPU-heavy loops, or `block_on`.
- [ ] axum 0.7 route syntax (`/:id`, `/*rest`) on axum 0.8, which panics at
      startup.
- [ ] Multi-step writes without a transaction, or state changes split across
      `.await`s in a way that cancellation leaves half-done.
- [ ] Non-cancel-safe futures in `select!` loops.
- [ ] Outbound calls without timeouts; unbounded spawning or channels.
- [ ] `unwrap()`/`expect()`/indexing on data that can legitimately be absent
      or malformed (request paths, library APIs).
- [ ] No SIGTERM handling (in-flight requests are cut off on deploy).
- [ ] Migrations that break the previous release (dropping or renaming a
      column still in use).
- [ ] An Alpine runtime image for a glibc binary, or a debug build shipped.

## Medium: design and maintainability

- [ ] A library that exposes `anyhow::Error` or `Box<dyn Error>`, instead of a
      typed, `#[non_exhaustive]` error enum.
- [ ] Errors converted by string matching, or context lost (`map_err(|_| ..)`
      that drops the source).
- [ ] Stringly-typed data where a newtype or enum belongs; validation
      repeated at many call sites instead of in a constructor.
- [ ] A trait with one implementation added to mock the database; test
      against Postgres with `#[sqlx::test]` instead.
- [ ] `.clone()` used to silence the borrow checker in hot paths;
      `Arc<Mutex<_>>` for data one task could own.
- [ ] Runtime-checked `sqlx::query()` where `query!` would check the SQL at
      compile time, or query macros without committed `.sqlx/`.
- [ ] Workspace hygiene: no `resolver`, members not inheriting
      `[workspace.lints]`, versions pinned per member instead of in
      `[workspace.dependencies]`, `*` versions, no `Cargo.lock` for binaries.
- [ ] OpenSSL/native-tls pulled in where rustls works.
- [ ] Public items without docs in a library; missing `# Safety`/`# Errors`
      sections.
- [ ] Tests that mock what they should exercise, depend on wall-clock time
      or ordering, or miss the error paths.

## Low: hygiene

- [ ] Edition older than 2024; no `rust-toolchain.toml`; no `deny.toml`.
- [ ] `lazy_static`/`once_cell` (std `LazyLock`/`OnceLock`); `async-trait`
      where native async fn in traits works.
- [ ] tokio `full` feature; unused dependencies (`cargo machete`).
- [ ] `println!`/`dbg!` in library code; `#[allow]` where `#[expect(.., reason)]`
      would document and self-expire.
- [ ] `Arc<PgPool>` (the pool is already a handle).
- [ ] Release profile without `lto`/`codegen-units = 1` for shipped binaries.
- [ ] A container that runs as root.

## How to write the review

1. Start with a one-paragraph verdict: is it safe to merge, and what are the
   top two issues?
2. Then list findings by severity, each with location, why it matters in one
   sentence, and the fix as code.
3. Separate "must fix" from "consider". Don't bury a soundness bug among
   style nits.
4. Name what's good (a clean error type, or good property tests), so the
   author keeps doing it.
5. End with the commands to verify: `cargo fmt --check`,
   `cargo clippy --all-targets -- -D warnings`, `cargo test`, and
   `cargo deny check`.
