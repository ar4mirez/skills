"""Tests for skills/bun-elysia/scripts (run: make test). Skipped when Bun isn't installed."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "bun-elysia"
AUDIT = SKILL / "scripts" / "audit.ts"
NEWMOD = SKILL / "scripts" / "new-module.ts"
FLAWED = SKILL / "evals" / "files" / "flawed_repo"
BUN = shutil.which("bun")


def bun(*args):
    return subprocess.run([BUN, *map(str, args)], capture_output=True, text=True)


@unittest.skipUnless(BUN, "bun not installed")
class AuditTests(unittest.TestCase):
    def test_flawed_repo_findings(self):
        res = bun(AUDIT, FLAWED, "--json")
        self.assertEqual(res.returncode, 1, res.stderr)
        checks = {f["check"] for f in json.loads(res.stdout)["findings"]}
        for expected in ("package-depends-on-app", "client-runtime-import", "eden-version-drift", "tsconfig-not-strict",
                         "alpine-without-musl", "app-depends-on-app", "deprecated-lucia", "not-method-chained",
                         "whole-context", "route-without-body-schema", "cross-module-import", "service-imports-elysia",
                         "bytecode-without-esm", "bun-check", "binary-lockfile", "swagger-plugin", "error-helper",
                         "no-biome"):
            self.assertIn(expected, checks)

    def test_clean_repo_and_type_import_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(json.dumps({"name": "x", "workspaces": {"packages": ["apps/*"], "catalog": {"elysia": "^1.4.30"}}}))
            (root / "bun.lock").write_text("{}")
            (root / "biome.json").write_text("{}")
            api = root / "apps" / "api"
            (api / "src" / "modules" / "billing").mkdir(parents=True)
            (api / "package.json").write_text(json.dumps({"name": "@x/api", "dependencies": {"elysia": "catalog:"}}))
            (api / "tsconfig.json").write_text('{ "compilerOptions": { "strict": true } }')
            (api / "src" / "modules" / "billing" / "index.ts").write_text(
                "import { Elysia, t } from 'elysia'\nexport const billing = new Elysia({ name: 'module.billing' })\n"
                "  .post('/x', ({ body }) => body, { body: t.Object({ a: t.String() }) })\n")
            web = root / "apps" / "web"
            (web / "src").mkdir(parents=True)
            (web / "package.json").write_text(json.dumps({"name": "@x/web", "dependencies": {"@elysia/eden": "^1.4.10"},
                                                          "devDependencies": {"@x/api": "workspace:*", "elysia": "catalog:"}}))
            (web / "tsconfig.json").write_text('{ "compilerOptions": { "strict": true } }')
            (web / "src" / "api.ts").write_text(
                "import { treaty } from '@elysia/eden'\nimport type { App } from '@x/api'\n"
                "export const api = treaty<App>(process.env.NEXT_PUBLIC_API_URL ?? 'localhost:3000')\n")
            res = bun(AUDIT, root, "--json")
        out = json.loads(res.stdout)
        self.assertEqual(res.returncode, 0, out)
        self.assertEqual(out["findings"], [])

    def test_module_cycle_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(json.dumps({"name": "x", "workspaces": ["apps/*"]}))
            (root / "bun.lock").write_text("{}")
            (root / "biome.json").write_text("{}")
            api = root / "apps" / "api"
            for mod, other in (("billing", "notifications"), ("notifications", "billing")):
                (api / "src" / "modules" / mod).mkdir(parents=True)
                (api / "src" / "modules" / mod / "service.ts").write_text(f"import {{ x }} from '../{other}/public'\n")
            (api / "package.json").write_text(json.dumps({"name": "@x/api", "dependencies": {"elysia": "^1.4.30"}}))
            (api / "tsconfig.json").write_text('{ "compilerOptions": { "strict": true } }')
            out = json.loads(bun(AUDIT, root, "--json", "--fail-on", "none").stdout)
        cycles = [f for f in out["findings"] if f["check"] == "module-cycle"]
        self.assertEqual(len(cycles), 1)
        self.assertIn("billing → notifications → billing", cycles[0]["message"])

    def test_bad_invocation(self):
        self.assertEqual(bun(AUDIT, "/nonexistent-dir-xyz").returncode, 2)
        self.assertEqual(bun(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(bun(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)


@unittest.skipUnless(BUN, "bun not installed")
class NewModuleTests(unittest.TestCase):
    def test_scaffolds_module_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = bun(NEWMOD, "team-invites", "--dir", tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            files = sorted(p.name for p in (Path(tmp) / "team-invites").iterdir())
            self.assertEqual(files, ["index.ts", "model.ts", "public.ts", "service.ts", "team-invites.test.ts"])
            index = (Path(tmp) / "team-invites" / "index.ts").read_text()
            self.assertIn("export const teamInvites = new Elysia({ name: 'module.team-invites', prefix: '/team-invites' })", index)
            service = (Path(tmp) / "team-invites" / "service.ts").read_text()
            self.assertNotIn("from 'elysia'", service)
            self.assertEqual(bun(NEWMOD, "team-invites", "--dir", tmp).returncode, 1)

    def test_rejects_bad_names(self):
        self.assertEqual(bun(NEWMOD, "Bad_Name").returncode, 2)


if __name__ == "__main__":
    unittest.main()
