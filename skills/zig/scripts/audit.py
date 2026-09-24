#!/usr/bin/env python3
"""Static audit of a Zig project for anti-patterns and pre-0.16 APIs.

Usage:
  python3 scripts/audit.py [ROOT] [--json] [--fail-on high|medium|low|none]

Scans *.zig, build.zig.zon, Dockerfiles, GitHub workflows, and .gitignore under ROOT
(default: current directory). It flags APIs that were removed or renamed in Zig 0.15 and
0.16 (the ones agents commonly hallucinate from older training data), build and package
manifest mistakes, error and memory-handling anti-patterns, and deploy issues.

Regex-level only: it strips comments and string literals first, but it does not parse
Zig. Treat findings as review prompts, and confirm with `zig build`.

Exit codes:
  0  no findings at or above --fail-on (default: high)
  1  findings at or above --fail-on
  2  bad input (missing directory, unknown option)

Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ("high", "medium", "low")
SKIP_DIRS = {".git", ".zig-cache", "zig-cache", "zig-out", "zig-pkg", "node_modules", ".venv", "__pycache__"}

# ---------------------------------------------------------------------------
# Removed or renamed std APIs (verified against the Zig 0.16.0 std source and the
# 0.15.1 / 0.16.0 release notes). Each entry: (check id, severity, regex, message).
# ---------------------------------------------------------------------------
REMOVED_API = [
    ("std-io-renamed", "high", r"\bstd\.io\b",
     "`std.io` no longer exists (renamed `std.Io` in 0.15; the old generic readers/writers are gone). "
     "Use `Io.File.Writer.init(.stdout(), io, &buf)`, `Io.Reader.fixed(bytes)`, `Io.Writer.fixed(buf)`."),
    ("old-io-api", "high",
     r"\b(GenericReader|GenericWriter|AnyReader|AnyWriter|null_writer|CountingReader|CountingWriter|"
     r"BufferedWriter|BufferedReader|bufferedWriter|bufferedReader|fixedBufferStream|getStdOut|getStdErr|getStdIn|"
     r"deprecatedWriter|deprecatedReader)\b",
     "Pre-Writergate stream API (removed by 0.16). Take `*std.Io.Writer` / `*std.Io.Reader`; buffer lives in the "
     "interface, so remember to `flush()`. Counting: `Io.Writer.Discarding`; in-memory: `Io.Writer.Allocating`."),
    ("general-purpose-allocator", "high", r"\bGeneralPurposeAllocator\b",
     "`std.heap.GeneralPurposeAllocator` was removed. Use `init.gpa` from `pub fn main(init: std.process.Init)`, "
     "or `std.heap.DebugAllocator(.{})` when you need your own leak-checked instance."),
    ("std-fs-moved", "high",
     r"\bstd\.fs\.(cwd|File|Dir|openFileAbsolute|openDirAbsolute|createFileAbsolute|deleteFileAbsolute|"
     r"makeDirAbsolute|deleteDirAbsolute|accessAbsolute|copyFileAbsolute|renameAbsolute|rename|realpath\w*|"
     r"selfExe\w*|openSelfExe|symLinkAbsolute|readLinkAbsolute|getAppDataDir|deleteTreeAbsolute|AtomicFile)\b",
     "File system handles moved to `std.Io.Dir` / `std.Io.File` in 0.16 and every operation takes `io` "
     "(`std.Io.Dir.cwd().openFile(io, path, .{})`, `file.close(io)`)."),
    ("std-net-moved", "high", r"\bstd\.net\b",
     "`std.net` moved to `std.Io.net` in 0.16 (`Io.net.IpAddress.parse(host, port)`, `address.listen(io, .{})`, "
     "`server.accept(io)`)."),
    ("thread-sync-primitive", "high",
     r"\bstd\.Thread\.(Mutex|Condition|ResetEvent|WaitGroup|Semaphore|RwLock|Futex|Pool)\b",
     "Moved to the Io interface in 0.16: `std.Io.Mutex`/`Condition`/`Event`/`Semaphore`/`RwLock`/`Futex`; "
     "`Thread.WaitGroup` and `Thread.Pool` became `std.Io.Group` (`group.async(io, f, args)`, `group.await(io)`)."),
    ("removed-time-api", "high",
     r"\bstd\.(time|Thread)\.sleep\b|\bstd\.time\.(timestamp|milliTimestamp|microTimestamp|nanoTimestamp|Instant|Timer)\b",
     "Time and sleep go through Io in 0.16: `io.sleep(.fromMilliseconds(n), .awake)`, "
     "`std.Io.Timestamp.now(io, .awake)`, `ts.untilNow(io, .awake)`."),
    ("global-env-args", "high",
     r"\bstd\.(os|posix)\.(getenv|environ|argv)\b|\bstd\.process\.(getEnvVarOwned|getEnvMap|argsAlloc|argsFree|"
     r"args|argsWithAllocator|hasEnvVar\w*|getCwd\w*)\b",
     "Environment and argv are no longer global in 0.16. Read them in `main(init: std.process.Init)` "
     "(`init.environ_map.get(\"PORT\")`, `init.minimal.args.toSlice(arena)`) and pass values down."),
    ("crypto-random-global", "high", r"\bstd\.crypto\.random\b",
     "`std.crypto.random` was removed in 0.16. Use `io.random(&buf)` (or `io.randomSecure`) or "
     "`std.Random.IoSource{ .io = io }` for a `std.Random` interface."),
    ("managed-container", "high",
     r"\bArrayList(Unmanaged|Aligned)?\([^()]*\)\.init\(|\bstd\.(AutoArrayHashMap|StringArrayHashMap|ArrayHashMap)\(",
     "Containers are unmanaged: `var list: std.ArrayList(T) = .empty;` and pass the allocator to each call "
     "(`list.append(gpa, x)`, `list.deinit(gpa)`). Managed array hash maps were removed in 0.16."),
    ("removed-container", "high",
     r"\bstd\.(BoundedArray|fifo|RingBuffer|SegmentedList|once)\b|\bLinearFifo\b|\bstd\.heap\.ThreadSafeAllocator\b",
     "Removed from std (0.15/0.16). BoundedArray: `ArrayList.initBuffer(&buf)` + `appendBounded`; "
     "fifo/RingBuffer: `Io.Reader`/`Io.Writer`; ThreadSafeAllocator: use a thread-safe allocator directly."),
    ("json-stringify-old", "high", r"\bstd\.json\.(stringify|stringifyAlloc)\b",
     "Use `std.json.Stringify.value(v, .{}, writer)`, `std.json.Stringify.valueAlloc(gpa, v, .{})`, "
     "or `writer.print(\"{f}\", .{std.json.fmt(v, .{})})`."),
    ("mem-split-old", "high", r"\bstd\.mem\.(split|tokenize)\s*\(",
     "`std.mem.split`/`tokenize` are gone: use `splitScalar`, `splitSequence`, `splitAny`, `tokenizeAny`, "
     "`tokenizeScalar`, or the 0.16 `cut*` helpers."),
    ("fmt-format-old", "high", r"\bstd\.fmt\.(format|FormatOptions|Formatter)\b",
     "Format methods are `pub fn format(self: T, w: *std.Io.Writer) std.Io.Writer.Error!void`, called with "
     "`{f}`. `std.fmt.format` became `writer.print`, `Formatter` became `std.fmt.Alt`."),
    ("type-builtin", "high", r"@Type\s*\(",
     "`@Type` was removed in 0.16. Use `@Int`, `@Struct`, `@Union`, `@Enum`, `@Pointer`, `@Fn`, `@Tuple`, "
     "or `@EnumLiteral()`."),
    ("usingnamespace", "high", r"\busingnamespace\b",
     "`usingnamespace` was removed in 0.15. Re-export declarations explicitly (`pub const x = other.x;`) "
     "or expose a namespace (`pub const other = @import(\"other.zig\");`)."),
    ("async-keyword", "high", r"(?<![.\w])(await|async)\s+[\w(]|@frameSize\b|@asyncCall\b|\banyframe\b",
     "The `async`/`await` keywords were removed in 0.15. Concurrency is `io.async(f, args)` / "
     "`io.concurrent(f, args)` returning a `Future`, or `std.Io.Group`."),
    ("old-process-child", "high",
     r"\bstd\.process\.Child\.(init|run)\b|\bChild\.init\s*\(|\bstd\.process\.execv\b",
     "0.16: `std.process.spawn(io, .{ .argv = argv, .stdout = .pipe })`, `std.process.run(gpa, io, .{...})`, "
     "`std.process.replace(io, .{...})`."),
    ("read-to-end-alloc", "medium", r"\.readToEndAlloc\s*\(",
     "Removed in 0.16: `var r = file.reader(io, &.{}); r.interface.allocRemaining(gpa, .limited(max))`, or "
     "`std.Io.Dir.cwd().readFileAlloc(io, path, gpa, .limited(max))`."),
]

DEPRECATED_API = [
    ("deprecated-alias", "low",
     r"\bArrayListUnmanaged\b|\bArrayListAligned(Unmanaged)?\b|\bstd\.(Auto|String)?ArrayHashMapUnmanaged\b|"
     r"\bstd\.mem\.(indexOf|lastIndexOf)\w*\b|\bstd\.fs\.path\b|\bstd\.fs\.max_path_bytes\b|"
     r"\bstd\.array_list\.(Managed|AlignedManaged)\b",
     "Deprecated alias in 0.16 (still compiles, will be removed): use `std.ArrayList`, `std.array_list.Aligned`, "
     "`std.array_hash_map.Auto/String/Custom`, `std.mem.find*`, `std.Io.Dir.path`; `array_list.Managed` "
     "(allocator stored inside) is on its way out, so use unmanaged `std.ArrayList`."),
    ("cimport-deprecated", "low", r"@cImport\s*\(",
     "`@cImport` is deprecated in 0.16. Translate the header in build.zig: `b.addTranslateC(.{ .root_source_file = "
     "b.path(\"src/c.h\"), ... }).createModule()` and import it as a module."),
]


class Auditor:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[dict] = []
        self.facts: dict = {}

    def add(self, severity: str, check: str, path: Path | str, line: int | None, message: str) -> None:
        rel = path if isinstance(path, str) else path.relative_to(self.root).as_posix()
        loc = f"{rel}:{line}" if line else rel
        self.findings.append({"severity": severity, "check": check, "location": loc, "message": message})

    # -- file discovery -------------------------------------------------------
    def files(self, pred) -> list[Path]:
        out = []
        stack = [self.root]
        while stack:
            d = stack.pop()
            try:
                entries = sorted(d.iterdir())
            except OSError:
                continue
            for e in entries:
                if e.is_dir():
                    if e.name not in SKIP_DIRS:
                        stack.append(e)
                elif pred(e):
                    out.append(e)
        return sorted(out)

    # -- entry point ----------------------------------------------------------
    def run(self) -> None:
        zig_files = self.files(lambda p: p.suffix == ".zig")
        zons = self.files(lambda p: p.name == "build.zig.zon")
        dockerfiles = self.files(lambda p: p.name == "Dockerfile" or p.name.startswith("Dockerfile.")
                                 or p.name.endswith(".Dockerfile"))
        workflows = [p for p in self.files(lambda p: p.suffix in (".yml", ".yaml"))
                     if ".github" in p.relative_to(self.root).parts]
        self.facts = {
            "zig_files": len(zig_files),
            "build_zig": [p.relative_to(self.root).as_posix() for p in zig_files if p.name == "build.zig"],
            "manifests": [p.relative_to(self.root).as_posix() for p in zons],
            "dockerfiles": len(dockerfiles),
            "workflows": len(workflows),
        }
        any_tests = False
        for f in zig_files:
            text = f.read_text(encoding="utf-8", errors="replace")
            code = strip_zig(text)
            if f.name == "build.zig":
                self.check_build_zig(f, code, text)
            else:
                any_tests |= bool(re.search(r"^\s*test\b", code, re.M))
            self.check_zig_source(f, code)
        non_build = [f for f in zig_files if f.name != "build.zig"]
        if non_build and not any_tests:
            self.add("medium", "no-tests", ".", None,
                     "No `test` blocks found. Put unit tests next to the code and run them with `zig build test`.")
        for z in zons:
            self.check_zon(z, z.read_text(encoding="utf-8", errors="replace"))
        for d in dockerfiles:
            self.check_dockerfile(d, d.read_text(encoding="utf-8", errors="replace"))
        if workflows and not any("zig fmt --check" in w.read_text(encoding="utf-8", errors="replace")
                                 for w in workflows):
            self.add("low", "ci-no-fmt-check", ".github/workflows", None,
                     "CI never runs `zig fmt --check .`. Zig has no official linter, so fmt plus "
                     "`zig build test` in Debug and ReleaseSafe is the gate.")
        self.check_gitignore()

    # -- Zig sources ----------------------------------------------------------
    def check_zig_source(self, f: Path, code: str) -> None:
        lines = code.split("\n")
        in_test = test_line_mask(lines)
        has_main = bool(re.search(r"\bpub\s+fn\s+main\s*\(", code))
        for i, line in enumerate(lines, 1):
            for check, sev, rx, msg in REMOVED_API + DEPRECATED_API:
                if re.search(rx, line):
                    self.add(sev, check, f, i, msg)
            testing = in_test[i - 1]
            if re.search(r"\bcatch\s+unreachable\b", line) and not testing:
                self.add("medium", "catch-unreachable", f, i,
                         "`catch unreachable` turns a real error into a panic (Debug/ReleaseSafe) or undefined "
                         "behavior (ReleaseFast). Propagate with `try`, or handle the error.")
            if re.search(r"\bcatch\s*(\|[^|]*\|\s*)?\{\s*\}", line) and not re.search(r"\b(cancel|close|deinit|unlock|delete\w*|setColor)\s*\(", line):
                self.add("medium", "swallowed-error", f, i,
                         "Empty `catch {}` silently drops an error. Propagate it, log it, or comment why it is safe "
                         "(best-effort cleanup such as `cancel`/`close`/`delete*` is exempt).")
            if re.search(r"@setRuntimeSafety\s*\(\s*false\s*\)", line):
                self.add("medium", "runtime-safety-off", f, i,
                         "`@setRuntimeSafety(false)` removes bounds and overflow checks. Only in a measured hot loop, "
                         "with a comment and a test that covers the edge cases.")
            if re.match(r"^(pub\s+)?var\s+\w+\s*(:[^=]*)?=\s*(std\.heap\.)?\w*(Allocator|allocator)\b", line):
                self.add("medium", "global-allocator", f, i,
                         "Global mutable allocator. Construct it in `main` (or use `init.gpa`) and pass an "
                         "`std.mem.Allocator` parameter down; libraries never own a global allocator.")
            if testing and re.search(r"\bstd\.heap\.(page_allocator|c_allocator|smp_allocator)\b", line):
                self.add("medium", "test-without-leak-check", f, i,
                         "Tests should allocate with `std.testing.allocator`, which fails the test on leaks "
                         "(and `std.testing.checkAllAllocationFailures` for OOM paths).")
            elif re.search(r"\bstd\.heap\.page_allocator\b", line) and "ArenaAllocator" not in line:
                self.add("low", "page-allocator", f, i,
                         "`page_allocator` rounds every allocation up to a page and never caches. Use `init.gpa`, "
                         "or an `ArenaAllocator` on top of it.")
            if not has_main and not testing and re.search(r"\bstd\.debug\.print\s*\(", line):
                self.add("low", "debug-print-in-library", f, i,
                         "`std.debug.print` in library code writes to stderr unbuffered and cannot be redirected. "
                         "Take a `*std.Io.Writer` or use `std.log.scoped(...)`.")
            if re.search(r"\bpub\s+fn\s+\w+\s*\([^)]*\)\s*anyerror!", line):
                self.add("low", "anyerror-public", f, i,
                         "Public function returns `anyerror!`. Declare the error set (or let it be inferred) so "
                         "callers can switch on it exhaustively.")
            if re.search(r"\bstd\.Thread\.spawn\s*\(", line):
                self.add("low", "raw-thread-spawn", f, i,
                         "Prefer `io.concurrent(f, args)` or `std.Io.Group` so tasks integrate with the program's "
                         "Io implementation and cancelation.")
        if re.search(r"\bArenaAllocator\b[^;\n]*(\.init\s*\(|=\s*\.init\s*\()", code) and not re.search(r"\.deinit\s*\(\s*\)", code):
            self.add("medium", "arena-without-deinit", f, None,
                     "An `ArenaAllocator` is created but never `deinit()`ed in this file. Pair it with "
                     "`defer arena.deinit();` on the next line.")
        if re.search(r"\bFile\.Writer\b|\b(stdout|stderr)\(\)\.writer\s*\(", code) and ".flush()" not in code:
            self.add("medium", "missing-flush", f, None,
                     "A buffered `Io.File.Writer` is created but `flush()` is never called in this file, so output "
                     "can be lost. Call `try w.flush();` before returning.")

    # -- build.zig ------------------------------------------------------------
    def check_build_zig(self, f: Path, code: str, text: str) -> None:
        for m in re.finditer(r"\.add(StaticLibrary|SharedLibrary)\s*\(", code):
            self.add("high", "build-old-library-api", f, line_of(code, m.start()),
                     "`addStaticLibrary`/`addSharedLibrary` were removed. Use "
                     "`b.addLibrary(.{ .name = ..., .linkage = .static, .root_module = ... })`.")
        for m in re.finditer(r"\.add(Executable|Test|Library|Object|StaticLibrary|SharedLibrary)\s*\(\s*\.\{", code):
            opts = top_level_fields(code, m.end() - 1)
            if "root_source_file" in opts and "root_module" not in opts:
                self.add("high", "build-root-source-file", f, line_of(code, m.start()),
                         "`root_source_file`/`target`/`optimize` directly on add*() options were removed in 0.15. "
                         "Pass `.root_module = b.createModule(.{ .root_source_file = b.path(...), .target = target, "
                         ".optimize = optimize })`.")
        if not re.search(r'\.step\s*\(\s*"test"', text):
            self.add("medium", "build-no-test-step", f, None,
                     "No `test` step. Add `addTest(.{ .root_module = m })` + `addRunArtifact` for every module "
                     "with tests, under `b.step(\"test\", ...)`, so `zig build test` runs them all.")
        if "preferred_optimize_mode" in code:
            self.add("low", "build-preferred-optimize", f, None,
                     "`preferred_optimize_mode` removes the `-Doptimize` option (only `-Drelease` remains), which "
                     "surprises CI scripts. Prefer plain `b.standardOptimizeOption(.{})`.")

    # -- build.zig.zon --------------------------------------------------------
    def check_zon(self, f: Path, text: str) -> None:
        code = strip_zig(text)
        if not re.search(r"\.fingerprint\s*=", code):
            self.add("high", "zon-missing-fingerprint", f, None,
                     "build.zig.zon needs `.fingerprint` (0.14+); `zig build` refuses to run without it and prints "
                     "a suggested value. Never change it after publishing.")
        m = re.search(r"\.name\s*=\s*\"", text)
        if m:
            self.add("high", "zon-string-name", f, line_of(text, m.start()),
                     "`.name` must be an enum literal (`.name = .my_pkg,`), not a string, since 0.14.")
        mv = re.search(r"\.minimum_zig_version\s*=\s*\"(\d+)\.(\d+)", text)
        if not mv:
            self.add("low", "zon-no-min-version", f, None,
                     "Declare `.minimum_zig_version = \"0.16.0\"` so tools (setup-zig, ZLS) pick the right compiler.")
        elif (int(mv.group(1)), int(mv.group(2))) < (0, 16):
            self.add("low", "zon-old-min-version", f, line_of(text, mv.start()),
                     "minimum_zig_version is older than 0.16: std I/O, fs, net, and process APIs differ a lot. "
                     "Upgrade deliberately; don't mix 0.14/0.15 examples with 0.16 code.")
        for dm in re.finditer(r"\.(\w+|@\"[^\"]+\")\s*=\s*\.\{([^{}]*)\}", code):
            body = text[dm.start():dm.end()]
            url = re.search(r"\.url\s*=\s*\"([^\"]+)\"", body)
            if not url:
                continue
            if not re.search(r"\.hash\s*=", body):
                self.add("high", "zon-url-without-hash", f, line_of(text, dm.start()),
                         f"Dependency `{dm.group(1)}` has a url but no hash. Add it with `zig fetch --save <url>`, "
                         "which pins the content hash.")
            u = url.group(1)
            if re.search(r"refs/heads/|/archive/(main|master)\b|/tarball/(main|master)\b|/(main|master)\.tar", u) or \
                    (u.startswith("git+") and "#" not in u):
                self.add("medium", "zon-unpinned-url", f, line_of(text, dm.start()),
                         f"Dependency url points at a moving branch ({u}). Its hash breaks as soon as the branch "
                         "moves. Use a tag or commit tarball (or `git+https://...#<commit>`).")
        if not re.search(r"\.paths\s*=", code):
            self.add("low", "zon-no-paths", f, None,
                     "Add `.paths` (build.zig, build.zig.zon, src, LICENSE) so the package hash covers only real sources.")

    # -- Dockerfile -----------------------------------------------------------
    def check_dockerfile(self, f: Path, text: str) -> None:
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"(?<![\w./-])zig\s+build\b(?!\s+--fetch)", line):
                full = line
                j = i
                while full.rstrip().endswith("\\") and j < len(lines):
                    full += lines[j]
                    j += 1
                if "-Doptimize" not in full and "--release" not in full and "test" not in full.split():
                    self.add("high", "docker-debug-build", f, i,
                             "`zig build` without `-Doptimize=` ships a Debug binary (slow, huge). Services use "
                             "`-Doptimize=ReleaseSafe`.")
                if re.search(r"-Doptimize=ReleaseFast|--release=fast", full):
                    self.add("medium", "docker-release-fast", f, i,
                             "Services default to ReleaseSafe: it keeps bounds/overflow checks, so a bug crashes "
                             "loudly instead of corrupting memory. Use ReleaseFast only for measured hot paths.")
                if re.search(r"-linux-gnu\b", full) and re.search(r"(?m)^FROM\s+(scratch|\S*distroless/static)", text):
                    self.add("medium", "docker-glibc-static-image", f, i,
                             "A `-linux-gnu` target that links libc is dynamic and will not start on scratch or "
                             "distroless/static. Target `-linux-musl` for a static binary.")
        froms = [ln for ln in lines if re.match(r"^\s*FROM\s", ln, re.I)]
        if froms:
            last_from_idx = max(i for i, ln in enumerate(lines) if re.match(r"^\s*FROM\s", ln, re.I))
            runtime = "\n".join(lines[last_from_idx:])
            if not re.search(r"(?m)^\s*USER\s", runtime) and ":nonroot" not in froms[-1]:
                self.add("low", "docker-root-user", f, last_from_idx + 1,
                         "The runtime stage runs as root. Use `gcr.io/distroless/static-debian13:nonroot` or add "
                         "`USER 65532:65532`.")

    # -- .gitignore -----------------------------------------------------------
    def check_gitignore(self) -> None:
        gi = self.root / ".gitignore"
        if not gi.is_file():
            if self.facts.get("zig_files"):
                self.add("low", "gitignore-cache", ".gitignore", None,
                         "No .gitignore. Ignore `.zig-cache/`, `zig-out/`, and `zig-pkg/` (0.16 fetches packages "
                         "there).")
            return
        text = gi.read_text(encoding="utf-8", errors="replace")
        missing = [p for p in (".zig-cache", "zig-out") if p not in text]
        if missing:
            self.add("low", "gitignore-cache", ".gitignore", None,
                     f".gitignore is missing {', '.join(missing)} (the pre-0.13 name was `zig-cache`). "
                     "Also consider `zig-pkg/`, where 0.16 fetches dependencies.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def strip_zig(text: str) -> str:
    """Blank out comments, string/char literals, and multiline `\\\\` strings, keeping line numbers."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif c == "\\" and text.startswith("\\\\", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(c + " " * max(0, j - i - 2) + (c if j - i >= 2 else ""))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def test_line_mask(lines: list[str]) -> list[bool]:
    """True for lines inside a `test ... { }` block (brace-depth tracking on stripped code)."""
    mask = []
    depth = 0
    test_depth = None
    pending = False
    for line in lines:
        if test_depth is None and re.match(r"^\s*test\b", line):
            pending = True
        inside = pending or test_depth is not None
        for ch in line:
            if ch == "{":
                depth += 1
                if pending:
                    test_depth = depth
                    pending = False
            elif ch == "}":
                if test_depth is not None and depth == test_depth:
                    test_depth = None
                depth -= 1
        mask.append(inside)
    return mask


def top_level_fields(code: str, brace_idx: int) -> set[str]:
    """Field names at depth 1 of the `.{ ... }` literal starting at code[brace_idx] == '{'."""
    fields = set()
    depth = 0
    i = brace_idx
    while i < len(code):
        ch = code[i]
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
            if depth == 0:
                break
        elif ch == "." and depth == 1:
            m = re.match(r"\.(\w+)\s*=", code[i:])
            if m:
                fields.add(m.group(1))
        i += 1
    return fields


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def report(a: Auditor) -> str:
    out = [f"Zig audit: {a.root}", ""]
    f = a.facts
    out.append(f"  .zig files: {f.get('zig_files', 0)}   build.zig: {', '.join(f.get('build_zig', [])) or 'none'}   "
               f"manifests: {', '.join(f.get('manifests', [])) or 'none'}")
    out.append("")
    if not a.findings:
        out.append("No findings.")
        return "\n".join(out)
    for sev in SEVERITIES:
        items = [x for x in a.findings if x["severity"] == sev]
        if not items:
            continue
        out.append(f"{sev.upper()} ({len(items)})")
        for x in items:
            out.append(f"  [{x['check']}] {x['location']}")
            out.append(f"      {x['message']}")
        out.append("")
    counts = {s: sum(1 for x in a.findings if x["severity"] == s) for s in SEVERITIES}
    out.append("Summary: " + ", ".join(f"{counts[s]} {s}" for s in SEVERITIES))
    return "\n".join(out)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # exit 2 on bad input, per the documented contract
        self.print_usage(sys.stderr)
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(2)


def main(argv: list[str]) -> int:
    p = Parser(prog="audit.py", description=__doc__.split("\n\n")[0],
               formatter_class=argparse.RawDescriptionHelpFormatter,
               epilog="Examples:\n  python3 scripts/audit.py .\n  python3 scripts/audit.py ~/code/app --json "
                      "--fail-on medium\n\nExit codes: 0 ok, 1 findings at/above --fail-on, 2 bad input.")
    p.add_argument("root", nargs="?", default=".", help="project root (default: .)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--fail-on", default="high", choices=["high", "medium", "low", "none"],
                   help="lowest severity that makes the exit code 1 (default: high)")
    args = p.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: '{args.root}' is not a directory.", file=sys.stderr)
        return 2
    a = Auditor(root)
    a.run()
    print(json.dumps({"facts": a.facts, "findings": a.findings}, indent=2) if args.json else report(a))
    if args.fail_on == "none":
        return 0
    limit = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(x["severity"]) <= limit for x in a.findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
