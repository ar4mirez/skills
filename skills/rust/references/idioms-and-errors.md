# Idioms, API design, and errors

Grounded in the Rust API Guidelines (https://rust-lang.github.io/api-guidelines/),
the Rust Book's error chapter (https://doc.rust-lang.org/book/ch09-00-error-handling.html),
and the std docs. The reference workspace in `assets/` follows every rule here.

## Contents
- Naming
- Types: parse, don't validate
- Ownership in signatures
- Errors: libraries vs binaries
- Panics
- Traits and generics
- Modules and visibility
- Resource management
- Iterators and collections
- Documentation
- The "don't" list

## Naming

- `snake_case` for functions, modules, and variables; `UpperCamelCase` for
  types and traits; `SCREAMING_SNAKE_CASE` for consts and statics. Acronyms
  are words: `HttpClient`, not `HTTPClient`.
- Conversions follow the API guidelines: `as_*` is free and borrowed
  (`as_str`), `to_*` is expensive or copies (`to_string`, `to_id`), and
  `into_*` consumes self (`into_inner`).
- Constructors: `new` for the obvious one, `with_*` for variants, and
  `from_*`/`From` impls for conversions. `try_from`/`parse` for fallible ones.
- Getters don't take a `get_` prefix: `fn url(&self) -> &str`.
- Crate names use hyphens in Cargo (`acme-core`) and underscores in code
  (`acme_core`).

## Types: parse, don't validate

- Wrap validated values in **newtypes** with private fields (`struct Slug(String)`)
  and construct them only through a checking function (`Slug::parse`, `FromStr`,
  `TryFrom<String>`). Code holding a `Slug` never re-validates, and the type
  documents intent. See `assets/core-slug.rs`.
- Use `#[serde(try_from = "String", into = "String")]` so deserialization runs
  the same validation (no back door around the constructor).
- Enums over booleans and strings: `enum Visibility { Public, Private }`, not
  `is_public: bool`. Make illegal states unrepresentable.
- `#[non_exhaustive]` on public enums and structs you expect to grow.
- Derive what's cheap and meaningful: `Debug` always (the workspace warns on
  `missing_debug_implementations`), plus `Clone`, `PartialEq`, `Eq`, `Hash`
  when they're true. Keep `Ord`/`PartialOrd` consistent (1.98 enforces it via a
  fast path).
- Hand-write `Debug` for anything holding secrets (see `assets/api-config.rs`).

## Ownership in signatures

- Take the most general borrowed form: `&str` over `&String`, `&[T]` over
  `&Vec<T>`, and `impl AsRef<Path>` for paths.
- Take ownership (`String`, `Vec<T>`) when you store the value. Let the caller
  decide whether to clone, instead of cloning inside.
- Return owned values or borrows tied to `&self`. Don't return references to
  locals, and don't reach for `Rc<RefCell<_>>` to escape the borrow checker:
  restructure the data (indices or ids into a `Vec`, or pass `&mut` down).
- `Cow<'_, str>` when a function usually borrows but sometimes must allocate.
- Accept `impl Into<String>` in builder-style constructors only; elsewhere it
  hides allocations.

## Errors: libraries vs binaries

**Libraries** return one concrete error type per failure domain, built with
**thiserror 2**:

```rust
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    #[error("slug is {len} bytes; the maximum is {max}")]
    SlugTooLong { len: usize, max: usize },
    #[error("reading {path}")]
    Io { path: PathBuf, #[source] source: std::io::Error },
}
```
Callers can `match` on variants and decide. Keep lower-level errors as
`#[source]` (or `#[from]` when the conversion is unambiguous) so the chain
survives. Don't put the source's message in your `#[error]` text as well:
reporters print the chain, and you'd print it twice.

**Binaries** use **anyhow** (`anyhow::Result<()>` from `main`, `.context(..)`
and `.with_context(|| ..)` on every `?` that crosses an I/O or module
boundary). Print with `{:#}` for a one-line chain, or `{:?}` for chain plus
backtrace. Use eyre (with color-eyre) only if you want its report formatting.
Don't mix both in one binary.

**Services** sit in between: an `ApiError` enum (thiserror) that implements
`IntoResponse`, maps each variant to a status code, and logs but never returns
internal details (see `assets/api-error.rs`). `main` itself uses anyhow.

Rules:
- `?` everywhere. Convert with `From` impls or `map_err`, never by string
  matching.
- `Box<dyn Error + Send + Sync>` is acceptable only in prototypes and tests.
- Don't use `anyhow` in a library's public API: callers can't match on it.
- `Option` for absence, `Result` for failure. Don't return `Result<Option<T>, E>`
  unless both "not found" and "failed" are real, distinct outcomes (a
  `fetch_optional` is the textbook case).

## Panics

- Panic only for **bugs**: a violated invariant that the caller can't
  handle. Recoverable conditions (bad input, I/O, network, missing rows)
  return `Result`.
- `unwrap()` and `expect()` are warned in non-test code by the workspace lints.
  When an invariant truly guarantees success, use `expect("why this can't fail")`
  with an `#[expect(clippy::expect_used, reason = "...")]`, or restructure so
  the type system proves it (`unwrap_or_default`, `let Some(x) = .. else { .. }`).
- Indexing (`v[i]`) panics too. Prefer `get(i)`, iterators, or `split_first`.
- In services, a panic in a handler is caught per task (and turned into a 500
  by tower-http's `CatchPanicLayer`), so keep `panic = "unwind"` in release.

## Traits and generics

- Default to concrete types. Add a trait when there are two real
  implementations, **not** to mock a database: test against a real one (see
  `testing.md`).
- Static dispatch (`impl Trait`, generics) by default; `dyn Trait` for
  heterogeneous collections, plugin points, or to cut compile times and code
  size in a hot generic.
- Native `async fn` in traits is stable (1.75), but such traits aren't
  dyn-compatible, and a public one can't promise `Send` futures. For public
  async traits, write `fn call(&self) -> impl Future<Output = T> + Send` (the
  `async_fn_in_trait` lint says so). Keep `async-trait` only when you need
  `dyn`.
- Implement std traits instead of inventing methods: `FromStr`, `Display`,
  `From`/`TryFrom`, `AsRef`, `Default`, `IntoIterator`.
- Seal traits you don't want implemented downstream (a private supertrait).

## Modules and visibility

- Everything private by default. `pub(crate)` for crate-internal sharing; `pub`
  only for the real API, re-exported from `lib.rs` (`pub use slug::Slug;`)
  so the module layout can change without breaking users. The
  `unreachable_pub` lint flags `pub` items that aren't actually exported.
- Use `foo.rs` + `foo/` (not `foo/mod.rs`) for new modules, except where a
  crate already uses `mod.rs`. Pick one per repo.
- Imports: std, then external crates, then `crate::`. rustfmt sorts within
  groups; separate the groups with a blank line.
- No glob imports except `use super::*` in test modules and preludes.

## Resource management

- RAII: resources close in `Drop` (files, locks, connections, spans). Scope
  guards tightly with a block `{ }` or `drop(guard)`.
- `Drop` can't fail or be async. For resources that must flush or close
  gracefully (pools, writers, servers), expose an explicit `close().await` or
  `finish()` and call it on shutdown (see `db.close().await` in
  `assets/api-main.rs`).
- `BufWriter`: call `flush()` and check the result; drop ignores the error.
- Lazy statics: `std::sync::LazyLock` / `OnceLock` (1.80+), not
  `lazy_static` or `once_cell`.

## Iterators and collections

- Iterator chains over index loops; `collect::<Result<Vec<_>, _>>()` to stop at
  the first error.
- `Vec::with_capacity` when the size is known; `HashMap` default hasher is
  DoS-resistant (keep it for untrusted keys).
- `BTreeMap` when you need ordering or deterministic output (snapshots, JSON).
- `let ... else` for early returns; `matches!` and `assert_matches!` (1.96) for
  shape checks.

## Documentation

- `//!` crate docs with a runnable example; `///` on every public item
  (`#![warn(missing_docs)]` in libraries). Examples are doc-tests, so they
  stay correct.
- Document `# Errors`, `# Panics`, and `# Safety` sections where they apply
  (clippy pedantic asks for them; the reference allows skipping `# Errors` on
  obvious application code).

## The "don't" list

- Don't `.clone()` to silence the borrow checker without asking whether a
  borrow or a restructure would do.
- Don't `unwrap()` in library code or in request paths.
- Don't use `String` for everything: newtypes and enums.
- Don't return `Box<dyn Error>` from a library, or `anyhow::Error` from a
  library API.
- Don't use `Rc<RefCell<T>>` graphs as a default design, or `Arc<Mutex<T>>` for
  data one task owns (send messages instead).
- Don't add a trait (or a generic parameter) with one implementation.
- Don't write `unsafe` for performance before a benchmark proves the need.
- Don't use macros where a function or generic works.
- Don't set `std::env::set_var` at runtime (it's `unsafe` in 2024); pass config.
- Don't ignore `#[must_use]` results with `let _ =` unless the comment says why.
