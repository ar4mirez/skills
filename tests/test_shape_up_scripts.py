"""Tests for skills/shape-up/scripts (run: make test)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "shape-up"
CHECK = SKILL / "scripts" / "check_pitch.py"
HILL = SKILL / "scripts" / "hill_chart.py"


def run(*args, stdin=None):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, input=stdin)


class CheckPitchTests(unittest.TestCase):
    def check(self, path):
        res = run(CHECK, path, "--json")
        return res.returncode, json.loads(res.stdout)

    def test_good_pitch_passes_clean(self):
        code, out = self.check(SKILL / "evals" / "files" / "good-pitch.md")
        self.assertEqual(code, 0)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["appetite_weeks"], 6)

    def test_bad_pitch_flags_every_smell(self):
        code, out = self.check(SKILL / "evals" / "files" / "bad-pitch.md")
        self.assertEqual(code, 1)
        text = " ".join(out["errors"] + out["warnings"]).lower()
        for smell in ("more than one cycle", "estimate", "opens with a solution", "wireframe-level",
                      "open questions", "without a decision", "says 'none'", "grab-bag"):
            self.assertIn(smell, text)

    def test_template_placeholders_are_errors(self):
        code, out = self.check(SKILL / "assets" / "pitch-template.md")
        self.assertEqual(code, 1)
        self.assertTrue(any("placeholder" in e for e in out["errors"]))

    def test_missing_ingredients(self):
        res = run(CHECK, "-", "--json", stdin="# Pitch\n\n## Problem\n\nSomething.\n")
        out = json.loads(res.stdout)
        self.assertEqual(res.returncode, 1)
        missing = [e for e in out["errors"] if e.startswith("Missing")]
        self.assertEqual(len(missing), 4)

    def test_unreadable_file_exit_2(self):
        self.assertEqual(run(CHECK, "does-not-exist.md").returncode, 2)


class HillChartTests(unittest.TestCase):
    def write(self, tmp, name, data):
        p = Path(tmp) / name
        p.write_text(json.dumps(data))
        return p

    def test_example_snapshot_renders(self):
        res = run(HILL, SKILL / "assets" / "hill-snapshot.json")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Save/Edit", res.stdout)

    def test_flags_stuck_backslide_late_and_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = self.write(tmp, "prev.json", {"date": "w3", "scopes": [
                {"name": "A", "position": 30}, {"name": "B", "position": 60}, {"name": "C", "position": 70}]})
            cur = self.write(tmp, "cur.json", {"cycle_week": 5, "scopes": [
                {"name": "A", "position": 31}, {"name": "B", "position": 40}, {"name": "C", "position": 90},
                {"name": "D", "position": 10}]})
            res = run(HILL, cur, "--previous", prev, "--format", "markdown")
        self.assertEqual(res.returncode, 0)
        out = res.stdout
        self.assertIn("**stuck**: 'A'", out)
        self.assertIn("**backslide**: 'B'", out)
        self.assertIn("**late-uphill**: 'A'", out)
        self.assertIn("**discovered**: 'D'", out)
        self.assertNotIn("'C' hasn't moved", out)

    def test_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hill.svg"
            res = run(HILL, SKILL / "assets" / "hill-snapshot.json", "--format", "svg", "-o", out)
            self.assertEqual(res.returncode, 0)
            self.assertTrue(out.read_text().startswith("<svg"))

    def test_invalid_position_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = self.write(tmp, "bad.json", {"scopes": [{"name": "X", "position": 140}]})
            res = run(HILL, bad)
        self.assertEqual(res.returncode, 2)
        self.assertIn("0 to 100", res.stderr)


if __name__ == "__main__":
    unittest.main()
