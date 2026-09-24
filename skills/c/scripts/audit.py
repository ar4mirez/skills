#!/usr/bin/env python3
"""Static audit of a C project for memory-safety, API-misuse, and build-hygiene
anti-patterns. Heuristic (regex + light parsing), no compiler needed, no network.

Usage:
  python3 scripts/audit.py [ROOT] [--json] [--fail-on high|medium|low|none]

Checks (severity):
  high    gets(); strcpy/strcat/sprintf/vsprintf/stpcpy/wcscpy/wcscat; scanf "%s" or "%["
          without a width; non-literal format strings (printf(buf)); p = realloc(p, ...);
          cmake_minimum_required below 3.5 (CMake 4 refuses to configure)
  medium  malloc/calloc/realloc/strdup result not checked for NULL within a few lines;
          allocation sizes multiplied without an overflow check; atoi/atol/atof;
          system()/popen(); volatile used as a synchronization flag; void main();
          alloca(); side effects inside assert(); headers without an include guard or
          #pragma once; global CMake flags (CMAKE_C_FLAGS, add_compile_options,
          include_directories, link_libraries, add_definitions); no -Wall/-Wextra;
          no hardening flags (_FORTIFY_SOURCE, -fstack-protector-strong); no tests
          registered with CTest; no sanitizer configuration
  low     strncpy; strtok; rand()/srand(); strto* without errno = 0 in the file; strlen() in
          a loop condition; <threads.h> (missing on macOS); empty parameter lists in headers;
          hard-coded -Werror; -z linker flags or -fcf-protection with no platform/flag probe;
          _FORTIFY_SOURCE without -U_FORTIFY_SOURCE; no C standard set; cmake below 3.21
          (no C_STANDARD 23); file(GLOB) sources; no CMakePresets.json; no CMakeLists.txt;
          Dockerfile runtime stage that is a full distro or runs as root

Suppress one line with a trailing comment containing `audit:ignore` (optionally
`audit:ignore=check-id`). Skips build/, .git/, and vendored dirs (third_party, vendor,
external, _deps, deps).

Exit codes: 0 = no findings at/above --fail-on (default: high), 1 = findings, 2 = bad input.
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ("high", "medium", "low")
SKIP_DIRS = {".git", "build", "cmake-build-debug", "cmake-build-release", "out", "third_party",
             "vendor", "external", "_deps", "deps", "node_modules", ".cache"}
C_EXTS = {".c", ".h"}


class Audit:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[dict] = []

    def add(self, severity: str, check: str, path: Path | None, line: int | None, message: str,
            raw_lines: list[str] | None = None) -> None:
        if raw_lines is not None and line is not None and 0 < line <= len(raw_lines):
            m = re.search(r"audit:ignore(?:=([\w,-]+))?", raw_lines[line - 1])
            if m and (not m.group(1) or check in m.group(1).split(",")):
                return
        loc = "." if path is None else path.relative_to(self.root).as_posix()
        if line:
            loc += f":{line}"
        self.findings.append({"severity": severity, "check": check, "location": loc,
                              "message": message})


# ---- C source preprocessing -------------------------------------------------------------

def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, keep string/char literals and newlines."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("\n" * src.count("\n", i, j))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def blank_strings(code: str) -> str:
    """Replace string and char literal contents with nothing (keep the quotes)."""
    return re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'',
                  lambda m: m.group(0)[0] * 2, code)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def call_args(text: str, open_paren: int) -> str:
    """Return the text between the parenthesis at open_paren and its match."""
    depth = 0
    for j in range(open_paren, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:j]
    return text[open_paren + 1:]


def split_top_level(args: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in args:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def unchecked_multiplication(expr: str) -> bool:
    """True when expr multiplies by something that isn't a compile-time constant."""
    e = re.sub(r"\bsizeof\s*\((?:[^()]|\([^()]*\))*\)", " S ", expr)
    e = re.sub(r"\bsizeof\s+\**\s*[A-Za-z_][\w.>\-\[\]]*", " S ", e)
    if not re.search(r"[\w)\]]\s*\*\s*[\w(]", e):  # a binary *, not a dereference
        return False
    idents = [t for t in re.findall(r"[A-Za-z_]\w*", e) if t != "S" and not t.isupper()
              and not re.fullmatch(r"[uUlL]+", t)]
    return bool(idents)


BANNED = {
    "gets": ("high", "gets", "gets() cannot bound its input and was removed in C11; use fgets()"),
    "strcpy": ("high", "unbounded-string-fn", "strcpy() has no bound; use snprintf() or memcpy() "
               "with a checked length"),
    "strcat": ("high", "unbounded-string-fn", "strcat() has no bound; build strings with "
               "snprintf() and check its return"),
    "stpcpy": ("high", "unbounded-string-fn", "stpcpy() has no bound; use memcpy() with a checked "
               "length"),
    "wcscpy": ("high", "unbounded-string-fn", "wcscpy() has no bound"),
    "wcscat": ("high", "unbounded-string-fn", "wcscat() has no bound"),
    "sprintf": ("high", "unbounded-string-fn", "sprintf() has no bound; use snprintf() and check "
                "the return value for truncation"),
    "vsprintf": ("high", "unbounded-string-fn", "vsprintf() has no bound; use vsnprintf()"),
    "atoi": ("medium", "atoi-family", "atoi() can't report errors and overflow is undefined; use "
             "strtol() with errno = 0 and an end-pointer check"),
    "atol": ("medium", "atoi-family", "atol() can't report errors; use strtol()"),
    "atoll": ("medium", "atoi-family", "atoll() can't report errors; use strtoll()"),
    "atof": ("medium", "atoi-family", "atof() can't report errors; use strtod()"),
    "system": ("medium", "shell-exec", "system() runs a shell: injection risk; use posix_spawn() or "
               "fork/exec with an argv array"),
    "popen": ("medium", "shell-exec", "popen() runs a shell: injection risk; use posix_spawn() "
              "with pipes"),
    "alloca": ("medium", "alloca", "alloca() has no failure mode and can overflow the stack; use a "
               "fixed buffer or the heap"),
    "strncpy": ("low", "strncpy", "strncpy() doesn't NUL-terminate on truncation and pads with "
                "zeros; use snprintf() or memcpy() with an explicit terminator"),
    "strtok": ("low", "strtok", "strtok() keeps hidden global state (not thread-safe); use "
               "strtok_r() or parse with memchr()"),
    "rand": ("low", "rand", "rand() is weak and not for secrets; use getrandom()/arc4random() for "
             "security, or a local PRNG for simulations"),
    "srand": ("low", "rand", "srand()/rand() are global and weak; see rand"),
}
BANNED_RE = re.compile(r"(?<![\w.>])(" + "|".join(BANNED) + r")\s*\(")
ALLOC_ASSIGN_RE = re.compile(
    r"([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*=\s*(?:\([^()]*\)\s*)?"
    r"(malloc|calloc|realloc|strdup|strndup|aligned_alloc|reallocarray)\s*\(")


def audit_c_file(a: Audit, path: Path) -> None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw_lines = raw.splitlines()
    code = strip_comments(raw)          # strings intact
    bare = blank_strings(code)          # strings emptied

    def add(sev, check, pos, msg, text=None):
        a.add(sev, check, path, line_of(bare if text is None else text, pos), msg, raw_lines)

    for m in BANNED_RE.finditer(bare):
        name = m.group(1)
        # skip declarations/definitions of a same-named function, e.g. "static int system(".
        before = bare[max(0, m.start() - 40):m.start()]
        if re.search(r"\b(int|void|char|long|double|static|extern)\s*\**\s*$", before):
            continue
        sev, check, msg = BANNED[name]
        add(sev, check, m.start(), f"{name}(): {msg}")

    for m in re.finditer(r"(?<![\w.>])(v?f?scanf|v?sscanf)\s*\(", code):
        args = call_args(code, m.end() - 1)
        fmt = re.search(r'"((?:\\.|[^"\\])*)"', args)
        if fmt and re.search(r"%(?:\*)?(?:[hljztL]*)(?:s|\[)", fmt.group(1)):
            add("high", "scanf-unbounded", m.start(),
                f"{m.group(1)}() with %s or %[ and no field width overflows the buffer; add a "
                "width (%63s) or read with fgets()", code)

    fmt_pos = {"printf": 0, "vprintf": 0, "fprintf": 1, "vfprintf": 1, "dprintf": 1,
               "syslog": 1, "snprintf": 2, "vsnprintf": 2, "err": 1, "warn": 0}
    for m in re.finditer(r"(?<![\w.>])(" + "|".join(fmt_pos) + r")\s*\(", code):
        args = split_top_level(call_args(code, m.end() - 1))
        idx = fmt_pos[m.group(1)]
        if len(args) == idx + 1:  # the format is the last argument: nothing to format
            f = args[idx]
            if f and not f.startswith('"') and re.fullmatch(r"[A-Za-z_][\w.\->\[\]]*", f) \
                    and not f.isupper():
                add("high", "format-nonliteral", m.start(),
                    f"{m.group(1)}() with a non-literal format ({f}) is a format-string "
                    f'vulnerability; use {m.group(1)}(..."%s", {f})', code)

    for m in re.finditer(r"([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*=\s*realloc\s*\(\s*"
                         r"([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*,", bare):
        if m.group(1) == m.group(2):
            add("high", "realloc-self-assign", m.start(),
                f"{m.group(1)} = realloc({m.group(1)}, ...) leaks the old block when realloc "
                "fails; assign to a temporary, check it, then replace")

    for m in ALLOC_ASSIGN_RE.finditer(bare):
        var = m.group(1)
        if bare[m.end(1):m.start(2)].lstrip().startswith("=="):
            continue
        window = bare[m.end():m.end() + 600]
        window = "\n".join(window.split("\n")[:6])
        v = re.escape(var)
        stmt_end = window.find(";")
        next_stmt = window[stmt_end + 1:].lstrip() if stmt_end >= 0 else ""
        checked = re.match(rf"return\s+{v}\s*;", next_stmt) or re.search(
            rf"!\s*\(?\s*{v}\b|\b{v}\s*[!=]=\s*(?:NULL|nullptr|0)\b|(?:NULL|nullptr)\s*[!=]=\s*{v}\b"
            rf"|\bif\s*\(\s*{v}\s*\)|\b{v}\s*\?", window)
        if not checked:
            add("medium", "unchecked-alloc", m.start(),
                f"{var} = {m.group(2)}(...) is used without a NULL check; check it right away "
                "and return an error code")

    for m in re.finditer(r"(?<![\w.>])(malloc|realloc|reallocarray|aligned_alloc)\s*\(", bare):
        args = split_top_level(call_args(bare, m.end() - 1))
        size_arg = {"malloc": 0, "realloc": 1, "aligned_alloc": 1}.get(m.group(1))
        if size_arg is None or len(args) <= size_arg:
            continue
        if unchecked_multiplication(args[size_arg]):
            add("medium", "alloc-size-overflow", m.start(),
                f"{m.group(1)}({args[size_arg]}): the multiplication can wrap and under-allocate; "
                "use calloc(n, size) or ckd_mul() from <stdckdint.h> first")

    for m in re.finditer(r"\bvolatile\b", bare):
        after = bare[m.end():m.end() + 30]
        before = bare[max(0, m.start() - 12):m.start()]
        if re.match(r"\s*sig_atomic_t\b", after) or re.search(r"(asm|__asm__)\s*$", before):
            continue
        add("medium", "volatile-sync", m.start(),
            "volatile is not a synchronization primitive (no atomicity, no ordering); use "
            "<stdatomic.h> for thread flags, volatile sig_atomic_t for signal flags. Ignore for "
            "memory-mapped I/O")

    for m in re.finditer(r"\bvoid\s+main\s*\(", bare):
        add("medium", "void-main", m.start(), "main must return int")

    for m in re.finditer(r"(?<![\w.>])assert\s*\(", bare):
        arg = call_args(bare, m.end() - 1)
        if re.search(r"\+\+|--|(?<![=!<>])=(?!=)", arg) or \
                re.search(r"\b(malloc|calloc|fopen|open|read|write|close|free)\s*\(", arg):
            add("medium", "assert-side-effect", m.start(),
                "assert() with a side effect: NDEBUG (every CMake Release build) removes the "
                "whole expression; do the work first, then assert on the result")

    if re.search(r"(?<![\w.>])strto(?:l|ul|ll|ull|imax|umax|d|f|ld)\s*\(", bare) and \
            not re.search(r"\berrno\s*=\s*0\b", bare):
        m = re.search(r"(?<![\w.>])strto(?:l|ul|ll|ull|imax|umax|d|f|ld)\s*\(", bare)
        add("low", "strto-without-errno", m.start(),
            "strto*() reports overflow only through errno: set errno = 0 before the call and "
            "check errno, the end pointer, and the range after it")

    for m in re.finditer(r"\b(?:for|while)\s*\(", bare):
        head = call_args(bare, m.end() - 1)
        cond = head.split(";")[1] if head.count(";") >= 2 else head
        if re.search(r"\bstrlen\s*\(", cond):
            add("low", "strlen-in-loop", m.start(),
                "strlen() in a loop condition rescans the string every iteration (O(n^2)); "
                "compute the length once")

    for m in re.finditer(r"#\s*include\s*<threads\.h>", bare):
        add("low", "c11-threads", m.start(),
            "<threads.h> is missing on macOS and some libcs; use pthreads on POSIX (C11 threads "
            "only for glibc/musl/MSVC-only code)")

    if path.suffix == ".h":
        first = re.search(r"^\s*#\s*(\w+)\s*(\S*)", bare, re.M)
        guarded = bool(re.search(r"^\s*#\s*pragma\s+once\b", bare, re.M))
        if not guarded and first and first.group(1) in ("ifndef",) :
            guarded = bool(re.search(rf"^\s*#\s*define\s+{re.escape(first.group(2))}\b", bare, re.M))
        if not guarded and first and first.group(1) == "if" and "defined" in bare[first.start():first.start() + 80]:
            guarded = True
        if not guarded and bare.strip():
            a.add("medium", "missing-include-guard", path, 1,
                  "header has no include guard or #pragma once; double inclusion redefines types",
                  raw_lines)
        for m in re.finditer(r"^[ \t]*(?:extern\s+)?[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\(\s*\)\s*;",
                             bare, re.M):
            add("low", "empty-param-list", m.start(),
                f"{m.group(1)}(): an empty parameter list is unprototyped before C23; write "
                "(void) so C11/C17 consumers get type checking")


# ---- CMake, presets, Docker --------------------------------------------------------------

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def audit_cmake(a: Audit, root: Path, cmake_files: list[Path]) -> None:
    top = root / "CMakeLists.txt"
    if not top.is_file():
        if not (root / "meson.build").is_file():
            a.add("low", "no-cmake", None, None,
                  "no CMakeLists.txt (or meson.build): use CMake with presets so every developer "
                  "and CI job builds the same way")
        return

    texts = {}
    for f in cmake_files:
        t = re.sub(r"#[^\n]*", "", read(f))  # drop CMake comments
        texts[f] = t
    everything = "\n".join(texts.values())
    presets = root / "CMakePresets.json"
    preset_text = read(presets) if presets.is_file() else ""
    both = everything + "\n" + preset_text

    top_text = texts.get(top, "")
    m = re.search(r"cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)", top_text, re.I)
    if m:
        v = version_tuple(m.group(1))
        line = line_of(top_text, m.start())
        if v < (3, 5):
            a.add("high", "cmake-min-too-old", top, line,
                  f"cmake_minimum_required({m.group(1)}): CMake 4 refuses anything below 3.5; "
                  "use VERSION 3.25...4.4")
        elif v < (3, 21):
            a.add("low", "cmake-min-old", top, line,
                  f"cmake_minimum_required({m.group(1)}): C_STANDARD 23 needs 3.21 and presets "
                  "v6 need 3.25; use VERSION 3.25...4.4")

    global_re = re.compile(
        r"^\s*(set\s*\(\s*CMAKE_C_FLAGS\w*|string\s*\(\s*APPEND\s+CMAKE_C_FLAGS\w*|"
        r"add_compile_options|add_definitions|add_compile_definitions|include_directories|"
        r"link_libraries|link_directories|add_link_options)\b", re.I | re.M)
    for f, t in texts.items():
        for g in global_re.finditer(t):
            a.add("medium", "global-cmake-flags", f, line_of(t, g.start()),
                  f"{g.group(1).split('(')[0].strip()}(...) applies to every target, including "
                  "dependencies; use target_compile_options/target_include_directories/"
                  "target_link_libraries on an INTERFACE policy target")
        for g in re.finditer(r"file\s*\(\s*GLOB(?:_RECURSE)?\b", t, re.I):
            a.add("low", "glob-sources", f, line_of(t, g.start()),
                  "file(GLOB) misses new files until re-configure; list sources explicitly")
        for g in re.finditer(r"(?<![\w=-])-Werror(?![=\w-])", t):
            line_text = t[t.rfind("\n", 0, g.start()) + 1:t.find("\n", g.start())]
            if "CMAKE_REQUIRED_FLAGS" in line_text:  # probing flags under -Werror is correct
                continue
            a.add("low", "hardcoded-werror", f, line_of(t, g.start()),
                  "-Werror in CMakeLists breaks builds on the next compiler release; set "
                  "CMAKE_COMPILE_WARNING_AS_ERROR in a CI preset instead")

    if "-Wall" not in both:
        a.add("medium", "no-warnings", top, None,
              "no -Wall anywhere in the build: enable -Wall -Wextra -Wpedantic -Wconversion "
              "-Wshadow -Wformat=2 -Wimplicit-fallthrough on a warnings target")
    else:
        missing = [w for w in ("-Wextra", "-Wconversion", "-Wshadow", "-Wformat=2",
                               "-Wimplicit-fallthrough") if w not in both]
        if "-Wextra" in missing:
            a.add("medium", "weak-warnings", top, None, "-Wall without -Wextra misses many bugs")
            missing.remove("-Wextra")
        if missing:
            a.add("low", "weak-warnings", top, None, "missing warnings: " + " ".join(missing))

    if "_FORTIFY_SOURCE" not in both or "-fstack-protector" not in both:
        miss = [f for f in ("-D_FORTIFY_SOURCE=3", "-fstack-protector-strong")
                if f.split("=")[0].lstrip("-D") not in both and f not in both]
        a.add("medium", "no-hardening", top, None,
              "release builds lack OpenSSF hardening (" + ", ".join(miss or ["some flags"]) +
              "); add -D_FORTIFY_SOURCE=3, -fstack-protector-strong, -fstack-clash-protection, "
              "PIE and RELRO, probed with check_c_compiler_flag/check_linker_flag")
    elif "_FORTIFY_SOURCE" in both and "-U_FORTIFY_SOURCE" not in both:
        a.add("low", "fortify-no-undef", top, None,
              "distro compilers often predefine _FORTIFY_SOURCE; prepend -U_FORTIFY_SOURCE to "
              "avoid redefinition warnings and get level 3")

    probed = re.search(r"check_linker_flag|PLATFORM_ID|CMAKE_SYSTEM_NAME|\bLINUX\b|\bAPPLE\b",
                       everything)
    if re.search(r"-z,(relro|now|noexecstack)", everything) and not probed:
        a.add("low", "unguarded-linker-flags", top, None,
              "-Wl,-z,... flags break linking on macOS (ld64); probe them with check_linker_flag() "
              "or guard with $<PLATFORM_ID:Linux>")
    if re.search(r"-fcf-protection|-mbranch-protection", everything) and not re.search(
            r"check_c_compiler_flag|CMAKE_SYSTEM_PROCESSOR", everything):
        a.add("low", "unguarded-arch-flags", top, None,
              "-fcf-protection is x86-only and -mbranch-protection AArch64-only; probe with "
              "check_c_compiler_flag() (under -Werror)")

    if not re.search(r"C_STANDARD|c_std_\d+|-std=", both):
        a.add("low", "no-c-standard", top, None,
              "no C standard set; the compiler default differs (GCC 15: gnu23, Clang: gnu17). "
              "Set C_STANDARD 23, C_STANDARD_REQUIRED ON, C_EXTENSIONS OFF on targets")
    if not re.search(r"\badd_test\s*\(|include\s*\(\s*CTest\s*\)|enable_testing", everything, re.I):
        a.add("medium", "no-tests", top, None,
              "no tests registered with CTest (enable_testing() + add_test())")
    if not presets.is_file():
        a.add("low", "no-presets", None, None,
              "no CMakePresets.json: add dev, asan, and release presets so local and CI builds match")
    if "-fsanitize=address" not in both and "-fsanitize=address,undefined" not in both:
        a.add("medium", "no-sanitizers", top, None,
              "no AddressSanitizer/UBSan configuration: add an asan preset and run the tests under it")


def audit_docker(a: Audit, root: Path, dockerfiles: list[Path]) -> None:
    for f in dockerfiles:
        t = read(f)
        froms = [m for m in re.finditer(r"^\s*FROM\s+(\S+)", t, re.M | re.I)]
        if not froms:
            continue
        last = froms[-1]
        image = last.group(1).lower()
        tail = t[last.start():]
        line = line_of(t, last.start())
        if re.match(r"(docker\.io/)?(library/)?(ubuntu|debian|fedora|centos|gcc|buildpack-deps)"
                    r"(:|$)", image):
            a.add("low", "docker-heavy-runtime", f, line,
                  f"runtime stage is {image}: ship the (static) binary on "
                  "gcr.io/distroless/static-debian13:nonroot or scratch")
        nonroot = "nonroot" in image or re.search(r"^\s*USER\s+(?!root\b|0\b)\S+", tail, re.M | re.I)
        if not nonroot and image != "scratch":
            a.add("low", "docker-root", f, line,
                  "runtime stage runs as root; use a :nonroot distroless image or a USER line")


def walk(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_dir():
                if e.name not in SKIP_DIRS and not e.name.startswith("build"):
                    stack.append(e)
            elif e.is_file():
                yield e


def run(root: Path) -> Audit:
    a = Audit(root)
    cmake_files, dockerfiles = [], []
    for f in walk(root):
        if f.suffix in C_EXTS:
            audit_c_file(a, f)
        elif f.name == "CMakeLists.txt" or f.suffix == ".cmake":
            cmake_files.append(f)
        elif f.name == "Dockerfile" or f.name.startswith("Dockerfile.") or f.suffix == ".dockerfile":
            dockerfiles.append(f)
    audit_cmake(a, root, cmake_files)
    audit_docker(a, root, dockerfiles)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    a.findings.sort(key=lambda x: (order[x["severity"]], x["location"], x["check"]))
    return a


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Static audit of a C project (unsafe APIs, memory handling, CMake hygiene).",
        epilog="Exit codes: 0 no findings at/above --fail-on, 1 findings, 2 bad input.")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fail-on", default="high", help="high|medium|low|none (default: high)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if args.fail_on not in (*SEVERITIES, "none"):
        print(f"audit: --fail-on must be high, medium, low, or none (got {args.fail_on!r})",
              file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"audit: {args.root} is not a directory", file=sys.stderr)
        return 2

    a = run(root)
    summary = {s: sum(1 for f in a.findings if f["severity"] == s) for s in SEVERITIES}
    if args.json:
        print(json.dumps({"root": str(root), "summary": summary, "findings": a.findings}, indent=2))
    else:
        if not a.findings:
            print(f"audit: {root}: no findings")
        for f in a.findings:
            print(f"[{f['severity']:<6}] {f['check']:<24} {f['location']}\n         {f['message']}")
        if a.findings:
            print(f"\n{summary['high']} high, {summary['medium']} medium, {summary['low']} low")
    if args.fail_on == "none":
        return 0
    threshold = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(f["severity"]) <= threshold for f in a.findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
