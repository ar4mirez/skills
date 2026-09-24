# Quality gate and security

Primary sources: rustfmt and clippy docs (https://rust-lang.github.io/rustfmt/,
https://doc.rust-lang.org/clippy/), the Cargo book (`[lints]`, `build.warnings`),
cargo-deny (https://embarkstudios.github.io/cargo-deny/), RustSec
(https://rustsec.org), the Rustonomicon (https://doc.rust-lang.org/nomicon/), and
Miri (https://github.com/rust-lang/miri).

## Contents
- The gate (what CI runs)
- rustfmt
- clippy and the lint set
- Zero warnings without RUSTFLAGS
- Supply chain: cargo-deny, advisories, unused dependencies
- Unsafe policy
- Input handling
- Secrets
- Other security defaults
- CI template notes

## The gate (what CI runs)

In order, all with `--locked` (see `assets/github-ci.yml`, verified locally):

1. `cargo fmt --all --check`
2. `cargo clippy --workspace --all-targets --all-features -- -D warnings`
3. `cargo sqlx prepare --workspace --check` (services with sqlx)
4. `cargo nextest run --workspace --all-features` and `cargo test --doc`
5. `cargo doc --workspace --no-deps` (broken intra-doc links fail)
6. `cargo deny check` (advisories, licenses, bans, and sources)
7. `cargo machete` (unused dependencies)
8. `cargo build --release`

Run the same commands locally before pushing. The job's env sets
`CARGO_BUILD_WARNINGS=deny`, so any warning in any step fails.

## rustfmt

Default style, no bikeshedding. `rustfmt.toml` sets only
`style_edition = "2024"` so formatting doesn't shift when the edition or
toolchain changes. Unstable options (`imports_granularity`,
`group_imports`) need nightly rustfmt; don't use them on a stable gate.

## clippy and the lint set

The lints live in `[workspace.lints]` (`assets/workspace-Cargo.toml`), and
every member opts in with `[lints] workspace = true`. Without that line,
the member silently gets none of them.

- `clippy::pedantic` at `warn` with `priority = -1`, so individual lints
  listed after it override the group. Opt out of the noisy ones for
  application code: `missing_errors_doc`, `missing_panics_doc`, and
  `must_use_candidate`. Libraries published to crates.io should keep the
  `*_doc` lints.
- Restriction lints worth having everywhere: `unwrap_used`, `expect_used`,
  `dbg_macro`, `todo`, `unimplemented`, `print_stdout`, `print_stderr`, and
  `large_futures`.
- Rust lints: `unsafe_code = "forbid"`, `missing_debug_implementations`,
  `unreachable_pub`, and the `rust_2018_idioms` group.
- Don't enable `clippy::restriction` or `clippy::nursery` wholesale: they
  contradict each other and churn every release.
- Local exceptions use `#[expect(lint, reason = "...")]` (stable since 1.81),
  not `#[allow]`: `expect` warns when the exception is no longer needed.
- `clippy.toml` holds lint configuration (test exemptions). Clippy reads the
  MSRV from `rust-version`, so it won't suggest APIs newer than your MSRV.

## Zero warnings without RUSTFLAGS

Cargo 1.97 stabilized `build.warnings`. `CARGO_BUILD_WARNINGS=deny` (or
`[build] warnings = "deny"` in `.cargo/config.toml`) turns local lint warnings
into errors for build, clippy, test, and doc (verified), and it doesn't change
`RUSTFLAGS`, which would invalidate the build cache between local and CI runs.
Dependencies are unaffected (their lints are capped anyway). Keep
`-- -D warnings` on the clippy line as well, for readers and older toolchains.

Don't put `#![deny(warnings)]` in source: a new compiler's new lint then
breaks downstream users' builds of your crate.

## Supply chain: cargo-deny, advisories, unused dependencies

- **cargo-deny** (`assets/deny.toml`) is the one supply-chain tool:
  - `advisories`: the RustSec database (vulnerable, unmaintained, and yanked
    crates). This covers cargo-audit's job, so you don't need both. Every
    `ignore` entry needs an id, a reason, and an owner.
  - `licenses`: an allowlist of permissive licenses; `private.ignore = true`
    skips your unpublished crates.
  - `bans`: deny `openssl-sys`/`native-tls` (rustls instead), deny
    wildcards (with `allow-wildcard-paths = true` for workspace path deps),
    and warn on duplicate versions.
  - `sources`: crates.io only; any git or other registry is an explicit
    decision.
- **cargo-machete** finds dependencies no code uses. It's fast and heuristic
  (it greps sources), so macro-only uses may need
  `[package.metadata.cargo-machete] ignored = ["..."]`. Cargo's built-in
  `unused_dependencies` lint is still nightly-only.
- Commit `Cargo.lock` for anything with a binary, and build with `--locked`.
- Review new dependencies: maintenance, `unsafe` usage, transitive weight
  (`cargo tree -e normal -p <crate>`), and whether std or an existing
  dependency already covers it.
- Updates: a scheduled `cargo update` PR (Dependabot or Renovate) with the full
  gate. Upgrade semver-major versions deliberately.

## Unsafe policy

1. **Default: `unsafe_code = "forbid"`** in `[workspace.lints.rust]`. Most
   application and service code never needs `unsafe`.
2. If a crate genuinely needs it (FFI, a measured hot path, a data structure),
   isolate it in **one small crate or module** that exposes a safe API, and
   override only there: `[lints.rust] unsafe_code = "deny"` in that crate, plus
   `#[expect(unsafe_code, reason = "...")]` on the specific module. Other
   crates stay `forbid`.
3. Every `unsafe` block has a `// SAFETY:` comment directly above it that
   names the invariant that makes it sound and why it holds here. Every
   `unsafe fn` has a `# Safety` doc section that states what callers must
   uphold. Enable `clippy::undocumented_unsafe_blocks` in that crate.
4. In edition 2024, `unsafe fn` bodies need explicit `unsafe {}` blocks
   (`unsafe_op_in_unsafe_fn`), and FFI uses `unsafe extern "C"` and
   `#[unsafe(no_mangle)]`.
5. Tests for the unsafe module run under **Miri** in CI (nightly job), plus
   sanitizers for FFI (see `testing.md`).
6. Before writing `unsafe` for speed, show the benchmark. `get_unchecked`
   rarely beats an iterator, which already elides bounds checks.

## Input handling

- Parse untrusted input into types at the boundary (serde + newtypes with
  `TryFrom`); `#[serde(deny_unknown_fields)]` on API inputs.
- Bound everything: request body size (a tower-http limit), string and
  collection lengths (validate in constructors), recursion depth, and timeouts.
  serde_json has a default recursion limit (128); keep it.
- Integer arithmetic on untrusted values: `checked_*`, `saturating_*`, or
  `try_from` conversions. Release builds wrap on overflow silently
  (`overflow-checks` is off by default in release).
- SQL: bind parameters (`$1`) only. In sqlx 0.9 a runtime string needs
  `AssertSqlSafe`, which should be rare and reviewed.
- Paths from users: canonicalize and check that the result is inside an
  allowed root, and never join untrusted input onto a path without that check.
- Redirects and URLs: validate the scheme (`https`/`http` only) to block
  `javascript:` and `file:` URLs.
- Deserializing untrusted data: serde_json and similar are fine; never use
  formats that can instantiate arbitrary types.

## Secrets

- From the environment (Kamal `env.secret`), read once into `Config`, with a
  hand-written `Debug` that redacts them. Never log a config or request that
  contains secrets.
- Don't embed secrets in binaries (`env!` at compile time bakes them into the
  artifact).
- For in-memory secrets that must not leak through `Debug` or logs, the
  `secrecy` crate's `SecretString` is a reasonable wrapper (verify the current
  version before adding it).
- Compare secrets and MACs in constant time (`subtle::ConstantTimeEq`); `==`
  on byte slices exits early.
- Passwords: `argon2` (in `spawn_blocking`), never a fast hash.
- TLS: `rustls` everywhere (reqwest and sqlx `tls-rustls` features).

## Other security defaults

- `overflow-checks = true` in `[profile.release]` for code where wrapping
  would be a security bug (finance, lengths, and indices) is cheap. Measure
  if in doubt.
- `panic = "abort"` doesn't make a service safer. Keep unwind and
  `CatchPanicLayer` so one bad request doesn't take the process down.
- Run the container as non-root (distroless `:nonroot`), with a read-only
  filesystem where possible.

## CI template notes

`assets/github-ci.yml`:
- `rustup toolchain install` with no arguments installs the toolchain and
  components named in `rust-toolchain.toml`.
- `Swatinem/rust-cache@v2` caches `~/.cargo` and `target/`.
- `taiki-e/install-action@v2` installs prebuilt cargo-nextest, cargo-deny, and
  cargo-machete. sqlx-cli isn't in its manifest, so it's built with
  `cargo install --locked` (cached after the first run).
- The Postgres service container backs `#[sqlx::test]`, and
  `SQLX_OFFLINE=true` keeps compilation independent of it.
- Add an MSRV job for published libraries
  (`cargo +<msrv> check --workspace --all-features`), and a nightly Miri job
  for crates with `unsafe`.
- Action versions verified September 2026: `actions/checkout@v7`,
  `Swatinem/rust-cache@v2` (2.9.2), `taiki-e/install-action@v2` (2.87).
