# Setup, versions, and project layout

Versions were verified in September 2026 against the Rust release notes
(https://github.com/rust-lang/rust/blob/master/RELEASES.md), the Cargo book
shipped with 1.98.1 (https://doc.rust-lang.org/cargo/), and crates.io. In an
existing repo, `Cargo.lock` and `rust-toolchain.toml` win; for new code, take
the latest patch of these.

## Contents
- Current versions
- What changed recently (1.94 to 1.98)
- Toolchain pin and MSRV policy
- Editions and the resolver
- Layout: library, CLI, service, workspace
- The workspace manifest
- Features
- Starting a new project

## Current versions

| Component | Version | Notes |
|---|---|---|
| Rust | **1.98.1** (2026-09-03) | Six-week train; 1.99 is due in October 2026 |
| Edition | **2024** | Stable since 1.85. Implies resolver "3" |
| tokio | 1.53 | Enable only the features you use |
| axum | 0.8.9 | `/{param}` path syntax; native async extractors |
| tower / tower-http | 0.5.3 / **0.7.1** | tower-http 0.7 adds CSRF middleware; `TimeoutLayer::new` is deprecated for `with_status_code` |
| tracing / tracing-subscriber | 0.1.44 / 0.3.23 | `json` + `env-filter` features |
| serde / serde_json | 1.0.229 / 1.0.151 | |
| sqlx | **0.9.0** | MSRV 1.94. Features: `runtime-tokio`, `tls-rustls`, `postgres`, `macros`, `migrate` |
| thiserror / anyhow | **2.0.21** / 1.0.104 | thiserror 2 is the current major |
| clap | 4.6.7 | `derive` feature |
| proptest | 1.11.0 | |
| criterion | 0.8.2 | Use `std::hint::black_box` |
| reqwest | 0.13.5 | For outbound HTTP; keep rustls |
| cargo-nextest / cargo-deny / cargo-machete | 0.9.146 / 0.20.2 / 0.9.2 | Installed with `--locked` |
| sqlx-cli | 0.9.0 | `--no-default-features --features rustls,postgres` |
| cargo-chef | 0.1.78 | Docker images `lukemathwalker/cargo-chef:0.1.78-rust-1.98.1-slim-trixie` |
| cargo-llvm-cov | 0.9.1 | Coverage |
| samply / flamegraph | 0.13.1 / 0.6.14 | Profilers |

Why criterion over divan: both work, but divan's last release was April 2025,
while criterion is maintained and is what most of the ecosystem's benches use.

## What changed recently (1.94 to 1.98)

- **1.98:** `bool::ok_or`/`ok_or_else`, `str::substr_range`,
  `String::from_utf16le/be`. `derive(PartialOrd)` now takes a fast path when you
  also derive `Ord`, so inconsistent hand-written `Ord`/`PartialOrd` pairs
  break. `repr(transparent)` is stricter.
- **1.97:** Cargo **`build.warnings`** is stable (`CARGO_BUILD_WARNINGS=deny`),
  which denies local lint warnings without touching `RUSTFLAGS` (so it keeps
  the build cache). It covers build, clippy, test, and rustdoc (verified). Symbols
  now use v0 mangling by default (old profilers may not demangle them).
  `pin!` no longer deref-coerces.
- **1.96:** `assert_matches!` and `debug_assert_matches!` are stable. The new
  `core::range` types are stable.
- **1.95:** `if let` guards on match arms, `cfg_select!`, `Vec::push_mut`,
  `core::hint::cold_path`, and the atomic `update`/`try_update` methods.
- **1.94:** Cargo config `include`, and TOML 1.1 in manifests (which raises the
  *development* MSRV if you use it).
- **1.90** made `lld` the default linker on `x86_64-unknown-linux-gnu` (faster
  links; nothing to configure).
- **`cargo script` is still unstable** (`-Zscript`, nightly only), so
  single-file Rust scripts aren't a stable-toolchain option yet. This skill's
  tools are Python for that reason.
- Cargo's own lint table (`[lints.cargo]`, including `unused_dependencies`) is
  nightly-only, so use cargo-machete on stable.

## Toolchain pin and MSRV policy

- **Pin the dev toolchain** in `rust-toolchain.toml` (`assets/rust-toolchain.toml`):
  an exact version plus `rustfmt` and `clippy`. New lints arrive every six
  weeks, and an unpinned CI goes red on a Tuesday for no code change. Bump it on
  purpose, in its own PR.
- **Declare the MSRV** with `rust-version` in `[workspace.package]`. It is the
  oldest compiler you promise to support, not the one you develop on.
  - For **applications**, MSRV is effectively the pinned toolchain, but keep
    `rust-version` honest: it's the floor for resolver 3's MSRV-aware resolution.
  - For **libraries**, pick the lowest version you test (N-2 releases, about
    12 weeks, is a reasonable default), and add a CI job with that toolchain
    (`cargo +1.94 check`) so you notice when you use a newer API.
  - Raising MSRV is a minor-version change for a library, not a patch.

## Editions and the resolver

Edition 2024 (https://doc.rust-lang.org/edition-guide/rust-2024/) is the
default for new code. The changes that bite during migration:

- `std::env::set_var`/`remove_var` are now `unsafe` (a data race with any
  thread reading the environment).
- `extern` blocks must be `unsafe extern`, and `#[no_mangle]`/`#[export_name]`
  must be `#[unsafe(no_mangle)]`.
- `unsafe_op_in_unsafe_fn` warns: the body of an `unsafe fn` needs explicit
  `unsafe {}` blocks.
- References to `static mut` are denied. Use atomics, `Mutex`, or `OnceLock`.
- `if let` scrutinee temporaries drop before `else`, and tail-expression
  temporaries drop before locals (fixes classic `RefCell` borrow errors).
- `impl Trait` in return position captures all in-scope lifetimes; narrow it
  with `use<..>`.
- `gen` is a reserved keyword. Let chains (`if let Some(x) = a && x > 3`) work
  in 2024 (stable since 1.88).
- Migrate with `cargo fix --edition`, then set `edition = "2024"`, then run
  `cargo fmt` (style edition 2024 re-sorts some imports).

**Resolver:** edition 2024 implies `resolver = "3"`: when a newer dependency
version needs a newer compiler than your `rust-version`, Cargo falls back to a
compatible one. A **virtual workspace has no package edition**, so you must set
`resolver = "3"` in `[workspace]`; otherwise it silently falls back to resolver "1".

## Layout: library, CLI, service, workspace

**(a) Library crate:**
```
my-lib/
  Cargo.toml
  src/lib.rs          # crate docs + `pub use` of the public API; small
  src/error.rs        # one Error enum (thiserror), #[non_exhaustive]
  src/<domain>.rs     # one module per concept; private by default
  tests/*.rs          # integration tests: only the public API
  benches/*.rs        # criterion benches (harness = false)
  examples/*.rs       # runnable examples, compiled by `cargo test`
```

**(b) CLI:** `src/main.rs` parses args (clap derive) and calls a `run(cli,
out, input)` function that takes its I/O as parameters. Once logic grows, move
it into `src/lib.rs` in the same package so tests exercise it without a
process. End-to-end tests spawn `env!("CARGO_BIN_EXE_<name>")`.

**(c) Service:** a library target plus a thin `main.rs`:
```
my-api/
  src/main.rs         # process wiring only: config, telemetry, pool, migrations, serve, shutdown
  src/lib.rs          # AppState + `app(state) -> Router` (tests build the same router)
  src/config.rs       # typed config from env
  src/error.rs        # ApiError: IntoResponse
  src/<feature>.rs    # routes + request/response types + queries for one feature
  migrations/*.sql    # sqlx migrations, embedded with sqlx::migrate!()
  tests/*.rs          # HTTP tests via tower::ServiceExt::oneshot + #[sqlx::test]
```
Split a feature module into a directory (`links/mod.rs`, `links/routes.rs`,
`links/queries.rs`) only when it passes a few hundred lines.

**(d) Workspace (monorepo):** a virtual root with `crates/*`:
```
Cargo.toml            # [workspace] + [workspace.package] + [workspace.dependencies] + [workspace.lints] + profiles
Cargo.lock            # committed (there are binaries)
rust-toolchain.toml  rustfmt.toml  clippy.toml  deny.toml
.sqlx/                # committed sqlx offline query data
crates/
  acme-core/          # domain types and rules; no I/O, no async, no framework
  acme-cli/           # binary
  acme-api/           # binary + lib
```
Name crates with a shared prefix (`acme-*`) and keep the dependency graph
pointing inward: binaries depend on `acme-core`, never the other way. Split out
a new crate for a real boundary (a reusable domain, a heavy optional
dependency, compile-time parallelism), not for every module.

## The workspace manifest

See `assets/workspace-Cargo.toml` (verified). The points agents miss:

- `[workspace.package]` holds `edition`, `rust-version`, `license`, and
  `version`; members write `edition.workspace = true`.
- `[workspace.dependencies]` holds **every** version, once. Members write
  `serde.workspace = true` and may add `features = [...]`, which are additive
  to the workspace's features. Use caret requirements with the full version
  (`"1.0.229"`), the Cargo book's recommendation.
- `[workspace.lints]` does nothing until each member says `[lints] workspace = true`.
- Profiles live only in the root manifest; member profiles are ignored.
- Path dependencies in the workspace table (`acme-core = { path = "crates/acme-core" }`)
  have no version, which cargo-deny flags as a wildcard unless
  `allow-wildcard-paths = true` (fine for `publish = false` crates).

## Features

- Features must be **additive**: enabling one never removes an API or changes
  behavior for other users, because Cargo unifies features across the graph.
- Put optional integrations behind `dep:` features (`serde = ["dep:serde"]`)
  so the dependency name doesn't become an implicit feature.
- Test the combinations: `cargo test --all-features` plus a plain `cargo test`.
  For many features, use `cargo hack check --feature-powerset` (cargo-hack 0.6).
- Libraries set `default-features = false` on heavy dependencies and re-expose
  what callers need.

## Starting a new project

```bash
python3 scripts/new_workspace.py ~/code/acme --name acme      # the verified skeleton (lib + cli + api)
python3 scripts/new_workspace.py ~/code/tool --without api    # library + CLI only
# or by hand:
cargo new --lib crates/acme-core && cargo new crates/acme-cli
cargo add -p acme-api axum tokio --features tokio/macros,tokio/rt-multi-thread
```
`cargo add` writes versions into the member. In a workspace, add the version to
`[workspace.dependencies]` and write `x.workspace = true` in the member instead.
