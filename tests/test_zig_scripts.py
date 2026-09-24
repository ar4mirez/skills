"""Tests for skills/zig/scripts (run: make test).

The audit and scaffolder tests need only Python. The build tests need Zig 0.16 on PATH
(or in $ZIG) and are skipped otherwise.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "zig"
AUDIT = SKILL / "scripts" / "audit.py"
NEW = SKILL / "scripts" / "new_project.py"
FLAWED = SKILL / "evals" / "files" / "flawed_project"


def py(*args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)


def find_zig():
    zig = os.environ.get("ZIG") or shutil.which("zig")
    if not zig:
        return None
    try:
        out = subprocess.run([zig, "version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return zig if out.startswith("0.16.") else None


ZIG = find_zig()


def audit_json(root, *extra):
    res = py(AUDIT, root, "--json", *extra)
    return res, json.loads(res.stdout) if res.stdout.strip().startswith("{") else None


class AuditTests(unittest.TestCase):
    def test_flawed_project_findings(self):
        res, out = audit_json(FLAWED)
        self.assertEqual(res.returncode, 1, res.stderr)
        checks = {f["check"] for f in out["findings"]}
        for expected in (
            "build-old-library-api", "build-root-source-file", "build-no-test-step",
            "general-purpose-allocator", "global-env-args", "std-io-renamed", "old-io-api", "std-net-moved",
            "usingnamespace", "thread-sync-primitive", "managed-container", "std-fs-moved", "mem-split-old",
            "json-stringify-old", "removed-time-api", "crypto-random-global", "type-builtin", "async-keyword",
            "read-to-end-alloc", "catch-unreachable", "swallowed-error", "arena-without-deinit", "no-tests",
            "zon-missing-fingerprint", "zon-string-name", "zon-url-without-hash", "zon-unpinned-url",
            "zon-old-min-version", "docker-debug-build", "docker-glibc-static-image", "docker-root-user",
            "gitignore-cache", "anyerror-public", "debug-print-in-library", "raw-thread-spawn",
        ):
            self.assertIn(expected, checks)

    def test_scaffolded_project_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "clean"
            self.assertEqual(py(NEW, dest, "--name", "clean").returncode, 0)
            res, out = audit_json(dest, "--fail-on", "low")
        self.assertEqual(res.returncode, 0, out)
        self.assertEqual(out["findings"], [])

    def test_no_false_positives_on_modern_idioms(self):
        src = r'''const std = @import("std");
//! Migrated from std.io and std.heap.GeneralPurposeAllocator; usingnamespace is gone.
const Io = std.Io;

/// Uses io.async, not the old `async` keyword; see std.fs.cwd() notes in the changelog.
pub fn run(gpa: std.mem.Allocator, io: Io) !void {
    const msg = "std.io.getStdOut() and std.time.sleep are gone";
    var future = io.async(work, .{io});
    defer future.cancel(io) catch {};
    try future.await(io);
    var list: std.ArrayList(u8) = .empty;
    defer list.deinit(gpa);
    try list.appendSlice(gpa, msg);
    var arena: std.heap.ArenaAllocator = .init(gpa);
    defer arena.deinit();
    const text =
        \\catch unreachable, @Type(.int), std.net.Address
    ;
    _ = text;
}

fn work(io: Io) !void {
    try io.sleep(.fromMilliseconds(1), .awake);
}

test run {
    try run(std.testing.allocator, std.testing.io);
    const x = std.fmt.parseInt(u8, "1", 10) catch unreachable;
    _ = x;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "root.zig").write_text(src)
            (root / ".gitignore").write_text(".zig-cache/\nzig-out/\nzig-pkg/\n")
            res, out = audit_json(root, "--fail-on", "low")
        self.assertEqual(out["findings"], [], out)
        self.assertEqual(res.returncode, 0)

    def test_fail_on_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.zig").write_text('const std = @import("std");\npub fn f() void { std.debug.print("x", .{}); }\n'
                                        "test f {}\n")
            (root / ".gitignore").write_text(".zig-cache/\nzig-out/\n")
            self.assertEqual(py(AUDIT, root).returncode, 0)  # only a low finding; default --fail-on high
            self.assertEqual(py(AUDIT, root, "--fail-on", "low").returncode, 1)

    def test_bad_invocation(self):
        self.assertEqual(py(AUDIT, "/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(py(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(py(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)
        help_ = py(AUDIT, "--help")
        self.assertEqual(help_.returncode, 0)
        self.assertIn("Exit codes", help_.stdout)


class NewProjectTests(unittest.TestCase):
    def test_scaffolds_renamed_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "word-stats"
            res = py(NEW, dest)
            self.assertEqual(res.returncode, 0, res.stderr)
            for rel in ("build.zig", "build.zig.zon", ".gitignore", "Dockerfile", "src/root.zig", "src/main.zig",
                        "src/server.zig", "src/c_api.zig", "include/word_stats.h", "examples/use_word_stats.c",
                        "config/deploy.yml", ".github/workflows/ci.yml"):
                self.assertTrue((dest / rel).is_file(), rel)
            zon = (dest / "build.zig.zon").read_text()
            self.assertIn(".name = .word_stats,", zon)
            fp = int(zon.split(".fingerprint = ")[1].split(",")[0], 16)
            self.assertEqual(fp >> 32, zlib.crc32(b"word_stats"))
            self.assertNotIn("tally", (dest / "build.zig").read_text())
            self.assertEqual(py(NEW, dest).returncode, 1)  # not empty without --force
            self.assertEqual(py(NEW, dest, "--force").returncode, 0)

    def test_rejects_bad_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(py(NEW, Path(tmp) / "x", "--name", "Bad-Name").returncode, 2)
            self.assertEqual(py(NEW, Path(tmp) / "y", "--name", "std").returncode, 2)


@unittest.skipUnless(ZIG, "zig 0.16 not installed (set $ZIG or put zig on PATH)")
class ZigBuildTests(unittest.TestCase):
    def test_scaffold_formats_tests_and_cross_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "proj"
            self.assertEqual(py(NEW, dest, "--name", "proj").returncode, 0)

            def zig(*args):
                return subprocess.run([ZIG, *args], cwd=dest, capture_output=True, text=True, timeout=900)

            fmt = zig("fmt", "--check", ".")
            self.assertEqual(fmt.returncode, 0, fmt.stdout + fmt.stderr)
            test = zig("build", "test")
            self.assertEqual(test.returncode, 0, test.stderr)
            cross = zig("build", "-Dtarget=x86_64-linux-musl", "-Doptimize=ReleaseSafe")
            self.assertEqual(cross.returncode, 0, cross.stderr)
            self.assertTrue((dest / "zig-out" / "bin" / "projd").is_file())


if __name__ == "__main__":
    unittest.main()
