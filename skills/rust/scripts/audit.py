#!/usr/bin/env python3
"""Static health check of a Rust crate or Cargo workspace. No build, no network.

Usage:
  python3 scripts/audit.py [ROOT] [--json] [--fail-on high|medium|low|none]

high    std Mutex/RwLock guard held across `.await`; blocking calls (thread::sleep, std::fs,
        reqwest::blocking, block_on) inside async code; `unsafe` without a `// SAFETY:` comment;
        `std::env::set_var`/`remove_var`; SQL built with `format!` and passed to a query;
        axum 0.7-style `/:param` routes (axum 0.8 panics at startup); hard-coded credentials
        in connection URLs; an Alpine runtime image for a glibc (non-musl) binary
medium  a virtual workspace without `resolver` (falls back to resolver 1); members that ignore
        `[workspace.lints]`; `unwrap()`/`expect()` in library code; `anyhow` in a library's
        dependencies; wildcard (`*`) versions; no Cargo.lock for a workspace with binaries;
        sqlx query macros without committed `.sqlx/` offline data; OpenSSL/native-tls deps;
        a Docker build without `--release`, or a runtime stage that ships the Rust toolchain
low     edition older than 2024; no rust-toolchain.toml; no deny.toml; `unsafe_code` not
        forbidden; tokio `full` feature; versions pinned in members instead of inherited from
        `[workspace.dependencies]`; lazy_static/once_cell (std has LazyLock/OnceLock);
        `async-trait` (native async fn in traits); `Arc<PgPool>`; println!/dbg! in library
        code; no tuned `[profile.release]`; a runtime image that runs as root

Needs Python 3.11+ (tomllib). Test code (`tests/`, `benches/`, `examples/`, and
`#[cfg(test)]` modules) is excluded from the source checks.

Exit codes: 0 = no findings at/above --fail-on (default: high), 1 = findings, 2 = bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

SEVERITIES = ("high", "medium", "low")
SKIP_DIRS = {"target", ".git", "node_modules", "vendor", ".sqlx"}
TEST_DIRS = {"tests", "benches", "examples", "fuzz"}
DEP_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


@dataclass
class Finding:
    severity: str
    check: str
    location: str
    message: str


# ---------------------------------------------------------------- source masking


def mask(src: str) -> str:
    """Blank out comments and string/char literal contents, keeping offsets and newlines,
    so regexes only ever see code."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if src.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif src.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            blank(i, j)
            i = j
        elif c == "r" and re.match(r'r#*"', src[i:i + 10]) and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            hashes = len(re.match(r"r(#*)", src[i:]).group(1))
            start = i + 2 + hashes
            end = src.find('"' + "#" * hashes, start)
            end = n if end == -1 else end
            blank(start, end)
            i = end + 1 + hashes
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
        elif c == "'":
            # char literal ('a', '\n', '\u{1F600}') vs lifetime ('a)
            m = re.match(r"'(\\.[^']*|[^'\\])'", src[i:i + 12])
            if m:
                blank(i + 1, i + m.end() - 1)
                i += m.end()
            else:
                i += 1
        else:
            i += 1
    return "".join(out)


def block_end(code: str, open_idx: int) -> int:
    """Index just past the brace block starting at code[open_idx] == '{'."""
    depth = 0
    for k in range(open_idx, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(code)


def strip_cfg_test(code: str) -> str:
    """Blank `#[cfg(test)]` items (usually `mod tests { ... }`)."""
    out = code
    for m in re.finditer(r"#\[cfg\(test\)\]", code):
        brace = code.find("{", m.end())
        semi = code.find(";", m.end())
        if brace == -1 or (semi != -1 and semi < brace):
            continue
        end = block_end(code, brace)
        out = out[: m.start()] + re.sub(r"[^\n]", " ", out[m.start():end]) + out[end:]
    return out


def async_bodies(code: str) -> list[tuple[int, int]]:
    spans = []
    for m in re.finditer(r"\basync\s+(?:move\s+)?(?:fn\b[^{;]*)?\{", code):
        brace = m.end() - 1
        spans.append((brace, block_end(code, brace)))
    return spans


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


# ---------------------------------------------------------------- the auditor


class Auditor:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[Finding] = []

    def add(self, severity: str, check: str, path: Path | str, message: str, line: int | None = None) -> None:
        loc = path if isinstance(path, str) else path.relative_to(self.root).as_posix() or "."
        if line:
            loc = f"{loc}:{line}"
        self.findings.append(Finding(severity, check, loc, message))

    # ---- manifests

    def manifests(self) -> list[Path]:
        found = []
        for p in sorted(self.root.rglob("Cargo.toml")):
            rel = p.relative_to(self.root).parts
            if any(part in SKIP_DIRS for part in rel[:-1]):
                continue
            found.append(p)
        return found

    @staticmethod
    def load(path: Path) -> dict:
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return {}

    def run(self) -> None:
        root_manifest = self.root / "Cargo.toml"
        root = self.load(root_manifest)
        ws = root.get("workspace")
        manifests = self.manifests()
        crates: list[tuple[Path, dict]] = [(m.parent, self.load(m)) for m in manifests]
        crates = [(d, t) for d, t in crates if "package" in t]

        ws_deps = set((ws or {}).get("dependencies", {}))
        ws_lints = bool((ws or {}).get("lints"))
        has_bins = False
        unsafe_forbidden = "unsafe_code" in str((ws or {}).get("lints", {}).get("rust", {}))

        if ws is not None and "package" not in root and "resolver" not in ws:
            self.add("medium", "workspace-resolver-missing", root_manifest,
                     'Virtual workspace without `resolver`: Cargo falls back to resolver "1". Set resolver = "3" '
                     "(the edition-2024 default: MSRV-aware resolution).")

        for crate_dir, man in crates:
            mpath = crate_dir / "Cargo.toml"
            pkg = man.get("package", {})
            edition = pkg.get("edition")
            if isinstance(edition, dict) and edition.get("workspace"):
                edition = (ws or {}).get("package", {}).get("edition")
            if edition is None:
                edition = "2015"
            if str(edition) < "2024":
                self.add("low", "old-edition", mpath,
                         f"edition {edition}: move to 2024 (`cargo fix --edition`, then set edition = \"2024\").")

            lints = man.get("lints")
            if ws_lints and crate_dir != self.root and not (isinstance(lints, dict) and lints.get("workspace")):
                self.add("medium", "lints-not-inherited", mpath,
                         "[workspace.lints] exists but this member lacks `[lints] workspace = true`, so none of it applies.")
            if "unsafe_code" in str(lints or {}):
                unsafe_forbidden = unsafe_forbidden or "forbid" in str(lints)

            is_bin = (crate_dir / "src" / "main.rs").exists() or "bin" in man or (crate_dir / "src" / "bin").is_dir()
            is_lib = (crate_dir / "src" / "lib.rs").exists() or "lib" in man
            has_bins |= is_bin

            for table in DEP_TABLES:
                for name, spec in man.get(table, {}).items():
                    self.check_dep(mpath, table, name, spec, ws_deps, is_lib and not is_bin)
            for target in man.get("target", {}).values():
                for table in DEP_TABLES:
                    for name, spec in target.get(table, {}).items():
                        self.check_dep(mpath, table, name, spec, ws_deps, is_lib and not is_bin)

            self.check_sources(crate_dir, is_lib)

        for name, spec in (ws or {}).get("dependencies", {}).items():
            self.check_dep(root_manifest, "workspace.dependencies", name, spec, set(), False)

        if crates:
            if has_bins and not (self.root / "Cargo.lock").exists():
                self.add("medium", "no-lockfile", ".",
                         "No Cargo.lock: binaries must commit it so every build resolves the same versions (use --locked in CI).")
            if not any((self.root / f).exists() for f in ("rust-toolchain.toml", "rust-toolchain")):
                self.add("low", "no-toolchain-pin", ".",
                         "No rust-toolchain.toml: pin the compiler (channel + rustfmt/clippy) so local and CI builds agree.")
            if not any((self.root / f).exists() for f in ("deny.toml", ".cargo/deny.toml")):
                self.add("low", "no-cargo-deny", ".",
                         "No deny.toml: gate advisories, licenses, bans, and sources with cargo-deny in CI.")
            if not unsafe_forbidden and not self.crate_attr_forbids_unsafe(crates):
                self.add("low", "unsafe-not-forbidden", root_manifest if root else ".",
                         'Set `unsafe_code = "forbid"` in [workspace.lints.rust] (override only in the crate that needs it).')
            release = root.get("profile", {}).get("release", {})
            if has_bins and not ({"lto", "codegen-units"} & set(release)):
                self.add("low", "release-profile-untuned", root_manifest if root else ".",
                         '[profile.release] has no lto/codegen-units: set lto = "fat" (or "thin"), codegen-units = 1 for shipped binaries.')

        self.check_dockerfiles()

    def crate_attr_forbids_unsafe(self, crates: list[tuple[Path, dict]]) -> bool:
        roots = [d / "src" / f for d, _ in crates for f in ("lib.rs", "main.rs")]
        present = [p for p in roots if p.exists()]
        return bool(present) and all("#![forbid(unsafe_code)]" in p.read_text(encoding="utf-8", errors="replace") for p in present)

    def check_dep(self, mpath: Path, table: str, name: str, spec, ws_deps: set[str], pure_lib: bool) -> None:
        version = spec if isinstance(spec, str) else (spec.get("version") if isinstance(spec, dict) else None)
        inherited = isinstance(spec, dict) and spec.get("workspace") is True
        pkg = spec.get("package", name) if isinstance(spec, dict) else name
        if version is not None and version.strip() == "*":
            self.add("medium", "wildcard-version", mpath, f"{name} = \"*\": pin a real minimum version (\"1.2.3\"), or inherit it from the workspace.")
        if ws_deps and name in ws_deps and not inherited and table != "workspace.dependencies":
            self.add("low", "version-not-inherited", mpath,
                     f"{name} is in [workspace.dependencies] but this member pins its own version; use `{name}.workspace = true`.")
        if pkg == "anyhow" and pure_lib and table == "dependencies":
            self.add("medium", "library-anyhow", mpath,
                     "A library depends on anyhow: expose a typed error enum (thiserror) so callers can match on it; anyhow belongs in binaries.")
        if pkg in ("openssl", "openssl-sys", "native-tls") or (pkg in ("reqwest", "sqlx") and isinstance(spec, dict) and any("native-tls" in f for f in spec.get("features", []))):
            self.add("medium", "openssl-dependency", mpath,
                     f"{name} pulls in OpenSSL/native-tls: prefer rustls (no system libssl, static- and distroless-friendly).")
        if pkg == "tokio" and isinstance(spec, dict) and "full" in spec.get("features", []):
            self.add("low", "tokio-full", mpath, 'tokio features = ["full"]: list what you use (rt-multi-thread, macros, net, signal, ...).')
        if pkg in ("lazy_static", "once_cell"):
            self.add("low", "legacy-lazy", mpath, f"{name}: std has LazyLock/OnceLock (1.80+); drop the dependency.")
        if pkg == "async-trait":
            self.add("low", "async-trait-crate", mpath,
                     "async-trait: native `async fn` in traits is stable (1.75+). Keep the crate only where you need `dyn Trait`.")

    # ---- sources

    def rust_files(self, crate_dir: Path) -> list[Path]:
        out = []
        for p in sorted(crate_dir.rglob("*.rs")):
            rel = p.relative_to(crate_dir).parts
            if any(part in SKIP_DIRS or part in TEST_DIRS for part in rel[:-1]):
                continue
            if rel == ("build.rs",):
                continue
            # A nested crate is audited on its own.
            if any((crate_dir.joinpath(*rel[:k]) / "Cargo.toml").exists() for k in range(1, len(rel))):
                continue
            out.append(p)
        return out

    def check_sources(self, crate_dir: Path, is_lib: bool) -> None:
        uses_query_macros = False
        for path in self.rust_files(crate_dir):
            raw = path.read_text(encoding="utf-8", errors="replace")
            code = strip_cfg_test(mask(raw))
            rel_parts = path.relative_to(crate_dir).parts
            lib_code = is_lib and rel_parts[:1] == ("src",) and rel_parts[1:2] != ("bin",) and path.name != "main.rs"

            if re.search(r"\bsqlx::query(_as|_scalar)?!\s*\(", code):
                uses_query_macros = True

            if lib_code:
                for m in re.finditer(r"\.(unwrap|expect)\(", code):
                    self.add("medium", "unwrap-in-library", path,
                             f"`.{m.group(1)}()` in library code: return a Result (with `?`) instead of panicking on a recoverable error.",
                             line_of(code, m.start()))
                for m in re.finditer(r"\b(println|eprintln|print|dbg)!\s*\(", code):
                    self.add("low", "print-in-library", path,
                             f"`{m.group(1)}!` in library code: return data or emit `tracing` events; the caller owns stdout.",
                             line_of(code, m.start()))

            for m in re.finditer(r"\b(?:std::)?env::(set_var|remove_var)\s*\(", code):
                self.add("high", "env-mutation", path,
                         f"env::{m.group(1)} is unsafe in edition 2024 (UB while other threads read the environment). "
                         "Pass configuration explicitly (e.g. a lookup closure) instead.", line_of(code, m.start()))

            for m in re.finditer(r"\bunsafe\s*(\{|fn\b|impl\b|extern\b)", code):
                before = raw[: m.start()].splitlines()[-4:]
                if not any("SAFETY:" in ln or "# Safety" in ln for ln in before):
                    self.add("high", "unsafe-without-safety-comment", path,
                             "`unsafe` without a `// SAFETY:` comment stating which invariant makes it sound.",
                             line_of(code, m.start()))

            for m in re.finditer(r"\.route\(\s*\"", code):
                lit = re.match(r'"([^"]*)"', raw[m.end() - 1:])
                if lit and re.search(r"/[:*][A-Za-z_]", lit.group(1)):
                    self.add("high", "axum-old-path-syntax", path,
                             f"Route {lit.group(1)!r} uses axum 0.7 syntax; axum 0.8 panics at startup. Use `/{{param}}` and `/{{*rest}}`.",
                             line_of(code, m.start()))

            sql_fmt = (r"\b(?:query|query_as|query_scalar|query_with|execute|fetch_one|fetch_all|fetch_optional)"
                       r"(?:::<[^>]*>)?\s*\(\s*&?\s*(?:(?:sqlx::)?AssertSqlSafe\s*\(\s*)?format!\s*\(")
            for m in re.finditer(sql_fmt, code):
                self.add("high", "sql-format-injection", path,
                         "SQL built with format!: bind parameters ($1, $2) instead. Interpolated input is SQL injection "
                         "(sqlx 0.9 makes you write AssertSqlSafe for this; that is an assertion, not a fix).",
                         line_of(code, m.start()))

            for m in re.finditer(r"\b(postgres(?:ql)?|mysql|redis|amqp|mongodb)://[^\s\"'@/:]+:[^\s\"'@/]+@", raw):
                line = raw[: m.start()].count("\n") + 1
                if "localhost" in raw[m.start():m.start() + 120] or "127.0.0.1" in raw[m.start():m.start() + 120]:
                    continue
                if code.splitlines()[line - 1].strip() == "":
                    continue  # in a comment, or in a stripped test module
                self.add("high", "hardcoded-credentials", path,
                         "Credentials in a connection URL literal: read secrets from the environment (and redact them in Debug).", line)

            for m in re.finditer(r"\bArc\s*<\s*(?:sqlx::)?(PgPool|Pool<|MySqlPool|SqlitePool)", code):
                self.add("low", "arc-wrapped-pool", path,
                         "The sqlx pool is already reference-counted; clone it instead of wrapping it in Arc.",
                         line_of(code, m.start()))

            for start, end in async_bodies(code):
                self.check_async_body(path, code, start, end)

        if uses_query_macros:
            ws_root = self.root
            if not any((d / ".sqlx").is_dir() for d in (crate_dir, ws_root)):
                self.add("medium", "sqlx-offline-missing", crate_dir / "Cargo.toml",
                         "sqlx query macros but no .sqlx/ directory: run `cargo sqlx prepare --workspace` and commit it, "
                         "so CI and Docker builds compile with SQLX_OFFLINE=true.")

    BLOCKING = [
        (r"\b(?:std::)?thread::sleep\s*\(", "thread::sleep blocks the executor thread; use tokio::time::sleep(..).await"),
        (r"\bstd::fs::\w+", "std::fs blocks the executor; use tokio::fs or spawn_blocking"),
        (r"\breqwest::blocking\b", "reqwest::blocking inside async code; use the async client"),
        (r"\.block_on\s*\(|\bblock_on\s*\(", "block_on inside async code deadlocks or panics; .await the future"),
        (r"\bstd::io::stdin\(\)\s*\.\s*read_line", "blocking stdin read in async code; use spawn_blocking"),
    ]

    def check_async_body(self, path: Path, code: str, start: int, end: int) -> None:
        body = code[start:end]
        # Skip nested async blocks' duplicate reports: only report matches whose innermost
        # async span is this one.
        for pattern, why in self.BLOCKING:
            for m in re.finditer(pattern, body):
                idx = start + m.start()
                inner = [s for s in async_bodies(code) if s[0] <= idx < s[1]]
                if min(inner, key=lambda s: s[1] - s[0]) != (start, end):
                    continue
                if "spawn_blocking" in code[max(start, idx - 200):idx]:
                    continue
                self.add("high", "blocking-in-async", path, why + ".", line_of(code, idx))

        for m in re.finditer(r"\blet\s+(?:mut\s+)?(\w+)\s*(?::[^=]+)?=\s*[^;]*?\.(lock|read|write)\(\)\s*(\.unwrap\(\)|\.expect\([^;]*?\)|\?)?\s*;", body):
            name, kind = m.group(1), m.group(2)
            if kind in ("read", "write") and not m.group(3):
                continue  # likely an async RwLock or an io read/write
            if re.search(r"\.(lock|read|write)\(\)\s*\.await", m.group(0)):
                continue
            # Scan to the end of the enclosing block, stopping at drop(name).
            depth, k = 0, m.end()
            while k < len(body):
                ch = body[k]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        break
                if body.startswith(f"drop({name})", k):
                    break
                if body.startswith(".await", k):
                    self.add("high", "guard-across-await", path,
                             f"`{name}` (a std {'Mutex' if kind == 'lock' else 'RwLock'} guard) is alive across `.await`: the future "
                             "becomes !Send and can deadlock. Scope the guard in a block or drop() it before awaiting.",
                             line_of(code, start + m.start()))
                    break
                k += 1

    # ---- containers

    def check_dockerfiles(self) -> None:
        for path in sorted(self.root.rglob("Dockerfile*")):
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts[:-1]) or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
            body = "\n".join(lines)
            froms = [ln.split()[1] for ln in lines if ln.strip().upper().startswith("FROM ") and len(ln.split()) > 1]
            if not froms:
                continue
            final = froms[-1].lower()
            if "cargo build" in body and "--release" not in body:
                self.add("medium", "docker-debug-build", path, "`cargo build` without --release: debug binaries are 10-100x slower.")
            if final.startswith(("rust:", "rust@", "lukemathwalker/cargo-chef")) or final == "rust":
                self.add("medium", "docker-toolchain-in-runtime", path,
                         f"Runtime stage is {froms[-1]}: ship only the binary on distroless (cc for glibc, static for musl).")
            if "alpine" in final and "musl" not in body:
                self.add("high", "alpine-glibc-binary", path,
                         "Alpine runtime but no musl target: a glibc binary won't start there. Use distroless/cc, or build --target *-linux-musl.")
            if "USER " not in body and "nonroot" not in final:
                self.add("low", "docker-root-user", path, "Runtime runs as root: use a :nonroot distroless tag or a USER line.")


def report(findings: list[Finding], root: Path) -> str:
    if not findings:
        return f"{root}: no findings."
    order = {s: i for i, s in enumerate(SEVERITIES)}
    lines = [f"{root}: {len(findings)} finding(s)"]
    for f in sorted(findings, key=lambda f: (order[f.severity], f.location)):
        lines.append(f"  [{f.severity.upper():6}] {f.check:30} {f.location}\n           {f.message}")
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    lines.append("summary: " + ", ".join(f"{counts[s]} {s}" for s in SEVERITIES))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="audit.py",
        description="Static health check of a Rust crate or Cargo workspace (manifests, idioms, async, unsafe, deploy).",
        epilog="Exit codes: 0 no findings at/above --fail-on, 1 findings, 2 bad input.",
    )
    parser.add_argument("root", nargs="?", default=".", help="crate or workspace root (default: .)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fail-on", default="high", help="lowest severity that fails: high|medium|low|none (default: high)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.fail_on not in (*SEVERITIES, "none"):
        print(f"error: --fail-on must be high, medium, low, or none (got {args.fail_on!r})", file=sys.stderr)
        return 2
    if tomllib is None:
        print("error: Python 3.11+ is required (tomllib).", file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    if not (root / "Cargo.toml").is_file():
        print(f"error: {root} has no Cargo.toml; pass the crate or workspace root.", file=sys.stderr)
        return 2

    auditor = Auditor(root)
    auditor.run()
    findings = auditor.findings
    if args.json:
        counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
        print(json.dumps({"root": str(root), "summary": counts, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(report(findings, root))
    if args.fail_on == "none":
        return 0
    threshold = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(f.severity) <= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
