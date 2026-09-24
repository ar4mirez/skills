"""Tests for skills/python/scripts (run: make test). The audit needs only Python 3.11+;
auditing the scaffolded project needs 3.14 (it uses 3.14 syntax); the full uv gate runs only
with PYTHON_SKILL_UV_TESTS=1 and uv on PATH."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "python"
AUDIT = SKILL / "scripts" / "audit.py"
SCAFFOLD = SKILL / "scripts" / "new_project.py"
FLAWED = SKILL / "evals" / "files" / "flawed_service"
HAS_TOMLLIB = sys.version_info >= (3, 11)
UV = shutil.which("uv")


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, cwd=cwd)


def audit_json(root, *extra):
    res = run(AUDIT, root, "--json", *extra)
    return res, json.loads(res.stdout) if res.stdout.strip().startswith("{") else None


CLEAN_SOURCE = '''"""Service helpers. Example: postgresql://user:secret@db.prod.internal.io/app (docs only)."""

import asyncio
import logging
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml
from sqlalchemy import text

log = logging.getLogger(__name__)
API_KEY = os.environ["API_KEY"]
API_KEY_ENV = "API_KEY"
LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/dev"


def read_config(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch(url: str) -> str:
    return requests.get(url, timeout=10).text


def run_tool(args: list[str]) -> str:
    return subprocess.run(["tool", *args], check=True, capture_output=True, text=True, timeout=30).stdout


def new_token() -> str:
    token = secrets.token_urlsafe(32)
    return token


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def find(session: object, code: str) -> object:
    return session.execute(text("SELECT url FROM links WHERE code = :code"), {"code": code})


def search(cur: object, term: str) -> object:
    return cur.execute("SELECT code FROM links WHERE url LIKE %s", (f"%{term}%",))


def tags(extra: list[str] | None = None) -> list[str]:
    try:
        return [*(extra or [])]
    except ValueError:
        log.exception("bad tags %s", extra)
        raise


async def fan_out(urls: list[str]) -> list[str]:
    def blocking(url: str) -> str:
        time.sleep(0.1)  # runs in a thread, not on the loop
        return url

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(asyncio.to_thread(blocking, u)) for u in urls]
        tg.create_task(asyncio.sleep(0))
    await asyncio.sleep(0.1)
    return [t.result() for t in tasks]


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")

    def _private(self, x):
        return x
'''


@unittest.skipUnless(HAS_TOMLLIB, "audit.py needs Python 3.11+ (tomllib)")
class AuditTests(unittest.TestCase):
    def test_flawed_service_findings(self):
        res, out = audit_json(FLAWED)
        self.assertEqual(res.returncode, 1, res.stderr)
        checks = {f["check"] for f in out["findings"]}
        for expected in (
            # high
            "eval-exec", "unsafe-deserialization", "shell-injection", "sql-string-building",
            "tls-verify-disabled", "hardcoded-secret", "blocking-in-async",
            # medium
            "bare-except", "swallowed-exception", "mutable-default", "http-no-timeout",
            "task-not-referenced", "get-event-loop", "naive-datetime", "insecure-random",
            "insecure-tempfile", "legacy-setup-py", "requirements-only", "no-lockfile",
            "docker-shell-form", "docker-reload", "docker-eol-python",
            # low
            "missing-type-hints", "legacy-typing", "logging-fstring", "docker-full-image",
            "docker-root-user", "docker-pip-install",
        ):
            self.assertIn(expected, checks)
        self.assertGreaterEqual(out["summary"]["high"], 10)
        sql = [f["location"] for f in out["findings"] if f["check"] == "sql-string-building"]
        self.assertEqual(sql, ["app/db.py:14", "app/db.py:21"])  # f-string and + concatenation

    def test_test_files_are_skipped(self):
        _, out = audit_json(FLAWED, "--fail-on", "none")
        self.assertFalse([f for f in out["findings"] if f["location"].startswith("tests/")])

    def test_clean_project_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "svc"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
                'dependencies = ["requests>=2.32"]\n\n'
                '[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n\n'
                '[tool.pytest]\nstrict = true\n'
            )
            (root / "uv.lock").write_text("version = 1\n")
            pkg = root / "src" / "svc"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text('"""svc."""\n')
            (pkg / "helpers.py").write_text(CLEAN_SOURCE)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_helpers.py").write_text('PASSWORD = "hunter2"\n\ndef test_x():\n    assert eval("1") == 1\n')
            (root / "Dockerfile").write_text(
                "FROM python:3.14-slim-trixie AS build\nRUN uv sync --locked --no-dev\n"
                "FROM python:3.14-slim-trixie\nRUN useradd --system app\nUSER app\n"
                'CMD ["svc", "serve"]\n'
            )
            res, out = audit_json(root, "--fail-on", "low")
        self.assertEqual(out["findings"], [], out)
        self.assertEqual(res.returncode, 0)

    def test_blocking_is_flagged_only_directly_inside_async(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "import time\n\n"
                "def sync_ok() -> None:\n    time.sleep(1)\n\n"
                "async def bad() -> None:\n    time.sleep(1)\n\n"
                "async def nested_ok() -> None:\n"
                "    def inner() -> None:\n        time.sleep(1)\n"
                "    await run(inner)\n\n"
                "async def run(f: object) -> None: ...\n"
            )
            _, out = audit_json(root, "--fail-on", "none")
        blocking = [f["location"] for f in out["findings"] if f["check"] == "blocking-in-async"]
        self.assertEqual(blocking, ["app.py:7"], out)

    def test_bad_invocation(self):
        self.assertEqual(run(AUDIT, "/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(run(AUDIT, "--no-such-flag").returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(AUDIT, tmp).returncode, 2)  # no Python project there
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(run(AUDIT, "--help").returncode, 0)

    @unittest.skipUnless(sys.version_info >= (3, 14), "the scaffold uses 3.14 syntax (PEP 695/758)")
    def test_scaffolded_project_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "shorty"
            self.assertEqual(run(SCAFFOLD, dest).returncode, 0)
            (dest / "uv.lock").write_text("version = 1\n")  # `uv lock` output; not run here
            res, out = audit_json(dest, "--fail-on", "low")
        self.assertEqual(out["findings"], [], out)
        self.assertEqual(res.returncode, 0)


class ScaffoldTests(unittest.TestCase):
    def test_scaffolds_renamed_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "linkly"
            res = run(SCAFFOLD, dest)
            self.assertEqual(res.returncode, 0, res.stderr)
            for rel in ("pyproject.toml", ".python-version", ".gitignore", ".dockerignore", "Dockerfile",
                        "config/deploy.yml", ".kamal/hooks/pre-deploy", ".github/workflows/ci.yml",
                        ".github/workflows/release.yml",
                        "packages/linkly-core/src/linkly_core/__init__.py",
                        "packages/linkly-core/src/linkly_core/py.typed",
                        "packages/linkly-cli/src/linkly_cli/__main__.py",
                        "packages/linkly-api/src/linkly_api/migrations/env.py",
                        "packages/linkly-api/src/linkly_api/migrations/versions/0001_create_links.py",
                        "packages/linkly-api/tests/conftest.py", "packages/linkly-api/README.md"):
                self.assertTrue((dest / rel).is_file(), rel)
            leftovers = [p for p in dest.rglob("*") if p.is_file() and "acme" in p.read_text().lower()]
            self.assertEqual(leftovers, [])
            self.assertIn('linkly = "linkly_cli.main:app"', (dest / "packages/linkly-cli/pyproject.toml").read_text())
            self.assertTrue(os.access(dest / ".kamal/hooks/pre-deploy", os.X_OK))
            self.assertEqual(run(SCAFFOLD, dest).returncode, 1)

    def test_without_api_drops_service_tooling(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "tooly"
            res = run(SCAFFOLD, dest, "--without", "api")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertFalse((dest / "packages" / "tooly-api").exists())
            self.assertFalse((dest / "Dockerfile").exists())
            root = (dest / "pyproject.toml").read_text()
            for gone in ("tooly-api", "tooly_api", "pydantic", "httpx"):
                self.assertNotIn(gone, root)
            ci = (dest / ".github/workflows/ci.yml").read_text()
            self.assertNotIn("postgres", ci)
            self.assertNotIn("TEST_DATABASE_URL", ci)

    def test_library_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "libby"
            self.assertEqual(run(SCAFFOLD, dest, "--without", "api", "--without", "cli").returncode, 0)
            self.assertEqual(sorted(p.name for p in (dest / "packages").iterdir()), ["libby-core"])
            self.assertNotIn("libby-cli", (dest / "pyproject.toml").read_text())

    def test_rejects_bad_input(self):
        self.assertEqual(run(SCAFFOLD, "/tmp/x", "--name", "Bad-Name").returncode, 2)
        self.assertEqual(run(SCAFFOLD, "/tmp/x", "--without", "web").returncode, 2)
        self.assertEqual(run(SCAFFOLD).returncode, 2)
        self.assertEqual(run(SCAFFOLD, "--help").returncode, 0)

    @unittest.skipUnless(UV and os.environ.get("PYTHON_SKILL_UV_TESTS"), "set PYTHON_SKILL_UV_TESTS=1 (needs uv + PyPI)")
    def test_scaffold_without_api_passes_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "tooly"
            self.assertEqual(run(SCAFFOLD, dest, "--without", "api").returncode, 0)
            for cmd in (["uv", "lock"], ["uv", "sync", "--locked"],
                        ["uv", "run", "ruff", "format", "--check"], ["uv", "run", "ruff", "check"],
                        ["uv", "run", "mypy"], ["uv", "run", "pytest", "-q"],
                        ["uv", "build", "--all-packages", "--no-sources"]):
                res = subprocess.run(cmd, cwd=dest, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"{cmd}: {res.stdout[-2000:]}{res.stderr[-2000:]}")


if __name__ == "__main__":
    unittest.main()
