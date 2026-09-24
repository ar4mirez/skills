"""Tests for skills/cpp/scripts (run: make test). Pure Python; the optional build test is
skipped unless CMake 3.28+, Ninja, a C++23 compiler, and VCPKG_ROOT are available."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "cpp"
AUDIT = SKILL / "scripts" / "audit.py"
NEWPROJ = SKILL / "scripts" / "new_project.py"
FLAWED = SKILL / "evals" / "files" / "legacy_service"


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


def audit_json(root, *extra):
    res = run(AUDIT, root, "--json", *extra)
    return res, json.loads(res.stdout)


class AuditTests(unittest.TestCase):
    def test_flawed_fixture_findings(self):
        res, out = audit_json(FLAWED)
        self.assertEqual(res.returncode, 1, res.stderr)
        checks = {f["check"] for f in out["findings"]}
        for expected in (
            "naked-new", "naked-delete", "raw-owning-pointer", "missing-virtual-dtor",
            "using-namespace-std-header", "bits-stdc++", "unsafe-c-string", "dangling-view-return",
            "dangling-string-view", "c-style-cast", "malloc-free", "manual-lock", "thread-detach",
            "volatile-sync", "endl-in-loop", "null-macro", "std-thread", "no-include-guard",
            "cmake-min-version", "cmake-no-standard", "cmake-global-flags", "fast-math",
            "cmake-glob-sources", "cmake-hardcoded-build-type", "cmake-unconditional-werror",
            "cmake-no-warnings", "no-sanitizers", "no-presets", "vcpkg-no-baseline",
            "docker-fat-runtime",
        ):
            self.assertIn(expected, checks)
        self.assertGreaterEqual(out["summary"]["high"], 10)

    def test_scaffolded_project_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(NEWPROJ, "inventory", "--dir", tmp).returncode, 0)
            res, out = audit_json(Path(tmp) / "inventory", "--fail-on", "low")
        self.assertEqual(out["findings"], [])
        self.assertEqual(res.returncode, 0)

    def test_no_false_positives_on_idiomatic_code(self):
        src = r'''
#pragma once
#include <memory>
#include <string>
#include <string_view>
struct Widget final {
  Widget() = default;
  Widget(const Widget&) = delete;            // deleted functions are not naked delete
  Widget& operator=(const Widget&) = delete;
  virtual ~Widget() = default;
  virtual void draw() const {}
};
class Base {
 public:
  virtual void run() = 0;
 protected:
  ~Base() = default;                          // protected non-virtual dtor is fine (C.35)
};
class Derived : public Base {                 // inherits Base's destructor
 public:
  void run() override {}
};
inline std::string_view view_of(const std::string& s) { return s; }   // view of a parameter ref
inline void f() {
  auto p = std::make_unique<int>(1'000);      // digit separators are not char literals
  (void)p;                                    // void cast is not a C-style cast
  const char* msg = "new Widget; delete x; (int)y; using namespace std;";  // in a string
  (void)msg;
  // new Widget(); delete ptr; std::endl  <- comments are ignored
  auto n = sizeof(int);
  (void)n;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "include").mkdir()
            (root / "include" / "widget.hpp").write_text(src)
            (root / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.28...4.4)\nproject(x CXX)\n"
                "set(CMAKE_CXX_STANDARD 23)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\nset(CMAKE_CXX_EXTENSIONS OFF)\n"
                "add_library(x INTERFACE)\n"
                "target_compile_options(x INTERFACE -Wall -Wextra $<$<BOOL:${X_WERROR}>:-Werror>)\n")
            (root / "CMakePresets.json").write_text('{"version": 8, "configurePresets": [{"name": "asan", '
                                                    '"cacheVariables": {"X_SANITIZERS": "address;undefined"}}]}')
            res, out = audit_json(root, "--fail-on", "low")
        self.assertEqual(out["findings"], [], out["findings"])
        self.assertEqual(res.returncode, 0)

    def test_suppression_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.cpp").write_text("int* p = new int(1);  // NOLINT(owning-memory): C API takes ownership\n")
            _, out = audit_json(tmp, "--fail-on", "none")
        self.assertNotIn("naked-new", {f["check"] for f in out["findings"]})

    def test_fail_on_threshold_and_bad_invocation(self):
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(run(AUDIT, "/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(run(AUDIT, "--help").returncode, 0)

    def test_text_output(self):
        res = run(AUDIT, FLAWED)
        self.assertIn("HIGH (", res.stdout)
        self.assertRegex(res.stdout, r"summary: \d+ high, \d+ medium, \d+ low")


class NewProjectTests(unittest.TestCase):
    def test_layout_and_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run(NEWPROJ, "inventory", "--dir", tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            root = Path(tmp) / "inventory"
            for rel in ("CMakeLists.txt", "CMakePresets.json", "vcpkg.json", ".clang-format", ".clang-tidy",
                        "cmake/ProjectOptions.cmake", "libs/wordcount/include/inventory/wordcount/wordcount.hpp",
                        "apps/wc/main.cpp", "apps/wc-server/main.cpp", "tests/wordcount_test.cpp",
                        ".github/workflows/ci.yml", "Dockerfile", "config/deploy.yml"):
                self.assertTrue((root / rel).is_file(), rel)
            text = "\n".join(p.read_text() for p in root.rglob("*") if p.is_file())
            self.assertIsNone(re.search(r"\bacme\b|ACME_", text))
            self.assertIn("namespace inventory::wordcount", (root / "libs/wordcount/include/inventory/wordcount/wordcount.hpp").read_text())
            self.assertIn("INVENTORY_SANITIZERS", (root / "CMakePresets.json").read_text())
            self.assertEqual(run(NEWPROJ, "inventory", "--dir", tmp).returncode, 1)

    def test_no_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(NEWPROJ, "lite", "--dir", tmp, "--no-service").returncode, 0)
            root = Path(tmp) / "lite"
            self.assertFalse((root / "apps" / "wc-server").exists())
            self.assertFalse((root / "config" / "deploy.yml").exists())
            self.assertNotIn("cpp-httplib", (root / "vcpkg.json").read_text())
            json.loads((root / "vcpkg.json").read_text())
            self.assertNotIn("wc-server", (root / "CMakeLists.txt").read_text())

    def test_rejects_bad_input(self):
        self.assertEqual(run(NEWPROJ, "Bad-Name").returncode, 2)
        self.assertEqual(run(NEWPROJ, "ok", "--dir", "/nonexistent-dir-xyz").returncode, 2)


CMAKE = shutil.which("cmake")
NINJA = shutil.which("ninja")
VCPKG = os.environ.get("VCPKG_ROOT")


def _cmake_new_enough() -> bool:
    if not CMAKE:
        return False
    m = re.search(r"(\d+)\.(\d+)", subprocess.run([CMAKE, "--version"], capture_output=True, text=True).stdout)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (3, 28)


@unittest.skipUnless(_cmake_new_enough() and NINJA and VCPKG and os.environ.get("CPP_SKILL_BUILD_TEST"),
                     "set CPP_SKILL_BUILD_TEST=1 with CMake 3.28+, Ninja, and VCPKG_ROOT to build the scaffold")
class ScaffoldBuildTest(unittest.TestCase):
    def test_asan_workflow_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(NEWPROJ, "demo", "--dir", tmp, "--no-service").returncode, 0)
            res = subprocess.run([CMAKE, "--workflow", "--preset", "asan"], cwd=Path(tmp) / "demo",
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stdout[-4000:] + res.stderr[-4000:])


if __name__ == "__main__":
    unittest.main()
