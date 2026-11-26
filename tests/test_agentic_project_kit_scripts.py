"""Tests for skills/agentic-project-kit/scripts/kit.sh (run: make test).

Every test works inside a fresh temporary directory, so the script never
touches the real repository or the home directory. On CI, `sh` is dash, which
also checks that the script is portable POSIX sh.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "agentic-project-kit"
KIT = SKILL / "scripts" / "kit.sh"
TODAY = "2026-11-26"


def run(*args, env_extra=None, cwd=None):
    env = dict(os.environ, KIT_TODAY=TODAY)
    env.update(env_extra or {})
    return subprocess.run(["sh", str(KIT), *map(str, args)], capture_output=True, text=True, env=env, cwd=cwd)


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def fill_placeholders(repo: Path) -> None:
    for p in repo.rglob("*.md"):
        if p.name != "TEMPLATE.md":
            text = p.read_text()
            while "{{" in text:
                start = text.index("{{")
                end = text.index("}}", start) + 2
                text = text[:start] + "x" + text[end:]
            p.write_text(text)


class KitTestCase(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="kit-test-"))
        self.repo = self.base / "repo"
        self.repo.mkdir()

    def tearDown(self):
        shutil.rmtree(self.base)

    def scaffold(self, *opts):
        res = run("scaffold", *opts, "--owner", "ana", self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res

    def audit(self, *opts):
        return run("audit", *opts, self.repo)


class ScaffoldTests(KitTestCase):
    def test_lite_creates_only_lite_files(self):
        self.scaffold()
        files = set(snapshot(self.repo))
        self.assertEqual(files, {
            "AGENTS.md", "CLAUDE.md", "PRODUCT.md", "TECH.md", "SECURITY.md",
            "docs/decisions/README.md", "docs/decisions/TEMPLATE.md", ".scratch/.gitignore",
        })
        self.assertEqual((self.repo / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertIn("owner: ana", (self.repo / "PRODUCT.md").read_text())
        self.assertIn("# repo: product", (self.repo / "PRODUCT.md").read_text())

    def test_full_and_options(self):
        self.scaffold("--profile", "full", "--extensions", "--map")
        for rel in ("AGENTIC.md", "CHANGES.md", "GLOSSARY.md", "EXTENSIONS.md", "docs/kit-map.md",
                    "docs/milestones/TEMPLATE.md", "docs/incidents/TEMPLATE.md", "docs/evals/agent-safety.md",
                    "docs/changes/README.md", "docs/runbooks/TEMPLATE.md", "docs/security/README.md",
                    "docs/prd/README.md"):
            self.assertTrue((self.repo / rel).is_file(), rel)

    def test_never_overwrites(self):
        (self.repo / "AGENTS.md").write_text("mine\n")
        res = self.scaffold()
        self.assertIn("skip    AGENTS.md (exists)", res.stdout)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "mine\n")
        second = self.scaffold()
        self.assertNotIn("create", second.stdout.replace("scaffold:", ""))

    def test_special_characters_in_names(self):
        res = run("scaffold", "--project", "a|b&c\\d", "--owner", "x/y", self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("# a|b&c\\d: product", (self.repo / "PRODUCT.md").read_text())
        self.assertIn("owner: x/y", (self.repo / "PRODUCT.md").read_text())

    def test_refuses_to_write_through_symlink_outside_repo(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.repo / "docs").symlink_to(outside)
        res = run("scaffold", self.repo)
        self.assertEqual(res.returncode, 1)
        self.assertIn("outside the repo", res.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_refuses_root_and_home(self):
        self.assertEqual(run("scaffold", "/").returncode, 2)
        fake_home = self.base / "home"
        fake_home.mkdir()
        res = run("scaffold", fake_home, env_extra={"HOME": str(fake_home)})
        self.assertEqual(res.returncode, 2)
        self.assertEqual(list(fake_home.iterdir()), [])

    def test_writes_nothing_outside_target(self):
        before = snapshot(self.base)
        self.scaffold("--profile", "full")
        after = snapshot(self.base)
        self.assertTrue(all(k.startswith("repo/") for k in set(after) - set(before)))


class AuditTests(KitTestCase):
    def test_fresh_scaffold_has_no_errors_and_audit_is_read_only(self):
        self.scaffold("--profile", "full")
        before = snapshot(self.repo)
        res = self.audit()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("0 errors", res.stdout)
        self.assertIn("profile full", res.stdout)
        self.assertIn("warn K06", res.stdout)
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(self.audit("--strict").returncode, 1)

    def test_filled_kit_with_tests_is_clean_under_strict(self):
        self.scaffold("--profile", "full")
        fill_placeholders(self.repo)
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "core_test.sh").write_text("# CORE-01 SEC-01\n")
        res = self.audit("--strict")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("0 errors, 0 warnings", res.stdout)

    def test_empty_repo_reports_missing_files(self):
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        for rel in ("AGENTS.md", "CLAUDE.md", "PRODUCT.md", "TECH.md", "SECURITY.md"):
            self.assertIn(f"error K01 {rel}:", res.stdout)
        self.assertIn("profile lite", res.stdout)

    def test_claude_md_copy_and_safety_section(self):
        self.scaffold()
        (self.repo / "AGENTS.md").write_text("# Agents\n\nNo rules.\n")
        (self.repo / "CLAUDE.md").write_text("# Agents\n\nNo rules.\n")
        out = self.audit().stdout
        self.assertIn("error K02 CLAUDE.md", out)
        self.assertIn("error K16 AGENTS.md", out)

    def test_size_cap(self):
        self.scaffold()
        with open(self.repo / "TECH.md", "a") as fh:
            fh.write("word " * 8000)
        self.assertIn("error K03 TECH.md", self.audit().stdout)

    def test_front_matter_problems(self):
        self.scaffold()
        (self.repo / "TECH.md").write_text("# no front matter\n")
        (self.repo / "PRODUCT.md").write_text("---\nstatus: bogus\nversion: one\nowner: \nrequirements: A-1\n---\n")
        out = self.audit().stdout
        self.assertIn("error K04 TECH.md", out)
        self.assertEqual(out.count("error K05 PRODUCT.md"), 4)

    def test_requirement_ids(self):
        self.scaffold("--profile", "full")
        product = self.repo / "PRODUCT.md"
        text = product.read_text().replace(
            "| CORE-01 | {{the first thing",
            "| CORE-01 | dup | must | x |\n| core-2 | bad | must | x |\n| OLD-01 | gone, withdrawn | must | x |\n| CORE-01 | {{the first thing")
        product.write_text(text)
        (self.repo / "docs" / "milestones" / "M01-core.md").write_text(
            "---\nstatus: in-progress\nversion: 1.0.0\nowner: ana\nrequirements: [CORE-01, NOPE-99]\n"
            "budget_tokens: 120000\n---\n\n# M01\n\n## Exit tests\n\n- CORE-01\n")
        out = self.audit().stdout
        self.assertIn("is malformed", out)
        self.assertIn("CORE-01 is already defined", out)
        self.assertIn("error K08 docs/milestones/M01-core.md: references NOPE-99", out)
        self.assertIn("warn K11 PRODUCT.md", out)
        self.assertIn("warn K10 SECURITY.md:", out)  # SEC-01 is in no brief
        self.assertNotIn("OLD-01 has no test", out)  # withdrawn rows skip the test check
        self.assertIn("expected [CORE-01, OLD-01]", out)  # ...but stay in the front matter list

    def test_milestone_calendar_language(self):
        self.scaffold("--profile", "full")
        (self.repo / "docs" / "milestones" / "M02-x.md").write_text(
            "---\nstatus: not-started\nversion: 1.0.0\nowner: ana\nrequirements: []\n---\n\nDone by the deadline, ETA Friday.\n")
        out = self.audit().stdout
        self.assertIn("error K14 docs/milestones/M02-x.md: plans in calendar time", out)
        self.assertIn("needs budget_tokens", out)
        self.assertIn("has no Exit tests section", out)

    def test_decision_and_incident_shape(self):
        self.scaffold("--profile", "full")
        (self.repo / "docs" / "decisions" / "0001-db.md").write_text(
            "---\nstatus: decided\nversion: 1.0.0\nowner: ana\nrequirements: []\n---\n\n"
            "## Options\n\n## Recommendation\n\n## Decision\n\nAna agreed.\n")
        (self.repo / "docs" / "incidents" / "2026-11-01-x.md").write_text(
            "---\nstatus: open\nversion: 1.0.0\nowner: ana\nrequirements: []\n---\n\n# x\n")
        out = self.audit().stdout
        self.assertIn("warn K15 docs/decisions/0001-db.md: is decided but", out)
        self.assertIn("warn K17 docs/incidents/2026-11-01-x.md", out)
        quoted = (self.repo / "docs" / "decisions" / "0001-db.md")
        quoted.write_text(quoted.read_text() + "\n> Go with it.\n")
        self.assertNotIn("K15", self.audit().stdout)

    def test_risk_acceptance_expiry(self):
        self.scaffold()
        with open(self.repo / "SECURITY.md", "a") as fh:
            fh.write("| RA-01 | long | ana | 2026-10-01 | 2027-03-01 | x |\n"
                     "| RA-02 | old | ana | 2026-07-01 | 2026-09-01 | x |\n"
                     "| RA-03 | soon | ana | 2026-11-01 | 2026-12-01 | x |\n"
                     "| RA-04 | ok | ana | 2026-11-20 | 2027-01-20 | x |\n"
                     "| RA-05 | bad | ana | soon | later | x |\n")
        out = self.audit().stdout
        self.assertIn("RA-01 runs 151 days", out)
        self.assertIn("RA-02 expired on 2026-09-01", out)
        self.assertIn("warn K12 SECURITY.md:", out)
        self.assertIn("RA-03 expires on 2026-12-01", out)
        self.assertNotIn("RA-04", out)
        self.assertIn("RA-05 needs Accepted and Expires dates", out)

    def test_kit_map_satisfies_roles(self):
        (self.repo / "AGENTS.md").write_text("# Agents\n\n## Agent safety\n\n- stay in the repo\n")
        (self.repo / "CLAUDE.md").write_text("@AGENTS.md\n")
        (self.repo / "spec").mkdir()
        (self.repo / "spec" / "reqs.md").write_text("| ID | Requirement |\n| --- | --- |\n| PAY-01 | pay |\n")
        (self.repo / "adr").mkdir()
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "kit-map.md").write_text(
            "| Kit file | Maps to | Why |\n| --- | --- | --- |\n"
            "| PRODUCT.md | spec/reqs.md | theirs |\n| TECH.md | n/a | tiny tool |\n"
            "| SECURITY.md | .github/SECURITY.md | theirs |\n| docs/decisions/ | adr/ | ADRs |\n")
        out = self.audit().stdout
        self.assertNotIn("K01 PRODUCT.md", out)
        self.assertNotIn("K01 TECH.md", out)
        self.assertNotIn("K01 docs/decisions", out)
        self.assertIn("error K01 SECURITY.md: mapped to .github/SECURITY.md", out)
        self.assertIn("PAY-01 has no test", out)  # mapped files are requirement sources


class TraceIndexTests(KitTestCase):
    def test_trace_matrix(self):
        self.scaffold("--profile", "full")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a_test.py").write_text("def test_core():  # CORE-01\n    pass\n")
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules" / "x.js").write_text("// SEC-01\n")
        (self.repo / "docs" / "milestones" / "M01-core.md").write_text(
            "---\nstatus: done\nversion: 1.0.0\nowner: ana\nrequirements: [CORE-01]\nbudget_tokens: 1\n---\n")
        lines = run("trace", self.repo).stdout.splitlines()
        self.assertEqual(lines[0], "id\tstate\tdefined_at\ttest_files\tmilestones")
        rows = {l.split("\t")[0]: l.split("\t") for l in lines[1:]}
        self.assertEqual(rows["CORE-01"][3:], ["1", "M01-core"])
        self.assertEqual(rows["SEC-01"][3:], ["0", "-"])  # node_modules is skipped

    def test_index(self):
        self.scaffold()
        out = run("index", self.repo).stdout
        self.assertIn("PRODUCT.md\tdraft\t0.1.0\tana\t[CORE-01]", out)
        self.assertNotIn("AGENTS.md", out)


class RotateTests(KitTestCase):
    def test_rotate_moves_unreleased(self):
        self.scaffold("--profile", "full")
        changes = self.repo / "CHANGES.md"
        changes.write_text(changes.read_text().replace("## Unreleased\n\n-\n", "## Unreleased\n\n- Login for CORE-01 (SHA-256)\n"))
        res = run("rotate", "--version", "1.2.0", self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        released = (self.repo / "docs" / "changes" / "1.2.0.md").read_text()
        self.assertIn("status: released", released)
        self.assertIn("requirements: [CORE-01]", released)
        self.assertIn("- Login for CORE-01", released)
        text = changes.read_text()
        self.assertNotIn("Login", text)
        self.assertIn("| 1.2.0 | [docs/changes/1.2.0.md](docs/changes/1.2.0.md) |", text)
        self.assertFalse((self.repo / ".scratch" / f"CHANGES.md.{os.getpid()}").exists())
        self.assertEqual([p.name for p in (self.repo / ".scratch").iterdir()], [".gitignore"])
        self.assertEqual(run("rotate", "--version", "1.3.0", self.repo).returncode, 1)  # nothing to release
        self.assertEqual(run("rotate", "--version", "1.2.0", self.repo).returncode, 1)  # exists
        self.assertEqual(run("rotate", "--version", "../x", self.repo).returncode, 2)
        self.assertNotIn("K13", run("audit", self.repo).stdout)


class GuardTests(KitTestCase):
    def test_guard_refuses_dangerous_paths(self):
        (self.repo / "f.txt").write_text("x")
        (self.repo / "sub").mkdir()
        outside = self.base / "outside.txt"
        outside.write_text("x")
        home = self.base / "home"
        home.mkdir()
        env = {"HOME": str(home)}
        for path in ("/", str(home), str(self.repo), str(self.repo / "sub"), str(outside),
                     str(self.repo / ".." / "outside.txt"), str(self.repo / "missing")):
            res = run("guard-check", self.repo, path, env_extra=env)
            self.assertEqual(res.returncode, 1, path)
            self.assertTrue(res.stdout.startswith("refuse"), path)
        res = run("guard-check", self.repo, self.repo / "f.txt", env_extra=env)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(outside.exists() and (self.repo / "f.txt").exists())


class CliTests(unittest.TestCase):
    def test_help_and_usage_errors(self):
        res = run("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Exit codes:", res.stdout)
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("nope").returncode, 2)
        self.assertEqual(run("audit", "--bogus", ".").returncode, 2)
        self.assertEqual(run("audit", "/does/not/exist").returncode, 2)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_shellcheck_clean(self):
        res = subprocess.run(["shellcheck", "-s", "sh", str(KIT)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)


if __name__ == "__main__":
    unittest.main()
