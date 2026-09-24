"""Tests for skills/typescript/scripts (run: make test).

The audit is TypeScript that runs under both Node (native type stripping, 22.18+/24+)
and Bun. Each runtime found on PATH is exercised; the suite skips when neither is.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "typescript"
AUDIT = SKILL / "scripts" / "audit.ts"
FLAWED = SKILL / "evals" / "files" / "flawed_sdk"


def node_with_type_stripping():
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    m = re.match(r"v(\d+)\.(\d+)", out)
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2))
    # Type stripping is on by default from 23.6 and 22.18.
    if major > 23 or (major == 23 and minor >= 6) or (major == 22 and minor >= 18):
        return node
    return None


def working_bun():
    bun = shutil.which("bun")
    if not bun:
        return None
    # A version-manager shim can exist without a selected version; only use a bun that runs.
    ok = subprocess.run([bun, "--version"], capture_output=True, text=True).returncode == 0
    return bun if ok else None


RUNTIMES = [r for r in (node_with_type_stripping(), working_bun()) if r]

EXPECTED_FLAWED_CHECKS = {
    "tsconfig-removed-option", "tsconfig-not-strict", "tsconfig-ignore-deprecations", "tsconfig-missing-flag",
    "tsconfig-commonjs", "hardcoded-secret", "library-no-exports", "package-not-esm", "multiple-lockfiles",
    "docker-ts-runner", "docker-root", "docker-unlocked-install", "no-graceful-shutdown", "non-null-assertion",
    "fetch-no-signal", "floating-promise", "as-any", "explicit-any", "commonjs", "parameter-property",
    "library-console", "unvalidated-json", "ts-ignore", "empty-catch", "throw-literal", "enum", "namespace",
    "error-without-cause", "legacy-dependency", "experimental-strip-flag", "legacy-runner", "no-linter",
}

CLEAN_PROJECT = {
    "package.json": json.dumps({
        "name": "@x/lib", "version": "1.0.0", "type": "module", "files": ["dist"],
        "exports": {".": {"types": "./dist/index.d.ts", "default": "./dist/index.js"}},
    }),
    "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
    "biome.json": "{}",
    "tsconfig.json": """{
      // comments and trailing commas are allowed
      "compilerOptions": {
        "strict": true,
        "noUncheckedIndexedAccess": true,
        "verbatimModuleSyntax": true,
        "erasableSyntaxOnly": true,
        "isolatedDeclarations": true,
      },
    }""",
    "src/index.ts": """import * as z from 'zod'

export const Status = { Active: 'active', Closed: 'closed' } as const
export type Status = (typeof Status)[keyof typeof Status]

const User = z.object({ id: z.string(), name: z.string() })
export type User = z.infer<typeof User>

export class Client {
  readonly #baseUrl: string

  constructor(baseUrl: string) {
    this.#baseUrl = baseUrl
  }

  async user(id: string, signal?: AbortSignal): Promise<User> {
    const res = await fetch(`${this.#baseUrl}/users/${id}`, {
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(5_000)]) : AbortSignal.timeout(5_000),
    })
    if (!res.ok) throw new Error(`GET /users/${id} answered ${res.status}`)
    return User.parse(await res.json())
  }
}

export function label(status: Status, note?: string): string {
  const first = note?.split(' ')[0]
  const shout = 'yes!' // a ! inside a string is not an assertion
  if (first !== undefined && status !== 'closed') return `${first}${shout.length}`
  return /a!b/.test(status) ? 'odd' : status
}

export async function load(text: string): Promise<User> {
  try {
    return User.parse(JSON.parse(text))
  } catch (error) {
    throw new Error('invalid user payload', { cause: error })
  }
}

export async function refresh(ids: readonly string[], client: Client): Promise<void> {
  await Promise.all(ids.map((id) => client.user(id)))
  void load('{}').catch(() => undefined)
}
""",
    "src/index.test.ts": """import { expect, it } from 'vitest'
import { label } from './index.ts'

it('labels', () => {
  // @ts-expect-error: unknown status is rejected at compile time
  expect(label('nope')).toBe('nope')
})
""",
}


def write_tree(root: Path, files: dict) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@unittest.skipUnless(RUNTIMES, "neither node (>= 22.18) nor bun is installed")
class AuditTests(unittest.TestCase):
    def run_audit(self, *args, runtime=None):
        return subprocess.run([runtime or RUNTIMES[0], str(AUDIT), *map(str, args)], capture_output=True, text=True)

    def test_flawed_fixture_findings_on_every_runtime(self):
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                res = self.run_audit(FLAWED, "--json", runtime=runtime)
                self.assertEqual(res.returncode, 1, res.stderr)
                findings = json.loads(res.stdout)["findings"]
                checks = {f["check"] for f in findings}
                missing = EXPECTED_FLAWED_CHECKS - checks
                self.assertFalse(missing, f"audit missed planted issues: {sorted(missing)}")
                self.assertGreaterEqual(sum(f["severity"] == "high" for f in findings), 5)
                for f in findings:
                    self.assertIn(f["severity"], ("high", "medium", "low"))
                    self.assertTrue(f["location"] and f["message"])

    def test_text_report_and_severity_order(self):
        res = self.run_audit(FLAWED)
        self.assertEqual(res.returncode, 1)
        out = res.stdout
        self.assertLess(out.index("HIGH"), out.index("MEDIUM"))
        self.assertLess(out.index("MEDIUM"), out.index("LOW"))
        self.assertIn("Summary:", out)

    def test_clean_project_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(Path(tmp), CLEAN_PROJECT)
            for runtime in RUNTIMES:
                with self.subTest(runtime=runtime):
                    res = self.run_audit(tmp, "--json", "--fail-on", "low", runtime=runtime)
                    out = json.loads(res.stdout)
                    self.assertEqual(out["findings"], [], out["findings"])
                    self.assertEqual(res.returncode, 0)

    def test_assets_are_clean(self):
        res = self.run_audit(SKILL / "assets", "--json", "--fail-on", "low")
        findings = json.loads(res.stdout)["findings"]
        # The flat assets dir has no lockfile, linter config, or tsconfig.json at its root; everything else must be clean.
        unexpected = [f for f in findings if f["check"] not in ("no-lockfile", "no-linter", "no-tsconfig")]
        self.assertEqual(unexpected, [], unexpected)

    def test_fail_on_thresholds(self):
        self.assertEqual(self.run_audit(FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(self.run_audit(FLAWED, "--fail-on=high").returncode, 1)
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(Path(tmp), {**CLEAN_PROJECT, "src/extra.ts": "export const f = (x: unknown) => x as any\n"})
            self.assertEqual(self.run_audit(tmp).returncode, 0)  # medium only, default threshold is high
            self.assertEqual(self.run_audit(tmp, "--fail-on", "medium").returncode, 1)

    def test_bad_invocation(self):
        self.assertEqual(self.run_audit("/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(self.run_audit(FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(self.run_audit(FLAWED, "--bogus-flag").returncode, 2)
        self.assertEqual(self.run_audit(FLAWED, "--fail-on").returncode, 2)
        self.assertEqual(self.run_audit().returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "notes.txt").write_text("hi")
            self.assertEqual(self.run_audit(tmp).returncode, 2)  # not a TypeScript project
        res = self.run_audit("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Usage:", res.stdout)


if __name__ == "__main__":
    unittest.main()
