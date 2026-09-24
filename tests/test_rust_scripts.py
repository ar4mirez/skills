"""Tests for skills/rust/scripts (run: make test). The audit needs only Python 3.11+;
the scaffold-and-build test also needs cargo and is skipped without it."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "rust"
AUDIT = SKILL / "scripts" / "audit.py"
SCAFFOLD = SKILL / "scripts" / "new_workspace.py"
FLAWED = SKILL / "evals" / "files" / "flawed_workspace"
CARGO = shutil.which("cargo")
HAS_TOMLLIB = sys.version_info >= (3, 11)


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, cwd=cwd)


def audit_json(root, *extra):
    res = run(AUDIT, root, "--json", *extra)
    return res, json.loads(res.stdout) if res.stdout.strip().startswith("{") else None


@unittest.skipUnless(HAS_TOMLLIB, "audit.py needs Python 3.11+ (tomllib)")
class AuditTests(unittest.TestCase):
    def test_flawed_workspace_findings(self):
        res, out = audit_json(FLAWED)
        self.assertEqual(res.returncode, 1, res.stderr)
        checks = {f["check"] for f in out["findings"]}
        for expected in (
            # high
            "guard-across-await", "blocking-in-async", "sql-format-injection", "axum-old-path-syntax",
            "env-mutation", "hardcoded-credentials", "unsafe-without-safety-comment", "alpine-glibc-binary",
            # medium
            "workspace-resolver-missing", "lints-not-inherited", "unwrap-in-library", "library-anyhow",
            "wildcard-version", "no-lockfile", "sqlx-offline-missing", "openssl-dependency", "docker-debug-build",
            # low
            "old-edition", "no-toolchain-pin", "no-cargo-deny", "unsafe-not-forbidden", "tokio-full",
            "version-not-inherited", "legacy-lazy", "async-trait-crate", "arc-wrapped-pool", "print-in-library",
            "release-profile-untuned", "docker-root-user",
        ):
            self.assertIn(expected, checks)
        self.assertGreaterEqual(out["summary"]["high"], 8)

    def test_test_code_is_not_flagged(self):
        _, out = audit_json(FLAWED, "--fail-on", "none")
        lib_unwraps = [f for f in out["findings"] if f["check"] == "unwrap-in-library"]
        # lib.rs has unwraps in a #[cfg(test)] module too; only the two in real code count.
        self.assertEqual(len(lib_unwraps), 2, lib_unwraps)

    def test_clean_workspace_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers = ["crates/*"]\nresolver = "3"\n\n'
                '[workspace.package]\nedition = "2024"\n\n'
                '[workspace.dependencies]\nthiserror = "2.0.21"\ntokio = { version = "1.53.1", features = ["macros", "rt-multi-thread"] }\n'
                'sqlx = { version = "0.9.0", default-features = false, features = ["postgres", "macros"] }\n\n'
                '[workspace.lints.rust]\nunsafe_code = "forbid"\n\n'
                '[profile.release]\nlto = "fat"\ncodegen-units = 1\n'
            )
            for f in ("Cargo.lock", "rust-toolchain.toml", "deny.toml"):
                (root / f).write_text("")
            (root / ".sqlx").mkdir()
            lib = root / "crates" / "core"
            (lib / "src").mkdir(parents=True)
            (lib / "Cargo.toml").write_text(
                '[package]\nname = "core"\nversion = "0.1.0"\nedition.workspace = true\n\n'
                '[dependencies]\nthiserror.workspace = true\n\n[lints]\nworkspace = true\n'
            )
            (lib / "src" / "lib.rs").write_text(
                "//! Parse, don't validate. Never call `.unwrap()` here; see \"unsafe { }\" docs.\n"
                "pub fn parse(s: &str) -> Result<u32, std::num::ParseIntError> {\n"
                "    // e.g. DATABASE_URL=postgres://user:pass@db.example.com/x (comments are ignored)\n"
                "    let local = \"postgres://postgres:postgres@localhost:5432/dev\";\n"
                "    let _ = local.len();\n    s.parse()\n}\n"
                "#[cfg(test)]\nmod tests {\n    #[test]\n    fn ok() { assert_eq!(super::parse(\"1\").unwrap(), 1); println!(\"ok\"); }\n}\n"
            )
            api = root / "crates" / "api"
            (api / "src").mkdir(parents=True)
            (api / "Cargo.toml").write_text(
                '[package]\nname = "api"\nversion = "0.1.0"\nedition.workspace = true\n\n'
                '[dependencies]\ntokio.workspace = true\nsqlx.workspace = true\n\n[lints]\nworkspace = true\n'
            )
            (api / "src" / "main.rs").write_text(
                "use std::sync::Mutex;\n"
                "static COUNT: Mutex<u64> = Mutex::new(0);\n"
                "async fn bump(pool: sqlx::PgPool) -> u64 {\n"
                "    let next = {\n        let mut n = COUNT.lock().unwrap();\n        *n += 1;\n        *n\n    };\n"
                "    let _ = sqlx::query!(\"SELECT 1 AS one\").fetch_one(&pool).await;\n"
                "    tokio::task::spawn_blocking(move || std::fs::read_to_string(\"x\")).await.ok();\n"
                "    next\n}\n"
                "fn router() { let _ = (\"/links/{code}\", \"/r/{*rest}\"); }\n"
                "#[tokio::main]\nasync fn main() { router(); }\n"
            )
            (root / "Dockerfile").write_text(
                "FROM rust:1.98.1-slim-trixie AS build\nRUN cargo build --release\n"
                "FROM gcr.io/distroless/cc-debian13:nonroot\nCOPY --from=build /app/target/release/api /api\n"
            )
            res, out = audit_json(root, "--fail-on", "low")
        self.assertEqual(out["findings"], [], out)
        self.assertEqual(res.returncode, 0)

    def test_guard_dropped_before_await_is_clean_but_held_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\nedition = "2024"\n')
            (root / "src").mkdir()
            (root / "src" / "main.rs").write_text(
                "async fn ok(m: std::sync::Mutex<u8>) {\n"
                "    let g = m.lock().unwrap();\n    let v = *g;\n    drop(g);\n    other(v).await;\n}\n"
                "async fn bad(m: std::sync::Mutex<u8>) {\n"
                "    let g = m.lock().unwrap();\n    other(*g).await;\n}\n"
                "async fn tokio_lock(m: tokio::sync::Mutex<u8>) {\n"
                "    let g = m.lock().await;\n    other(*g).await;\n}\n"
                "async fn other(_: u8) {}\nfn main() {}\n"
            )
            _, out = audit_json(root, "--fail-on", "none")
        guards = [f for f in out["findings"] if f["check"] == "guard-across-await"]
        self.assertEqual([g["location"] for g in guards], ["src/main.rs:8"], guards)

    def test_bad_invocation(self):
        self.assertEqual(run(AUDIT, "/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(run(AUDIT, "--no-such-flag").returncode, 2)
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(run(AUDIT, "--help").returncode, 0)


class ScaffoldTests(unittest.TestCase):
    def test_scaffolds_renamed_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "linkly"
            env = dict(os.environ, PATH="")  # no cargo: skip the fmt step for speed and determinism
            res = subprocess.run([sys.executable, str(SCAFFOLD), dest], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            for rel in ("Cargo.toml", "rust-toolchain.toml", "deny.toml", ".gitignore", ".dockerignore",
                        ".github/workflows/ci.yml", "config/deploy.yml", "Dockerfile",
                        "crates/linkly-core/src/lib.rs", "crates/linkly-cli/src/main.rs",
                        "crates/linkly-api/src/links.rs", "crates/linkly-api/migrations/20260901000000_create_links.sql"):
                self.assertTrue((dest / rel).is_file(), rel)
            root_toml = (dest / "Cargo.toml").read_text()
            self.assertIn('linkly-core = { path = "crates/linkly-core" }', root_toml)
            self.assertNotIn("acme", (dest / "crates/linkly-api/src/main.rs").read_text())
            self.assertIn('env!("CARGO_BIN_EXE_linkly")', (dest / "crates/linkly-cli/tests/cli.rs").read_text())
            if HAS_TOMLLIB:
                res, out = audit_json(dest, "--fail-on", "low")
                # Only the lockfile and .sqlx/ are missing until the first build and `cargo sqlx prepare`.
                self.assertEqual({f["check"] for f in out["findings"]}, {"no-lockfile", "sqlx-offline-missing"}, out)
            self.assertEqual(subprocess.run([sys.executable, str(SCAFFOLD), dest], capture_output=True, env=env).returncode, 1)

    def test_without_api_drops_service_and_database_ci(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "tool"
            env = dict(os.environ, PATH="")
            res = subprocess.run([sys.executable, str(SCAFFOLD), dest, "--without", "api"], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertFalse((dest / "crates" / "tool-api").exists())
            self.assertFalse((dest / "Dockerfile").exists())
            ci = (dest / ".github/workflows/ci.yml").read_text()
            self.assertNotIn("sqlx", ci)
            self.assertNotIn("postgres", ci)

    def test_rejects_bad_names(self):
        self.assertEqual(run(SCAFFOLD, "/tmp/x", "--name", "Bad_Name").returncode, 2)
        self.assertEqual(run(SCAFFOLD).returncode, 2)

    @unittest.skipUnless(CARGO and os.environ.get("RUST_SKILL_CARGO_TESTS"), "set RUST_SKILL_CARGO_TESTS=1 (needs cargo + crates.io)")
    def test_scaffold_without_api_passes_clippy_and_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "tool"
            self.assertEqual(run(SCAFFOLD, dest, "--without", "api").returncode, 0)
            for cmd in (["cargo", "fmt", "--all", "--check"],
                        ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"],
                        ["cargo", "test"]):
                res = subprocess.run(cmd, cwd=dest, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"{cmd}: {res.stderr[-2000:]}")


if __name__ == "__main__":
    unittest.main()
