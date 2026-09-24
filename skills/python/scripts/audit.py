#!/usr/bin/env python3
"""Static health check of a Python project. Parses with `ast`; no imports, no network.

Usage:
  python3 scripts/audit.py [ROOT] [--json] [--fail-on high|medium|low|none]

high    eval()/exec(); unsafe deserialization (pickle/marshal/shelve/dill, yaml.load without
        SafeLoader); shell=True / os.system with a non-constant command; SQL built with an
        f-string, .format(), %, or + and passed to execute()/text(); TLS verification disabled
        (verify=False); hard-coded secrets and credentialed connection URLs; time.sleep(),
        requests.*, or urlopen() inside `async def`
medium  bare `except:`; `except Exception: pass`; mutable default arguments; requests/urlopen
        without a timeout; subprocess or open() inside `async def`; create_task() results
        that nothing keeps (the task can be garbage-collected mid-flight);
        asyncio.get_event_loop(); datetime.utcnow()/utcfromtimestamp(); tempfile.mktemp();
        `random` used for secrets or tokens; shell=True with a constant command; setup.py or
        requirements.txt without pyproject.toml; no lockfile; Docker: Alpine base, shell-form
        CMD/ENTRYPOINT (SIGTERM never reaches Python), --reload, `uv sync` without
        --locked/--frozen
low     public functions without type hints; typing.List/Dict/Optional/Union imports;
        `from __future__ import annotations` on 3.14+; f-strings in logging calls;
        datetime.now() without a tz; no requires-python, or one that admits EOL Pythons;
        no ruff or type-checker config; [tool.pytest.ini_options] on pytest 9; Docker: full
        (non-slim) python image, root user, pip install without --require-hashes;
        files the running interpreter can't parse (run the audit with the project's Python)

Needs Python 3.11+ (tomllib); run it with the project's Python version or newer so newer
syntax parses. Test code (tests/, test_*.py, *_test.py, conftest.py) is skipped by the
source checks.

Exit codes: 0 = no findings at/above --fail-on (default: high), 1 = findings, 2 = bad input.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

SEVERITIES = ("high", "medium", "low")
SKIP_DIRS = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    ".eggs",
    "htmlcov",
}
TEST_DIRS = {"tests", "test", "testing"}
LOCKFILES = ("uv.lock", "poetry.lock", "pdm.lock", "pylock.toml", "Pipfile.lock")

SQL_RE = re.compile(r"\b(select|insert|update|delete|where|from|values|order\s+by)\b", re.IGNORECASE)
SECRET_NAME_RE = re.compile(
    r"(?i)(^|_)(password|passwd|pwd|secret|secret_key|api_?key|access_?key|auth_?token|token|private_?key)$"
)
CRED_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]+)@([^\s/:?#]+)", re.IGNORECASE)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "db", "postgres", "host", "example.com", "::1"}
SQL_SINKS = {
    "execute",
    "executemany",
    "exec_driver_sql",
    "text",
    "raw",
    "executescript",
    "fetch",
    "fetchrow",
    "fetchval",
    "mogrify",
    "read_sql",
    "read_sql_query",
}
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
LOGGER_NAMES = {"log", "logger", "logging", "_log", "_logger", "LOG", "LOGGER"}
LEGACY_TYPING = {"List", "Dict", "Set", "FrozenSet", "Tuple", "Type", "Optional", "Union", "Text"}
UNSAFE_LOADS = {
    "pickle.load",
    "pickle.loads",
    "pickle.Unpickler",
    "cPickle.load",
    "cPickle.loads",
    "_pickle.loads",
    "dill.load",
    "dill.loads",
    "marshal.load",
    "marshal.loads",
    "shelve.open",
    "jsonpickle.decode",
    "pandas.read_pickle",
    "yaml.unsafe_load",
    "yaml.full_load",
    "joblib.load",
    "torch.load",
}
SAFE_YAML_LOADERS = {"SafeLoader", "CSafeLoader", "BaseLoader"}
BLOCKING_HIGH = {"time.sleep", "urllib.request.urlopen"}
BLOCKING_MEDIUM = {
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "os.system",
    "open",
    "input",
}
SECRETISH_RE = re.compile(r"(?i)(token|secret|passw|otp|nonce|salt|api_?key|session_?id)")


@dataclass
class Finding:
    severity: str
    check: str
    location: str
    message: str


@dataclass
class Report:
    root: Path
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, check: str, path: Path, message: str, line: int | None = None) -> None:
        try:
            rel = path.relative_to(self.root).as_posix()
        except ValueError:
            rel = path.as_posix()
        loc = f"{rel}:{line}" if line else rel
        self.findings.append(Finding(severity, check, loc or ".", message))


# ---------------------------------------------------------------- source checks


def dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def is_dynamic_str(node: ast.AST) -> bool:
    """An f-string with placeholders, str.format(), or %/+ involving a string literal."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return isinstance(node.func.value, (ast.Constant, ast.JoinedStr))
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        operands: list[ast.AST] = []
        stack: list[ast.AST] = [node]
        while stack:  # flatten a + b + c chains
            n = stack.pop()
            if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mod, ast.Add)):
                stack.extend((n.left, n.right))
            else:
                operands.append(n)
        has_literal = any(
            isinstance(o, ast.JoinedStr) or (isinstance(o, ast.Constant) and isinstance(o.value, str)) for o in operands
        )
        return has_literal and any(not isinstance(o, ast.Constant) for o in operands)
    return False


def literal_text(node: ast.AST) -> str:
    return " ".join(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def is_sql_builder(node: ast.AST) -> bool:
    return is_dynamic_str(node) and bool(SQL_RE.search(literal_text(node)))


def kw(call: ast.Call, name: str) -> ast.expr | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


class SourceChecker(ast.NodeVisitor):
    def __init__(self, report: Report, path: Path, future_ok: bool) -> None:
        self.r = report
        self.path = path
        self.future_ok = future_ok
        self.aliases: dict[str, str] = {}
        self.async_depth = 0
        self.class_depth = 0
        self.func_depth = 0
        self.sql_names: list[set[str]] = [set()]

    def add(self, severity: str, check: str, node: ast.AST, message: str) -> None:
        self.r.add(severity, check, self.path, message, getattr(node, "lineno", None))

    def resolve(self, node: ast.AST) -> str | None:
        name = dotted(node)
        if name is None:
            return None
        head, _, rest = name.partition(".")
        if head in self.aliases:
            base = self.aliases[head]
            return f"{base}.{rest}" if rest else base
        return name

    # imports ------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for a in node.names:
            self.aliases[a.asname or a.name] = f"{mod}.{a.name}" if mod else a.name
        if mod == "typing":
            legacy = sorted(a.name for a in node.names if a.name in LEGACY_TYPING)
            if legacy:
                self.add(
                    "low",
                    "legacy-typing",
                    node,
                    f"typing.{', typing.'.join(legacy)}: use list/dict/tuple and `X | None` (PEP 585/604)",
                )
        if mod == "__future__" and any(a.name == "annotations" for a in node.names) and self.future_ok:
            self.add(
                "low",
                "future-annotations",
                node,
                "`from __future__ import annotations` is unnecessary on 3.14+ (PEP 649 defers annotations)",
            )

    # functions ----------------------------------------------------------------
    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        self.check_defaults(node)
        if self.func_depth == 0:
            self.check_hints(node)
        self.func_depth += 1
        saved_async = self.async_depth
        self.async_depth = 1 if is_async else 0
        self.sql_names.append(set())
        self.generic_visit(node)
        self.sql_names.pop()
        self.async_depth = saved_async
        self.func_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, is_async=True)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        saved = self.async_depth
        self.async_depth = 0
        self.generic_visit(node)
        self.async_depth = saved

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_depth += 1
        saved = self.func_depth
        self.func_depth = 0  # methods are checked for hints like module-level functions
        self.generic_visit(node)
        self.func_depth = saved
        self.class_depth -= 1

    def check_defaults(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for d in [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]:
            mutable = isinstance(d, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp))
            if isinstance(d, ast.Call) and dotted(d.func) in {
                "list",
                "dict",
                "set",
                "collections.defaultdict",
                "defaultdict",
                "deque",
                "collections.deque",
            }:
                mutable = True
            if mutable:
                self.add(
                    "medium",
                    "mutable-default",
                    d,
                    f"mutable default argument in {node.name}(): it is shared across calls; default to None",
                )

    def check_hints(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name.startswith("_") and node.name != "__init__":
            return
        if any(dotted(d) in {"overload", "typing.overload"} for d in node.decorator_list):
            return
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if self.class_depth and args and args[0].arg in {"self", "cls"}:
            args = args[1:]
        for extra in (node.args.vararg, node.args.kwarg):
            if extra is not None:
                args.append(extra)
        missing = [a.arg for a in args if a.annotation is None]
        no_return = node.returns is None and node.name != "__init__"
        if missing or no_return:
            what = []
            if missing:
                what.append(f"parameters {', '.join(missing)}")
            if no_return:
                what.append("return type")
            self.add("low", "missing-type-hints", node, f"public function {node.name}() lacks {' and '.join(what)}")

    # statements ---------------------------------------------------------------
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.add(
                "medium",
                "bare-except",
                node,
                "bare `except:` also catches KeyboardInterrupt/SystemExit; catch specific exceptions",
            )
        elif dotted(node.type) in {"Exception", "BaseException"} and all(
            isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            for s in node.body
        ):
            self.add(
                "medium",
                "swallowed-exception",
                node,
                "`except Exception: pass` hides failures; handle, log, or re-raise",
            )
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Constant):
            return  # docstrings and bare string statements are documentation, not code
        if isinstance(node.value, ast.Call):
            name = self.resolve(node.value.func) or ""
            loop_task = name.endswith(("loop.create_task", "loop().create_task"))
            if name in {"asyncio.create_task", "asyncio.ensure_future"} or loop_task:
                self.add(
                    "medium",
                    "task-not-referenced",
                    node,
                    "create_task() result is dropped: the event loop keeps only a weak reference; "
                    "use asyncio.TaskGroup or keep the task in a set",
                )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for t in node.targets:
            self.check_assignment(t, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.check_assignment(node.target, node.value)
        self.generic_visit(node)

    def check_assignment(self, target: ast.AST, value: ast.AST) -> None:
        name = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else None
        if name is None:
            return
        if is_sql_builder(value):
            self.sql_names[-1].add(name)
        if SECRET_NAME_RE.search(name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
            v = value.value
            if v and not re.fullmatch(r"[A-Z][A-Z0-9_]*", v) and not v.startswith(("<", "${", "{{")):
                self.add(
                    "high", "hardcoded-secret", value, f"{name} is a hard-coded secret; read it from the environment"
                )
        if SECRETISH_RE.search(name) and any(
            isinstance(n, ast.Call) and (self.resolve(n.func) or "").startswith("random.") for n in ast.walk(value)
        ):
            self.add(
                "medium",
                "insecure-random",
                value,
                f"{name} comes from `random` (predictable); use the `secrets` module",
            )

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            m = CRED_URL_RE.search(node.value)
            host = m.group(2).lower() if m else ""
            if (
                m
                and host not in LOCAL_HOSTS
                and not host.endswith((".local", ".test", ".example", "example.com", "example.org", ".internal"))
            ):
                self.add("high", "hardcoded-secret", node, "connection URL with embedded credentials; use an env var")

    # calls --------------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        name = self.resolve(node.func) or ""
        raw = dotted(node.func) or ""
        attr = node.func.attr if isinstance(node.func, ast.Attribute) else raw

        if raw in {"eval", "exec"} and raw not in self.aliases:
            self.add(
                "high",
                "eval-exec",
                node,
                f"{raw}() runs arbitrary code; parse the data instead (ast.literal_eval, json)",
            )

        if name in UNSAFE_LOADS:
            self.add(
                "high",
                "unsafe-deserialization",
                node,
                f"{name}() can execute code from its input; never load untrusted data this way (use JSON)",
            )
        if name == "yaml.load":
            loader = kw(node, "Loader") or (node.args[1] if len(node.args) > 1 else None)
            if loader is None or (dotted(loader) or "").split(".")[-1] not in SAFE_YAML_LOADERS:
                self.add("high", "unsafe-deserialization", node, "yaml.load without SafeLoader; use yaml.safe_load")

        shell = kw(node, "shell")
        if (name.startswith("subprocess.") and is_true(shell)) or name in {"os.system", "os.popen"}:
            cmd = node.args[0] if node.args else kw(node, "args")
            const = isinstance(cmd, ast.Constant)
            self.add(
                "medium" if const else "high",
                "shell-injection",
                node,
                f"{name}() runs through a shell; pass an argument list without shell=True",
            )

        if attr in SQL_SINKS and node.args:
            first = node.args[0]
            if is_sql_builder(first) or (isinstance(first, ast.Name) and first.id in self.sql_names[-1]):
                self.add(
                    "high",
                    "sql-string-building",
                    node,
                    "SQL built from strings (f-string/format/%/+): SQL injection; use bound parameters",
                )

        verify = kw(node, "verify")
        if isinstance(verify, ast.Constant) and verify.value is False:
            self.add("high", "tls-verify-disabled", node, "verify=False disables TLS certificate checks")

        is_requests = name.startswith("requests.") and name.split(".")[-1] in HTTP_VERBS
        if (is_requests or name == "urllib.request.urlopen") and kw(node, "timeout") is None:
            self.add("medium", "http-no-timeout", node, f"{name}() without timeout= can hang forever")

        if self.async_depth:
            if name in BLOCKING_HIGH or is_requests:
                self.add(
                    "high",
                    "blocking-in-async",
                    node,
                    f"{name}() blocks the event loop inside async def; use the async equivalent or asyncio.to_thread",
                )
            elif name in BLOCKING_MEDIUM:
                self.add(
                    "medium",
                    "blocking-in-async",
                    node,
                    f"{name}() blocks the event loop inside async def; use asyncio.to_thread or an async API",
                )

        if name in {"asyncio.get_event_loop", "asyncio.get_event_loop_policy", "asyncio.set_event_loop_policy"}:
            self.add(
                "medium",
                "get-event-loop",
                node,
                f"{name}() is legacy (3.14 raises without a current loop / deprecates policies); "
                "use asyncio.run() and asyncio.get_running_loop()",
            )

        if name.endswith(("datetime.utcnow", "datetime.utcfromtimestamp")) or name in {"utcnow"}:
            self.add(
                "medium",
                "naive-datetime",
                node,
                "utcnow()/utcfromtimestamp() return naive datetimes (deprecated); use datetime.now(UTC)",
            )
        elif name.endswith("datetime.now") and not node.args and kw(node, "tz") is None:
            self.add("low", "naive-datetime", node, "datetime.now() without tz is naive local time; pass UTC")

        if name == "tempfile.mktemp":
            self.add("medium", "insecure-tempfile", node, "tempfile.mktemp() is racy; use NamedTemporaryFile/mkstemp")

        if (
            attr in LOG_METHODS
            and isinstance(node.func, ast.Attribute)
            and (dotted(node.func.value) or "").split(".")[-1] in LOGGER_NAMES
            and node.args
            and isinstance(node.args[0], ast.JoinedStr)
        ):
            self.add(
                "low",
                "logging-fstring",
                node,
                "f-string in a logging call: formats even when filtered and breaks aggregation; use %s args or extra=",
            )

        self.generic_visit(node)


def is_test_file(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    name = path.name
    return (
        any(p in TEST_DIRS for p in rel.parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def python_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).parts
        if any(part in SKIP_DIRS or (part.startswith(".") and part not in {".", ".."}) for part in rel[:-1]):
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------- project checks


def load_toml(path: Path, report: Report) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        report.add("medium", "bad-toml", path, f"cannot parse: {exc}")
        return {}


def min_python(spec: str) -> tuple[int, int] | None:
    m = re.search(r">=?\s*3\.(\d+)", spec)
    return (3, int(m.group(1))) if m else None


def check_project(root: Path, report: Report) -> tuple[int, int] | None:
    """Project-level checks. Returns the lowest supported Python found (for other checks)."""
    pyproject = root / "pyproject.toml"
    has_setup = (root / "setup.py").is_file()
    reqs = sorted(root.glob("requirements*.txt"))
    if not pyproject.is_file():
        if has_setup:
            report.add(
                "medium",
                "legacy-setup-py",
                root / "setup.py",
                "setup.py without pyproject.toml: declare the project in PEP 621 pyproject.toml (uv init)",
            )
        if reqs:
            report.add(
                "medium",
                "requirements-only",
                reqs[0],
                "requirements.txt without pyproject.toml: use pyproject.toml + uv.lock (uv add); export requirements only if a tool needs them",
            )
        if not has_setup and not reqs:
            return None
        report.add("medium", "no-lockfile", root, "no lockfile: commit uv.lock so every install is reproducible")
        return None

    data = load_toml(pyproject, report)
    if not any((root / f).is_file() for f in LOCKFILES):
        report.add(
            "medium", "no-lockfile", pyproject, "no lockfile next to pyproject.toml: run `uv lock` and commit uv.lock"
        )

    tool = data.get("tool", {})
    if "ruff" not in tool and not (root / "ruff.toml").is_file() and not (root / ".ruff.toml").is_file():
        report.add("low", "no-linter", pyproject, "no ruff configuration ([tool.ruff])")
    if not ({"mypy", "pyright", "ty", "basedpyright"} & tool.keys()) and not any(
        (root / f).is_file() for f in ("mypy.ini", ".mypy.ini", "pyrightconfig.json", "ty.toml")
    ):
        report.add("low", "no-type-checker", pyproject, "no type checker configured ([tool.mypy] strict = true)")
    if "ini_options" in tool.get("pytest", {}):
        report.add(
            "low",
            "pytest-ini-options",
            pyproject,
            "[tool.pytest.ini_options] is the legacy string form; pytest 9 reads native [tool.pytest]",
        )

    lowest: tuple[int, int] | None = None
    manifests = [(pyproject, data)]
    members = tool.get("uv", {}).get("workspace", {}).get("members", [])
    for pattern in members:
        for member in sorted(root.glob(pattern)):
            mp = member / "pyproject.toml"
            if mp.is_file():
                manifests.append((mp, load_toml(mp, report)))
    for path, manifest in manifests:
        project = manifest.get("project")
        if project is None:
            continue
        spec = project.get("requires-python")
        if not spec:
            report.add("low", "no-requires-python", path, "[project] has no requires-python")
            continue
        mp = min_python(spec)
        if mp and mp < (3, 10):
            report.add("low", "eol-python", path, f"requires-python {spec!r} admits end-of-life Pythons (< 3.10)")
        if mp and (lowest is None or mp < lowest):
            lowest = mp
    return lowest


def check_dockerfile(path: Path, report: Report) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    stages = [i for i, line in enumerate(lines) if re.match(r"\s*FROM\s", line, re.IGNORECASE)]
    if not stages:
        return
    for i in stages:
        m = re.match(r"\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", lines[i], re.IGNORECASE)
        image = m.group(1) if m else ""
        if re.match(r"(docker\.io/)?(library/)?python:", image):
            tag = image.split(":", 1)[1]
            ver = re.match(r"3\.(\d+)", tag)
            if ver and int(ver.group(1)) < 10:
                report.add("medium", "docker-eol-python", path, f"{image} is an end-of-life Python", i + 1)
            if "alpine" in tag:
                report.add(
                    "medium",
                    "docker-alpine",
                    path,
                    "python on Alpine (musl): most wheels must compile from source and run slower; use -slim",
                    i + 1,
                )
            elif "slim" not in tag:
                report.add(
                    "low", "docker-full-image", path, f"{image} is the full image (~1 GB); use a -slim tag", i + 1
                )
    final = lines[stages[-1] :]
    users = [line.split()[1] for line in final if re.match(r"\s*USER\s+\S", line, re.IGNORECASE)]
    if not users or users[-1] in {"root", "0", "0:0"}:
        report.add(
            "low", "docker-root-user", path, "final stage runs as root; add a system user and USER it", stages[-1] + 1
        )
    env_locked = re.search(r"UV_(LOCKED|FROZEN)\s*=?\s*1", text)
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if re.match(r"(CMD|ENTRYPOINT)\s", s, re.IGNORECASE):
            body = s.split(None, 1)[1] if len(s.split(None, 1)) > 1 else ""
            if not body.startswith("["):
                report.add(
                    "medium",
                    "docker-shell-form",
                    path,
                    "shell-form CMD/ENTRYPOINT: /bin/sh is PID 1 and SIGTERM never reaches Python (no graceful shutdown); use exec form [...]",
                    n,
                )
            if "--reload" in body:
                report.add("medium", "docker-reload", path, "--reload is a dev-only file watcher", n)
        if re.search(r"\buv\s+sync\b", s) and not re.search(r"--(locked|frozen)\b", s) and not env_locked:
            report.add(
                "medium",
                "docker-unlocked-install",
                path,
                "uv sync without --locked/--frozen may re-resolve dependencies",
                n,
            )
        if re.search(r"\bpip3?\s+install\b", s) and "--require-hashes" not in s and not re.search(r"\buv\b", s):
            report.add(
                "low",
                "docker-pip-install",
                path,
                "pip install without --require-hashes; install from uv.lock (uv sync --locked) instead",
                n,
            )


# ---------------------------------------------------------------- main


def audit(root: Path) -> Report:
    report = Report(root)
    lowest = check_project(root, report)
    future_ok = lowest is not None and lowest >= (3, 14)
    for path in python_files(root):
        if is_test_file(path, root):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError as exc:
            report.add(
                "low",
                "parse-error",
                path,
                f"cannot parse with Python {sys.version_info.major}.{sys.version_info.minor} ({exc.msg}); "
                "run the audit with the project's Python",
                exc.lineno,
            )
            continue
        SourceChecker(report, path, future_ok).visit(tree)
    for docker in sorted(root.rglob("Dockerfile*")):
        if not any(part in SKIP_DIRS for part in docker.relative_to(root).parts[:-1]) and docker.is_file():
            check_dockerfile(docker, report)
    order = {s: i for i, s in enumerate(SEVERITIES)}

    def key(f: Finding) -> tuple[int, str, str, int]:
        path, _, line = f.location.partition(":")
        return order[f.severity], f.check, path, int(line) if line.isdigit() else 0

    report.findings.sort(key=key)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit.py",
        description="Static anti-pattern scan of a Python project (ast-based; no imports, no network).",
        epilog="Exit codes: 0 = clean at --fail-on, 1 = findings, 2 = bad input.",
    )
    parser.add_argument("root", nargs="?", default=".", help="project directory (default: .)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fail-on", default="high", help="high | medium | low | none (default: high)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if tomllib is None:
        print("error: needs Python 3.11+ (tomllib)", file=sys.stderr)
        return 2
    if args.fail_on not in (*SEVERITIES, "none"):
        print(f"error: --fail-on must be high, medium, low, or none (got {args.fail_on!r})", file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    if not (root / "pyproject.toml").is_file() and not python_files(root) and not (root / "setup.py").is_file():
        print(f"error: no Python project found in {args.root}", file=sys.stderr)
        return 2

    report = audit(root)
    summary = {s: sum(f.severity == s for f in report.findings) for s in SEVERITIES}
    if args.json:
        print(
            json.dumps(
                {"root": str(root), "summary": summary, "findings": [asdict(f) for f in report.findings]}, indent=2
            )
        )
    else:
        if not report.findings:
            print(f"{root}: no findings")
        for sev in SEVERITIES:
            group = [f for f in report.findings if f.severity == sev]
            if group:
                print(f"\n{sev.upper()} ({len(group)})")
                for f in group:
                    print(f"  [{f.check}] {f.location}: {f.message}")
        print(f"\nsummary: {summary['high']} high, {summary['medium']} medium, {summary['low']} low")
    if args.fail_on == "none":
        return 0
    threshold = SEVERITIES.index(args.fail_on)
    return 1 if any(SEVERITIES.index(f.severity) <= threshold for f in report.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
