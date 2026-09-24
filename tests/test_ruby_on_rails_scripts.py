"""Tests for skills/ruby-on-rails/scripts (run: make test). Skipped when Ruby isn't installed."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "ruby-on-rails"
AUDIT = SKILL / "scripts" / "rails_audit.rb"
PATHCFG = SKILL / "scripts" / "check_path_config.rb"
SAMPLE = SKILL / "evals" / "files" / "sample_app"
RUBY = shutil.which("ruby")


def run(*args):
    return subprocess.run([RUBY, *map(str, args)], capture_output=True, text=True)


@unittest.skipUnless(RUBY, "ruby not installed")
class RailsAuditTests(unittest.TestCase):
    def findings(self, *extra):
        res = run(AUDIT, SAMPLE, "--json", *extra)
        return res.returncode, json.loads(res.stdout)["findings"]

    def test_sample_app_findings(self):
        code, findings = self.findings()
        self.assertEqual(code, 1)  # has high-severity findings
        checks = {f["check"] for f in findings}
        for expected in ("unindexed-foreign-key", "rescue-exception", "non-restful-route", "non-restful-action",
                         "unscoped-find", "services-directory", "default-scope", "side-effect-in-transaction",
                         "update-attribute", "callback-recursion", "legacy-strong-params", "time-zone", "redis-dependency"):
            self.assertIn(expected, checks)

    def test_polymorphic_index_counts_and_indexed_fk_not_flagged(self):
        _, findings = self.findings()
        fk = {f["message"].split(" ")[0] for f in findings if f["check"] == "unindexed-foreign-key"}
        self.assertEqual(fk, {"comments.author_id", "invoices.customer_id"})

    def test_restful_actions_and_private_methods_not_flagged(self):
        _, findings = self.findings()
        actions = [f["message"] for f in findings if f["check"] == "non-restful-action"]
        self.assertEqual(len(actions), 1)
        self.assertIn("publish", actions[0])

    def test_fail_on_none_exits_zero(self):
        self.assertEqual(run(AUDIT, SAMPLE, "--fail-on", "none").returncode, 0)

    def test_clean_app_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config").mkdir()
            (Path(tmp) / "config" / "application.rb").write_text("# app\n")
            res = run(AUDIT, tmp)
        self.assertEqual(res.returncode, 0)
        self.assertIn("No findings", res.stdout)

    def test_not_a_rails_app_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(AUDIT, tmp).returncode, 2)


@unittest.skipUnless(RUBY, "ruby not installed")
class PathConfigTests(unittest.TestCase):
    def test_template_is_valid(self):
        res = run(PATHCFG, SKILL / "assets" / "path-configuration.json", "--json")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(json.loads(res.stdout)["errors"], [])

    def test_bad_config_errors(self):
        res = run(PATHCFG, SKILL / "evals" / "files" / "bad_path_config.json", "--platform", "ios", "--json")
        out = json.loads(res.stdout)
        self.assertEqual(res.returncode, 1)
        text = " ".join(out["errors"] + out["warnings"])
        for needle in ('Missing "settings"', "invalid regex", '"sheet" is invalid', '"half" is invalid',
                       "non-empty array", "Android-only keys", "catch-all"):
            self.assertIn(needle, text)

    def test_android_needs_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "android_v1.json"
            p.write_text(json.dumps({"settings": {}, "rules": [{"patterns": [".*"], "properties": {"context": "default"}}]}))
            res = run(PATHCFG, p, "--platform", "android", "--json")
        out = json.loads(res.stdout)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(any('"uri"' in w for w in out["warnings"]))
        self.assertFalse(any("Version the file name" in w for w in out["warnings"]))

    def test_missing_file_exit_2(self):
        self.assertEqual(run(PATHCFG, "nope.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
