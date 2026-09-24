#!/usr/bin/env python3
"""Static health check of a modern C++ / CMake project. No build, no network, stdlib only.

Usage:
  python3 scripts/audit.py [ROOT] [--json] [--fail-on high|medium|low|none]

high    naked new/delete; raw owning pointer members; polymorphic class without a
        virtual (or protected) destructor; `using namespace std` in a header;
        <bits/stdc++.h>; std::auto_ptr; unsafe C string functions (gets, strcpy,
        strcat, sprintf); no C++ standard set in CMake; cmake_minimum_required < 3.5
        (a hard error in CMake 4)
medium  C-style casts; malloc/free; std::string_view bound to a temporary; manual
        mutex lock()/unlock(); std::thread::detach(); volatile used as a flag;
        global CMake flags (add_compile_options, include_directories,
        CMAKE_CXX_FLAGS, ...) instead of target_*; compiler extensions on or not
        disabled; no warning flags; no CMakePresets.json; -ffast-math; vcpkg.json
        without a baseline
low     std::endl inside a loop; NULL instead of nullptr; `using namespace std` in a
        source file; header without #pragma once or include guard; std::thread
        (prefer std::jthread); C++ standard below 20; file(GLOB) sources;
        unconditional -Werror in CMake; CMAKE_BUILD_TYPE hard-coded; no sanitizer
        configuration; final Docker stage is a full compiler/OS image

Suppress one line with a trailing `// NOLINT` or `// cpp-audit: ignore`.
Skipped directories: build*, cmake-build-*, out, .git, _deps, vcpkg_installed,
third_party, external, vendor, node_modules.

Exit codes: 0 = no findings at/above --fail-on (default: high), 1 = findings, 2 = bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SEVERITIES = ("high", "medium", "low")
CXX_SOURCE = {".cpp", ".cc", ".cxx", ".c++", ".cppm", ".ixx"}
CXX_HEADER = {".h", ".hpp", ".hh", ".hxx", ".h++", ".ipp", ".inl"}
SKIP_DIRS = {".git", "out", "_deps", "vcpkg_installed", "third_party", "external", "vendor",
             "node_modules", ".cache", "__pycache__"}
SUPPRESS = re.compile(r"//\s*(NOLINT|cpp-audit:\s*ignore)")


@dataclass
class Finding:
    severity: str
    check: str
    location: str
    message: str


# --------------------------------------------------------------------------- helpers

def strip_code(src: str) -> str:
    """Blank out comments and string/char literals, keeping offsets and newlines."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
        elif c == "R" and src.startswith('R"', i) and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            m = re.match(r'R"([^(\s]{0,16})\(', src[i:])
            if not m:
                i += 1
                continue
            end = src.find(")" + m.group(1) + '"', i + m.end())
            j = n if end == -1 else end + len(m.group(1)) + 2
            blank(i + 2, j - 1)
            i = j
        elif c in "\"'":
            # a ' between digits is a digit separator (1'000'000), not a char literal
            if c == "'" and i > 0 and src[i - 1].isalnum() and i + 1 < n and src[i + 1].isalnum():
                i += 1
                continue
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
        else:
            i += 1
    return "".join(out)


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def matching_brace(code: str, open_index: int) -> int:
    depth = 0
    for k in range(open_index, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(code)


def top_level(body: str) -> str:
    """Blank everything nested deeper than the outer braces (nested classes, function bodies)."""
    out, depth = [], 0
    for ch in body:
        if ch == "{":
            depth += 1
            out.append(ch if depth <= 1 else " ")
        elif ch == "}":
            out.append(ch if depth <= 1 else " ")
            depth -= 1
        else:
            out.append(ch if depth <= 1 or ch == "\n" else " ")
    return "".join(out)


def walk(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                name = p.name
                if name in SKIP_DIRS or name.startswith(("build", "cmake-build-")):
                    continue
                stack.append(p)
            elif p.is_file():
                yield p


# --------------------------------------------------------------------------- C++ checks

NAKED_NEW = re.compile(r"(?<![\w.>:])new\s+(?!\()[A-Za-z_:][\w:<>, ]*\s*[\[({;]")
NAKED_DELETE = re.compile(r"\bdelete\b\s*(\[\s*\])?\s*[A-Za-z_(*]")
DELETED_FN = re.compile(r"=\s*delete\b")
C_CAST = re.compile(
    r"(?<![\w)\]>])\(\s*(?:const\s+)?(?:unsigned\s+|signed\s+)?"
    r"(int|long|short|char|float|double|bool|size_t|std::size_t|ssize_t|u?int(?:8|16|32|64)_t|"
    r"std::u?int(?:8|16|32|64)_t|uintptr_t|std::uintptr_t|void\s*\*|[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*\s*\*+)"
    r"\s*(?:const\s*)?\)\s*(?=[\w(&*])")
MALLOC = re.compile(r"(?<![\w.:>])(malloc|calloc|realloc|free)\s*\(")
UNSAFE_C = re.compile(r"(?<![\w.:>])(gets|strcpy|strcat|sprintf|vsprintf)\s*\(")
USING_STD = re.compile(r"^\s*using\s+namespace\s+std\s*;", re.M)
BITS = re.compile(r"#\s*include\s*<bits/stdc\+\+\.h>")
AUTO_PTR = re.compile(r"\bstd::auto_ptr\b")
NULL_MACRO = re.compile(r"(?<![\w])NULL(?![\w])")
DETACH = re.compile(r"\.\s*detach\s*\(\s*\)")
STD_THREAD = re.compile(r"\bstd::thread\b(?!::)")
VOLATILE = re.compile(r"\bvolatile\s+(bool|int|std::atomic)")
MANUAL_LOCK = re.compile(r"(?<![\w>])(\w*(?:mutex|mtx)\w*)\s*(\.|->)\s*(lock|unlock)\s*\(\s*\)\s*;", re.I)
SV_TEMP = re.compile(r"\bstring_view\s+\w+\s*[={]\s*(?:std::string\s*[({]|[^;]*\+\s*[\w\"(])")
CLASS_HEAD = re.compile(r"\b(class|struct)\s+(?:\[\[[^\]]*\]\]\s*)?(?:alignas\([^)]*\)\s*)?([A-Za-z_]\w*)\s*(final\b)?\s*(?::[^;{]*)?\{")
PTR_MEMBER = re.compile(r"^\s*(?:const\s+)?(?:[\w:<>]+\s*)\*+\s*(\w+)\s*(?:=\s*nullptr\s*)?;", re.M)
VIEW_FN = re.compile(r"\b(?:std::)?(?:string_view|span<[^>]*>)\s+[\w:]+\s*\([^)]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{")
LOOP_HEAD = re.compile(r"\b(for|while)\s*\(|\bdo\s*$")
GUARD = re.compile(r"^\s*#\s*(pragma\s+once|ifndef\s+\w+)", re.M)


def check_cxx(path: Path, rel: str, raw: str, findings: list[Finding], owners: dict) -> None:
    code = strip_code(raw)
    raw_lines = raw.splitlines()
    is_header = path.suffix.lower() in CXX_HEADER

    def add(sev: str, check: str, index: int, msg: str) -> None:
        ln = line_of(code, index)
        if ln - 1 < len(raw_lines) and SUPPRESS.search(raw_lines[ln - 1]):
            return
        findings.append(Finding(sev, check, f"{rel}:{ln}", msg))

    for m in NAKED_NEW.finditer(code):
        add("high", "naked-new", m.start(), "naked `new`: use std::make_unique / a container / a value (RAII)")
    for m in NAKED_DELETE.finditer(code):
        prefix = code[max(0, m.start() - 12):m.start() + 1]
        if DELETED_FN.search(prefix + code[m.start():m.end()]) or "operator" in prefix:
            continue
        add("high", "naked-delete", m.start(), "naked `delete`: ownership belongs in a unique_ptr or container")
    for m in UNSAFE_C.finditer(code):
        add("high", "unsafe-c-string", m.start(), f"`{m.group(1)}` has no bounds: use std::string / std::format / std::span")
    for m in BITS.finditer(raw):
        add("high", "bits-stdc++", m.start(), "<bits/stdc++.h> is a non-portable libstdc++ internal; include what you use")
    for m in AUTO_PTR.finditer(code):
        add("high", "auto-ptr", m.start(), "std::auto_ptr was removed in C++17: use std::unique_ptr")
    for m in USING_STD.finditer(code):
        if is_header:
            add("high", "using-namespace-std-header", m.start(),
                "`using namespace std` in a header leaks into every includer: qualify names")
        else:
            add("low", "using-namespace-std", m.start(), "`using namespace std` invites ADL/name clashes: qualify or use targeted using-declarations")
    for m in C_CAST.finditer(code):
        inner = code[m.start():m.end()]
        if re.fullmatch(r"\(\s*void\s*\)\s*", inner):
            continue
        add("medium", "c-style-cast", m.start(), f"C-style cast `{inner.strip()}`: use static_cast / std::bit_cast (or a named cast that shows intent)")
    for m in MALLOC.finditer(code):
        add("medium", "malloc-free", m.start(), f"`{m.group(1)}` in C++: use containers / std::make_unique; at C boundaries wrap in unique_ptr with a deleter")
    for m in SV_TEMP.finditer(code):
        add("medium", "dangling-string-view", m.start(), "std::string_view bound to a temporary std::string: it dangles at the end of the statement")
    for m in DETACH.finditer(code):
        add("medium", "thread-detach", m.start(), "detached threads outlive their data and can't be stopped: use std::jthread + stop_token")
    for m in VOLATILE.finditer(code):
        add("medium", "volatile-sync", m.start(), "volatile is not synchronization: use std::atomic")
    for m in MANUAL_LOCK.finditer(code):
        add("medium", "manual-lock", m.start(), f"manual `{m.group(3)}()`: use std::scoped_lock / std::unique_lock so exceptions can't leak the lock")
    for m in STD_THREAD.finditer(code):
        add("low", "std-thread", m.start(), "std::thread terminates if not joined: prefer std::jthread (joins, supports stop_token)")
    for m in NULL_MACRO.finditer(code):
        add("low", "null-macro", m.start(), "use nullptr, not NULL")

    # Classes: virtual functions without a virtual destructor; raw owning pointer members.
    for m in CLASS_HEAD.finditer(code):
        name, is_final = m.group(2), bool(m.group(3))
        open_i = m.end() - 1
        body = top_level(code[open_i:matching_brace(code, open_i) + 1])
        has_base = code[m.start():open_i].find(":") != -1
        has_virtual = re.search(r"\bvirtual\b(?!\s*~)", body) is not None
        dtor = re.search(r"(virtual\s+)?~\s*" + re.escape(name) + r"\s*\([^)]*\)\s*(override|final)?", body)
        # A derived class without its own destructor inherits the base's (possibly virtual) one.
        if has_virtual and not is_final and (dtor or not has_base):
            ok = False
            if dtor and (dtor.group(1) or dtor.group(2)):
                ok = True
            elif dtor:
                labels = list(re.finditer(r"\b(public|protected|private)\s*:", body[:dtor.start()]))
                ok = bool(labels) and labels[-1].group(1) == "protected"
            if not ok:
                add("high", "missing-virtual-dtor", m.start(),
                    f"`{name}` has virtual functions but no virtual (or protected) destructor: deleting through a base pointer is UB")
        for pm in PTR_MEMBER.finditer(body):
            ln = line_of(code, open_i + pm.start(1))
            if not SUPPRESS.search(raw_lines[ln - 1] if ln - 1 < len(raw_lines) else ""):
                owners["members"].append((name, pm.group(1), f"{rel}:{ln}"))

    # Names released by hand anywhere in the project (members may be deleted in another file).
    owners["released"].update(m.group(2) for m in re.finditer(r"(\bdelete\s*(?:\[\s*\])?\s*|\bfree\s*\(\s*)(\w+)", code))

    # A function returning a view (string_view/span) of a local owning object.
    for m in VIEW_FN.finditer(code):
        fn_body = code[m.end() - 1:matching_brace(code, m.end() - 1) + 1]
        owners = set(re.findall(r"\b(?:std::)?(?:string|vector<[^;>]*>|array<[^;>]*>)\s+(\w+)\s*[=({;]", fn_body))
        for r in re.finditer(r"\breturn\s+(\w+)\s*;", fn_body):
            if r.group(1) in owners:
                add("high", "dangling-view-return", m.end() - 1 + r.start(),
                    f"returns a view of local `{r.group(1)}`, which is destroyed on return: return the owning type")

    # std::endl inside a loop body: flushes every iteration.
    loop_stack: list[bool] = []
    last_stmt = 0
    for k, ch in enumerate(code):
        if ch == "{":
            head = code[last_stmt:k]
            loop_stack.append(bool(LOOP_HEAD.search(head)))
            last_stmt = k + 1
        elif ch == "}":
            if loop_stack:
                loop_stack.pop()
            last_stmt = k + 1
        elif ch == ";":
            last_stmt = k + 1
        elif ch == "e" and code.startswith("endl", k) and (k == 0 or not (code[k - 1].isalnum() or code[k - 1] == "_")) \
                and not code[k + 4:k + 5].isalnum() and any(loop_stack):
            add("low", "endl-in-loop", k, "std::endl flushes on every iteration: write '\\n' and flush once")

    if is_header and not GUARD.search(raw):
        add("low", "no-include-guard", 0, "header has no #pragma once or include guard")


# --------------------------------------------------------------------------- CMake checks

CM_GLOBAL = re.compile(r"^\s*(add_compile_options|add_definitions|add_compile_definitions|include_directories|"
                       r"link_libraries|link_directories|add_link_options)\s*\(", re.M | re.I)
CM_TARGET_EQUIV = {
    "add_compile_options": "target_compile_options", "add_definitions": "target_compile_definitions",
    "add_compile_definitions": "target_compile_definitions", "include_directories": "target_include_directories",
    "link_libraries": "target_link_libraries", "link_directories": "target_link_directories (or imported targets)",
    "add_link_options": "target_link_options",
}
CM_FLAGS = re.compile(r"^\s*(set|string)\s*\(\s*(?:APPEND\s+)?CMAKE_CXX_FLAGS\w*\b", re.M | re.I)
CM_STD = re.compile(r"CMAKE_CXX_STANDARD\s+\"?(\d+)", re.I)
CM_FEATURE = re.compile(r"\bcxx_std_(\d+)\b")
CM_EXT_ON = re.compile(r"(CMAKE_CXX_EXTENSIONS|CXX_EXTENSIONS)\s+\"?(ON|TRUE|1|YES)\b", re.I)
CM_EXT_OFF = re.compile(r"(CMAKE_CXX_EXTENSIONS|CXX_EXTENSIONS)\s+\"?(OFF|FALSE|0|NO)\b", re.I)
CM_MIN = re.compile(r"cmake_minimum_required\s*\(\s*VERSION\s+(\d+)\.(\d+)", re.I)
CM_GLOB = re.compile(r"\bfile\s*\(\s*GLOB(_RECURSE)?\b", re.I)
CM_BUILD_TYPE = re.compile(r"^\s*set\s*\(\s*CMAKE_BUILD_TYPE\b(?![^)]*CACHE)", re.M | re.I)
CM_WARN = re.compile(r"-Wall\b|/W[34]\b")
CM_WERROR = re.compile(r"-Werror\b(?!=)|/WX\b")
CM_SAN = re.compile(r"-fsanitize|/fsanitize|SANITIZ", re.I)
FAST_MATH = re.compile(r"-ffast-math|-Ofast\b")


def cmake_code(raw: str) -> str:
    """Drop # comments (outside quotes, roughly) so commented-out lines don't count."""
    return "\n".join(re.sub(r"(^|\s)#.*$", r"\1", line) for line in raw.splitlines())


def check_cmake(root: Path, cmake_files: list[Path], presets: list[Path], findings: list[Finding]) -> None:
    if not cmake_files:
        return
    texts = {p: cmake_code(p.read_text(errors="replace")) for p in cmake_files}
    rel = lambda p: str(p.relative_to(root))  # noqa: E731
    top = root / "CMakeLists.txt"
    all_text = "\n".join(texts.values())
    preset_text = "\n".join(p.read_text(errors="replace") for p in presets)

    for p, text in texts.items():
        for m in CM_GLOBAL.finditer(text):
            cmd = m.group(1).lower()
            findings.append(Finding("medium", "cmake-global-flags", f"{rel(p)}:{line_of(text, m.start())}",
                                    f"`{cmd}` applies to every target in the directory: use {CM_TARGET_EQUIV[cmd]} on the target"))
        for m in CM_FLAGS.finditer(text):
            findings.append(Finding("medium", "cmake-global-flags", f"{rel(p)}:{line_of(text, m.start())}",
                                    "CMAKE_CXX_FLAGS is global and string-typed: use target_compile_options (or a preset)"))
        for m in CM_EXT_ON.finditer(text):
            findings.append(Finding("medium", "cmake-extensions-on", f"{rel(p)}:{line_of(text, m.start())}",
                                    "compiler extensions on (-std=gnu++XX): set CMAKE_CXX_EXTENSIONS OFF for portable code"))
        for m in CM_GLOB.finditer(text):
            findings.append(Finding("low", "cmake-glob-sources", f"{rel(p)}:{line_of(text, m.start())}",
                                    "file(GLOB) sources miss added/removed files until re-configure: list sources explicitly"))
        for m in CM_BUILD_TYPE.finditer(text):
            findings.append(Finding("low", "cmake-hardcoded-build-type", f"{rel(p)}:{line_of(text, m.start())}",
                                    "CMAKE_BUILD_TYPE hard-coded in CMakeLists: choose it in CMakePresets.json"))
        for m in FAST_MATH.finditer(text):
            findings.append(Finding("medium", "fast-math", f"{rel(p)}:{line_of(text, m.start())}",
                                    "-ffast-math/-Ofast break IEEE semantics (NaN/inf checks vanish): enable narrower flags per target only if measured"))
        for m in CM_WERROR.finditer(text):
            line = text.splitlines()[line_of(text, m.start()) - 1]
            if "$<" not in line and not re.search(r"\bif\s*\(", line):
                findings.append(Finding("low", "cmake-unconditional-werror", f"{rel(p)}:{line_of(text, m.start())}",
                                        "unconditional -Werror breaks builds on newer compilers: gate it behind an option set in CI"))
        for m in CM_MIN.finditer(text):
            major, minor = int(m.group(1)), int(m.group(2))
            if (major, minor) < (3, 5):
                findings.append(Finding("high", "cmake-min-version", f"{rel(p)}:{line_of(text, m.start())}",
                                        f"cmake_minimum_required({major}.{minor}) is a hard error in CMake 4: require 3.28 or newer"))
            elif (major, minor) < (3, 25) and p == top:
                findings.append(Finding("low", "cmake-min-version", f"{rel(p)}:{line_of(text, m.start())}",
                                        f"cmake_minimum_required({major}.{minor}) predates presets v6+, FILE_SET headers, and C++23 support: use 3.28...4.x"))

    std_levels = [int(x) for x in CM_STD.findall(all_text)] + [int(x) for x in CM_FEATURE.findall(all_text)]
    std_levels += [int(x) for x in re.findall(r"CMAKE_CXX_STANDARD\"\s*:\s*\"(\d+)", preset_text)]
    if not std_levels:
        findings.append(Finding("high", "cmake-no-standard", rel(top) if top.exists() else rel(cmake_files[0]),
                                "no C++ standard set: add CMAKE_CXX_STANDARD 23 (+ REQUIRED ON, EXTENSIONS OFF) or target_compile_features(cxx_std_23)"))
    else:
        if max(std_levels) < 20:
            findings.append(Finding("low", "cmake-old-standard", rel(top) if top.exists() else rel(cmake_files[0]),
                                    f"C++{max(std_levels)}: new code should target C++23 (std::expected, std::print, ranges)"))
        if re.search(r"CMAKE_CXX_STANDARD\s", all_text) and not CM_EXT_OFF.search(all_text) \
                and not CM_EXT_ON.search(all_text) and "CMAKE_CXX_EXTENSIONS" not in preset_text:
            findings.append(Finding("medium", "cmake-extensions-on", rel(top) if top.exists() else rel(cmake_files[0]),
                                    "CMAKE_CXX_EXTENSIONS defaults to ON (gnu++XX): set it OFF next to CMAKE_CXX_STANDARD"))

    flag_text = all_text + "\n" + preset_text
    if not CM_WARN.search(flag_text):
        findings.append(Finding("medium", "cmake-no-warnings", rel(top) if top.exists() else rel(cmake_files[0]),
                                "no warning flags: add -Wall -Wextra -Wpedantic -Wconversion -Wshadow ... via an options target"))
    if not CM_SAN.search(flag_text):
        findings.append(Finding("low", "no-sanitizers", rel(top) if top.exists() else rel(cmake_files[0]),
                                "no sanitizer configuration: add asan (address;undefined) and tsan presets"))
    if top.exists() and not (root / "CMakePresets.json").exists():
        findings.append(Finding("medium", "no-presets", rel(top),
                                "no CMakePresets.json: commit dev/asan/tsan/release presets so every machine and CI builds the same way"))


# --------------------------------------------------------------------------- other files

def check_vcpkg(root: Path, findings: list[Finding]) -> None:
    manifest = root / "vcpkg.json"
    if not manifest.exists():
        return
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        findings.append(Finding("medium", "vcpkg-invalid", "vcpkg.json", f"cannot parse vcpkg.json: {exc}"))
        return
    config = root / "vcpkg-configuration.json"
    if "builtin-baseline" not in data and "configuration" not in data and "vcpkg-configuration" not in data \
            and not config.exists():
        findings.append(Finding("medium", "vcpkg-no-baseline", "vcpkg.json",
                                "no builtin-baseline: dependency versions float with the vcpkg checkout; pin one (vcpkg x-update-baseline --add-initial-baseline)"))


def check_docker(root: Path, path: Path, findings: list[Finding]) -> None:
    text = path.read_text(errors="replace")
    froms = [m for m in re.finditer(r"^\s*FROM\s+(\S+)", text, re.M | re.I)]
    if not froms:
        return
    final = froms[-1].group(1).lower()
    if re.match(r"(gcc|ubuntu|debian|fedora|silkeh/clang|conanio)\b", final) and "distroless" not in final:
        findings.append(Finding("low", "docker-fat-runtime", f"{path.relative_to(root)}:{line_of(text, froms[-1].start())}",
                                f"final stage `{final}` ships a compiler/OS: copy the binary into gcr.io/distroless/cc (or scratch for fully static)"))


# --------------------------------------------------------------------------- main

def audit(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    owners: dict = {"members": [], "released": set()}
    cmake_files: list[Path] = []
    presets: list[Path] = []
    for path in walk(root):
        suffix = path.suffix.lower()
        rel = str(path.relative_to(root))
        if suffix in CXX_SOURCE or suffix in CXX_HEADER:
            try:
                check_cxx(path, rel, path.read_text(errors="replace"), findings, owners)
            except OSError:
                continue
        elif path.name == "CMakeLists.txt" or suffix == ".cmake":
            cmake_files.append(path)
        elif path.name in ("CMakePresets.json", "CMakeUserPresets.json"):
            presets.append(path)
        elif path.name == "Dockerfile" or path.name.startswith("Dockerfile.") or suffix == ".dockerfile":
            check_docker(root, path, findings)
    for cls, member, loc in owners["members"]:
        if member in owners["released"]:
            findings.append(Finding("high", "raw-owning-pointer", loc,
                                    f"`{cls}::{member}` is a raw owning pointer (released by hand): use std::unique_ptr "
                                    "or a container, and the copy operations stop being a double free"))
    check_cmake(root, cmake_files, presets, findings)
    check_vcpkg(root, findings)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (order[f.severity], f.check, f.location))
    return findings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="audit.py",
        description="Static health check of a C++/CMake project (ownership, casts, headers, "
                    "CMake hygiene, concurrency, deploy). Exit 0 = clean at --fail-on, 1 = findings, 2 = bad input.",
        epilog="Examples:\n  python3 scripts/audit.py .\n  python3 scripts/audit.py ~/code/acme --json --fail-on medium",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", default=".", help="project root (default: .)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fail-on", default="high", choices=[*SEVERITIES, "none"],
                        help="lowest severity that makes the exit code 1 (default: high)")
    args = parser.parse_args(argv)  # argparse exits 2 on bad arguments

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"audit.py: not a directory: {args.root}", file=sys.stderr)
        return 2

    findings = audit(root)
    counts = {s: sum(f.severity == s for f in findings) for s in SEVERITIES}
    if args.json:
        print(json.dumps({"root": str(root), "summary": counts, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        if not findings:
            print(f"{root}: no findings")
        for sev in SEVERITIES:
            group = [f for f in findings if f.severity == sev]
            if group:
                print(f"\n{sev.upper()} ({len(group)})")
                for f in group:
                    print(f"  [{f.check}] {f.location}: {f.message}")
        print(f"\nsummary: {counts['high']} high, {counts['medium']} medium, {counts['low']} low")

    if args.fail_on == "none":
        return 0
    threshold = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(f.severity) <= threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
