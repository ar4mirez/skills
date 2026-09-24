"""Tests for skills/c/scripts (run: make test). The build test is skipped when cmake/cc are missing."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "c"
AUDIT = SKILL / "scripts" / "audit.py"
NEWPROJ = SKILL / "scripts" / "new_project.py"
FLAWED = SKILL / "evals" / "files" / "flawed_project"


def py(*args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)


def audit_json(root, *extra):
    res = py(AUDIT, root, "--json", *extra)
    return res, json.loads(res.stdout)


CLEAN_C = r'''
#include "clean.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Comments may mention strcpy(dst, src) and gets(buf) freely. */
static volatile sig_atomic_t got_signal = 0;

char *clean_dup(const char *s, size_t len) {
    char *p = malloc(len + 1);
    if (!p) {
        return NULL;
    }
    memcpy(p, s, len);
    p[len] = '\0';
    return p;
}

int *clean_array(size_t n) {
    int *xs = calloc(n, sizeof *xs);
    if (xs == NULL) {
        return NULL;
    }
    return xs;
}

void *clean_one(void) {
    void *q = malloc(sizeof(int));
    return q;
}

int clean_grow(char **buf, size_t *cap) {
    char *bigger = realloc(*buf, *cap);
    if (!bigger) {
        return -1;
    }
    *buf = bigger;
    return 0;
}

long clean_parse(const char *s, int *ok) {
    char *end = NULL;
    errno = 0;
    long v = strtol(s, &end, 10);
    *ok = errno == 0 && end != s && *end == '\0';
    return v;
}

void clean_print(const char *name, char *out, size_t cap) {
    printf("hello\n");
    printf("%s\n", name);
    fprintf(stderr, "gets( and strcpy( inside a string are fine: %s\n", name);
    int n = snprintf(out, cap, "%s", name);
    (void)n;
    size_t len = strlen(name);
    for (size_t i = 0; i < len; i++) {
        (void)name[i];
    }
    (void)got_signal;
}
'''

CLEAN_H = '''#pragma once
#include <stddef.h>
char *clean_dup(const char *s, size_t len);
void *clean_one(void);
'''

CLEAN_CMAKE = '''cmake_minimum_required(VERSION 3.25...4.4)
project(clean LANGUAGES C)
include(CheckCCompilerFlag)
add_library(clean_warnings INTERFACE)
target_compile_options(clean_warnings INTERFACE -Wall -Wextra -Wpedantic -Wconversion -Wshadow
  -Wformat=2 -Wimplicit-fallthrough)
add_library(clean_hardening INTERFACE)
check_c_compiler_flag(-fcf-protection=full HAVE_CF)
target_compile_options(clean_hardening INTERFACE -fstack-protector-strong
  $<$<CONFIG:Release>:-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3>)
add_library(clean src/clean.c)
set_target_properties(clean PROPERTIES C_STANDARD 23 C_STANDARD_REQUIRED ON)
target_link_libraries(clean PRIVATE clean_warnings clean_hardening)
enable_testing()
add_test(NAME smoke COMMAND clean)
'''

CLEAN_PRESETS = '{"version": 6, "configurePresets": [{"name": "asan", "cacheVariables": ' \
                '{"CMAKE_C_FLAGS": "-fsanitize=address,undefined"}}]}'


def write_clean(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "clean.c").write_text(CLEAN_C)
    (root / "src" / "clean.h").write_text(CLEAN_H)
    (root / "CMakeLists.txt").write_text(CLEAN_CMAKE)
    (root / "CMakePresets.json").write_text(CLEAN_PRESETS)
    (root / "Dockerfile").write_text("FROM alpine:3.24 AS build\nRUN true\n"
                                     "FROM gcr.io/distroless/static-debian13:nonroot\n")


class AuditTests(unittest.TestCase):
    def test_flawed_project_findings(self):
        res, out = audit_json(FLAWED)
        self.assertEqual(res.returncode, 1, res.stderr)
        checks = {f["check"] for f in out["findings"]}
        for expected in ("gets", "unbounded-string-fn", "scanf-unbounded", "format-nonliteral",
                         "realloc-self-assign", "cmake-min-too-old", "unchecked-alloc",
                         "alloc-size-overflow", "atoi-family", "shell-exec", "volatile-sync",
                         "void-main", "assert-side-effect", "missing-include-guard",
                         "global-cmake-flags", "no-warnings", "no-hardening", "no-tests",
                         "no-sanitizers", "strtok", "rand", "strlen-in-loop", "c11-threads",
                         "empty-param-list", "hardcoded-werror", "no-c-standard", "glob-sources",
                         "no-presets", "docker-heavy-runtime", "docker-root"):
            self.assertIn(expected, checks)
        self.assertGreaterEqual(out["summary"]["high"], 8)

    def test_line_numbers_point_at_the_call(self):
        _, out = audit_json(FLAWED, "--fail-on", "none")
        locs = {(f["check"], f["location"]) for f in out["findings"]}
        self.assertIn(("scanf-unbounded", "src/main.c:27"), locs)
        self.assertIn(("gets", "src/parser.c:29"), locs)
        self.assertIn(("unchecked-alloc", "src/parser.c:9"), locs)

    def test_clean_project_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_clean(Path(tmp))
            res, out = audit_json(tmp, "--fail-on", "low")
        self.assertEqual(out["findings"], [])
        self.assertEqual(res.returncode, 0)

    def test_assets_have_no_findings(self):
        res, out = audit_json(SKILL / "assets", "--fail-on", "low")
        self.assertEqual(out["findings"], [], out)
        self.assertEqual(res.returncode, 0)

    def test_inline_suppression(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_clean(Path(tmp))
            (Path(tmp) / "src" / "legacy.c").write_text(
                "#include <string.h>\nvoid f(char *d, const char *s) {\n"
                "    strcpy(d, s); /* audit:ignore=unbounded-string-fn (bounded by caller) */\n}\n")
            _, out = audit_json(tmp, "--fail-on", "low")
        self.assertEqual(out["findings"], [])

    def test_fail_on_threshold_and_bad_invocation(self):
        self.assertEqual(py(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(py(AUDIT, "/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(py(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(py(AUDIT, "--no-such-flag").returncode, 2)
        self.assertEqual(py(AUDIT, "--help").returncode, 0)
        text = py(AUDIT, FLAWED).stdout
        self.assertIn("high", text)


class NewProjectTests(unittest.TestCase):
    def test_service_layout_and_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = py(NEWPROJ, "ringbuf", tmp, "--kind", "service", "--force")
            self.assertEqual(res.returncode, 0, res.stderr)
            root = Path(tmp)
            for rel in ("CMakeLists.txt", "CMakePresets.json", "include/ringbuf/ringbuf.h",
                        "src/ringbuf.c", "src/arena.c", "app/cli.c", "app/server.c",
                        "tests/test_ringbuf.c", "tests/test_http.c", "fuzz/fuzz_parse.c",
                        "Dockerfile", "config/deploy.yml", ".github/workflows/ci.yml",
                        "cmake/zig-toolchain.cmake", ".clang-format", ".clang-tidy"):
                self.assertTrue((root / rel).is_file(), rel)
            cm = (root / "CMakeLists.txt").read_text()
            self.assertIn("RINGBUF_SANITIZE", cm)
            self.assertNotIn("kvstore", cm)
            self.assertNotIn("# >>>", cm)
            _, out = audit_json(root, "--fail-on", "low")
            self.assertEqual(out["findings"], [])

    def test_lib_kind_strips_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(py(NEWPROJ, "ringbuf", tmp, "--kind", "lib", "--force").returncode, 0)
            root = Path(tmp)
            self.assertFalse((root / "app").exists())
            cm = (root / "CMakeLists.txt").read_text()
            self.assertNotIn("app/", cm)
            self.assertIn("add_test(NAME ringbuf", cm)

    def test_refuses_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(py(NEWPROJ, "Bad-Name", tmp).returncode, 2)
            self.assertEqual(py(NEWPROJ, "kvstore", tmp).returncode, 2)
            self.assertEqual(py(NEWPROJ, "ok", tmp, "--kind", "gui").returncode, 2)
            (Path(tmp) / "existing.txt").write_text("x")
            self.assertEqual(py(NEWPROJ, "ringbuf", tmp).returncode, 1)


CMAKE = shutil.which("cmake")
NINJA = shutil.which("ninja")
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


@unittest.skipUnless(CMAKE and NINJA and CC and os.name == "posix" and os.environ.get("C_SKILL_BUILD"),
                     "set C_SKILL_BUILD=1 with cmake >= 3.25, ninja, and a C23 compiler on PATH")
class BuildTests(unittest.TestCase):
    def test_scaffold_builds_and_tests_under_asan(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(py(NEWPROJ, "ringbuf", tmp, "--kind", "service", "--force").returncode, 0)
            for cmd in (["cmake", "--preset", "ci"], ["cmake", "--build", "--preset", "ci"],
                        ["ctest", "--preset", "ci"]):
                res = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
