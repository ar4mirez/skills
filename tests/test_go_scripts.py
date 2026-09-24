"""Tests for skills/go/scripts (run: make test). Skipped when the Go toolchain isn't installed.

The scripts are built once into a temp dir because `go run` collapses every
non-zero exit status to 1, and the audit's contract is 0/1/2.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "go"
AUDIT_SRC = SKILL / "scripts" / "audit.go"
SCAFFOLD_SRC = SKILL / "scripts" / "scaffold.go"
FLAWED = SKILL / "evals" / "files" / "flawed_service"
GO = shutil.which("go")

CLEAN_MODULE = {
    "go.mod": "module example.com/clean\n\ngo 1.27.0\n",
    "main.go": '''package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strings"
	"time"
)

var slug = mustCompile(`^[a-z]+$`)

func mustCompile(s string) *regexp.Regexp { return regexp.MustCompile(s) }

var ErrEmpty = errors.New("empty")

func read(r io.Reader) (string, error) {
	b := make([]byte, 8)
	n, err := r.Read(b)
	if err == io.EOF {
		return "", ErrEmpty
	}
	if err != nil {
		return "", fmt.Errorf("read: %w", err)
	}
	return string(b[:n]), nil
}

func handler(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	body, err := io.ReadAll(r.Body)
	if errors.Is(err, ErrEmpty) {
		http.Error(w, "empty", http.StatusBadRequest)
		return
	}
	_ = r.Context()
	_, _ = w.Write([]byte(strings.ToUpper(string(body))))
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	mux := http.NewServeMux()
	mux.HandleFunc("POST /echo", handler)
	srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		_ = srv.Shutdown(context.WithoutCancel(ctx))
	}()
	if err := srv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	_ = slug
}
''',
    "store.go": '''package main

import (
	"context"
	"database/sql"
	"fmt"
)

type store struct{ db *sql.DB }

const label = "password"

func (s *store) name(ctx context.Context, id int64) (string, error) {
	var n string
	err := s.db.QueryRowContext(ctx, "SELECT name FROM users WHERE id = $1", id).Scan(&n)
	if err != nil {
		return "", fmt.Errorf("user %d: %w", id, err)
	}
	return n, nil
}
''',
}

EXPECTED_FLAWED_CHECKS = {
    "sql-string-building", "hardcoded-secret", "server-no-timeouts", "insecure-skip-verify",
    "cgo-static-image", "no-graceful-shutdown", "error-not-wrapped", "error-equality",
    "error-type-assertion", "error-leak", "context-background-in-handler", "context-in-struct",
    "unbounded-body", "default-http-client", "client-no-timeout", "default-serve-mux",
    "pprof-default-mux", "defer-in-loop", "panic-in-library", "exit-outside-main",
    "local-replace", "missing-go-sum", "old-go-directive", "discouraged-module", "tools-go",
    "pkg-dir", "util-package", "ioutil", "pkg-errors", "getter-prefix", "context-not-first",
    "sleep-in-test", "ci-no-race", "no-trimpath",
}


def write_tree(root: Path, files: dict) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@unittest.skipUnless(GO, "go toolchain not installed")
class GoScriptsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bindir = tempfile.mkdtemp(prefix="go-skill-bin-")
        cls.audit = str(Path(cls.bindir) / "audit")
        cls.scaffold = str(Path(cls.bindir) / "scaffold")
        for src, out in ((AUDIT_SRC, cls.audit), (SCAFFOLD_SRC, cls.scaffold)):
            res = subprocess.run([GO, "build", "-o", out, str(src)], capture_output=True, text=True, cwd=SKILL)
            if res.returncode != 0:
                raise RuntimeError(f"building {src.name} failed:\n{res.stderr}")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.bindir, ignore_errors=True)

    def run_audit(self, *args):
        return subprocess.run([self.audit, *map(str, args)], capture_output=True, text=True)

    def run_scaffold(self, *args):
        # --assets keeps the test independent of where the binary was built.
        return subprocess.run([self.scaffold, "--assets", str(SKILL / "assets"), *map(str, args)],
                              capture_output=True, text=True)


class AuditTests(GoScriptsBase):
    def test_flawed_fixture_findings(self):
        res = self.run_audit(FLAWED, "--json")
        self.assertEqual(res.returncode, 1, res.stderr)
        findings = json.loads(res.stdout)["findings"]
        checks = {f["check"] for f in findings}
        missing = EXPECTED_FLAWED_CHECKS - checks
        self.assertFalse(missing, f"audit missed planted issues: {sorted(missing)}")
        self.assertGreaterEqual(sum(f["severity"] == "high" for f in findings), 5)
        for f in findings:
            self.assertIn(f["severity"], ("high", "medium", "low"))
            self.assertTrue(f["location"] and f["message"])

    def test_text_report_and_severity_order(self):
        res = self.run_audit(FLAWED)
        self.assertEqual(res.returncode, 1)
        out = res.stdout
        self.assertLess(out.index("HIGH"), out.index("MEDIUM"))
        self.assertLess(out.index("MEDIUM"), out.index("LOW"))
        self.assertIn("Summary:", out)

    def test_clean_module_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(Path(tmp), CLEAN_MODULE)
            res = self.run_audit(tmp, "--json", "--fail-on", "low")
        out = json.loads(res.stdout)
        self.assertEqual(out["findings"], [], out["findings"])
        self.assertEqual(res.returncode, 0)

    def test_scaffolded_service_and_assets_are_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "svc"
            self.assertEqual(self.run_scaffold("--module", "example.com/svc", target).returncode, 0)
            res = self.run_audit(target, "--json", "--fail-on", "low")
            self.assertEqual(json.loads(res.stdout)["findings"], [], res.stdout)
            self.assertEqual(res.returncode, 0)
        res = self.run_audit(SKILL / "assets", "--json", "--fail-on", "low")
        self.assertEqual(json.loads(res.stdout)["findings"], [], res.stdout)

    def test_fail_on_thresholds(self):
        self.assertEqual(self.run_audit(FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(self.run_audit(FLAWED, "--fail-on=high").returncode, 1)

    def test_bad_invocation(self):
        self.assertEqual(self.run_audit("/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(self.run_audit(FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(self.run_audit(FLAWED, "--bogus-flag").returncode, 2)
        self.assertEqual(self.run_audit(FLAWED, "--fail-on").returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_audit(tmp).returncode, 2)  # not a Go project
        res = self.run_audit("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Usage:", res.stdout)


class ScaffoldTests(GoScriptsBase):
    def test_service_layout_and_module_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "svc"
            res = self.run_scaffold("--module", "github.com/me/shortener", target)
            self.assertEqual(res.returncode, 0, res.stderr)
            for rel in ("go.mod", "go.sum", "cmd/links/main.go", "internal/server/server.go",
                        "internal/link/link.go", "internal/link/linkdb/models.go", "db/db.go",
                        "db/migrations/00001_create_links.sql", ".golangci.yml", "Dockerfile",
                        "config/deploy.yml", ".github/workflows/ci.yml", ".kamal/hooks/pre-deploy"):
                self.assertTrue((target / rel).is_file(), rel)
            self.assertTrue((target / "go.mod").read_text().startswith("module github.com/me/shortener\n"))
            self.assertIn('"github.com/me/shortener/internal/link"', (target / "cmd/links/main.go").read_text())
            self.assertNotIn("github.com/acme/links", (target / ".golangci.yml").read_text())
            self.assertTrue(os.access(target / ".kamal/hooks/pre-deploy", os.X_OK))
            # refuses to overwrite
            self.assertEqual(self.run_scaffold("--module", "github.com/me/shortener", target).returncode, 1)

    def test_library_builds_and_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "lib"
            res = self.run_scaffold("--kind", "library", "--module", "example.com/retry", target)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(sorted(p.name for p in target.iterdir()),
                             [".golangci.yml", "example_test.go", "go.mod", "retry.go", "retry_test.go"])
            env = {**os.environ, "GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"}
            vet = subprocess.run([GO, "vet", "./..."], cwd=target, capture_output=True, text=True, env=env)
            if vet.returncode != 0 and "requires go >=" in vet.stderr:
                self.skipTest("local Go toolchain older than 1.27")
            self.assertEqual(vet.returncode, 0, vet.stderr)
            test = subprocess.run([GO, "test", "-count=1", "./..."], cwd=target, capture_output=True, text=True, env=env)
            self.assertEqual(test.returncode, 0, test.stdout + test.stderr)

    def test_service_compiles_from_module_cache(self):
        """Builds and tests the scaffolded service offline; skips when deps aren't cached."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "svc"
            self.assertEqual(self.run_scaffold("--module", "example.com/svc", target).returncode, 0)
            env = {**os.environ, "GOPROXY": "off", "GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"}
            dl = subprocess.run([GO, "mod", "download"], cwd=target, capture_output=True, text=True, env=env)
            if dl.returncode != 0:
                self.skipTest("service dependencies not in the local module cache (or Go < 1.27)")
            vet = subprocess.run([GO, "vet", "./..."], cwd=target, capture_output=True, text=True, env=env)
            self.assertEqual(vet.returncode, 0, vet.stderr)
            test = subprocess.run([GO, "test", "-count=1", "./..."], cwd=target, capture_output=True, text=True, env=env)
            self.assertEqual(test.returncode, 0, test.stdout + test.stderr)

    def test_bad_invocation(self):
        self.assertEqual(self.run_scaffold("--module", "Not A Path", "/tmp/x").returncode, 2)
        self.assertEqual(self.run_scaffold("--module", "example.com/x", "--kind", "cli", "/tmp/x").returncode, 2)
        self.assertEqual(self.run_scaffold("--module", "example.com/x").returncode, 2)
        res = subprocess.run([self.scaffold, "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
