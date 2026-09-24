"""Tests for skills/php-laravel/scripts (run: make test). Skipped when PHP isn't installed."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "php-laravel"
AUDIT = SKILL / "scripts" / "laravel_audit.php"
SCAFFOLD = SKILL / "scripts" / "scaffold_resource.php"
FLAWED = SKILL / "evals" / "files" / "flawed_app"
PHP = shutil.which("php")


def run(*args, cwd=None):
    return subprocess.run([PHP, *map(str, args)], capture_output=True, text=True, cwd=cwd)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


CLEAN_PROVIDER = """<?php

declare(strict_types=1);

namespace App\\Providers;

use Illuminate\\Database\\Eloquent\\Model;
use Illuminate\\Support\\Facades\\DB;
use Illuminate\\Support\\ServiceProvider;

final class AppServiceProvider extends ServiceProvider
{
    public function boot(): void
    {
        Model::shouldBeStrict(! $this->app->isProduction());
        DB::prohibitDestructiveCommands($this->app->isProduction());
    }
}
"""


@unittest.skipUnless(PHP, "php not installed")
class LaravelAuditTests(unittest.TestCase):
    def findings(self, root=FLAWED, *extra):
        res = run(AUDIT, root, "--json", *extra)
        return res.returncode, json.loads(res.stdout)["findings"]

    def test_flawed_app_findings(self):
        code, findings = self.findings()
        self.assertEqual(code, 1)  # high-severity findings exist
        checks = {f["check"] for f in findings}
        for expected in (
            "laravel-eol", "debug-in-production", "sync-queue-in-production", "mass-assignment-all",
            "unguarded-model", "raw-sql-interpolation", "env-outside-config", "unescaped-output",
            "livewire-unauthorized-action", "livewire-unlocked-id", "csrf-disabled", "php-constraint",
            "telescope-in-production", "debug-leftover", "db-in-controller", "unbounded-query",
            "missing-authorization", "non-resourceful-action", "unscoped-find", "no-strict-models",
            "side-effect-in-transaction", "unindexed-foreign-key", "octane-static-state",
            "upload-client-filename", "open-redirect", "inline-validation", "risky-migration",
            "no-static-analysis", "no-pest", "no-arch-tests", "stray-http-allowed", "missing-strict-types",
        ):
            self.assertIn(expected, checks)

    def test_composite_index_covers_fk(self):
        _, findings = self.findings()
        fks = [f["message"] for f in findings if f["check"] == "unindexed-foreign-key"]
        self.assertEqual(len(fks), 1)  # account_id leads a composite index; only customer_id is flagged
        self.assertIn("customer_id", fks[0])

    def test_unescaped_severity_depends_on_source(self):
        _, findings = self.findings()
        sev = {f["message"].split("`")[1]: f["severity"] for f in findings if f["check"] == "unescaped-output"}
        self.assertEqual(sev["{!! request('q') !!}"], "high")
        self.assertEqual(sev["{!! $invoice->notes !!}"], "medium")

    def test_resource_actions_not_flagged(self):
        _, findings = self.findings()
        actions = sorted(f["message"].split("`")[1] for f in findings if f["check"] == "non-resourceful-action")
        self.assertEqual(actions, ["export", "markPaid", "search"])

    def test_clean_app_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "composer.json", json.dumps({
                "require": {"php": "^8.5", "laravel/framework": "^13.0"},
                "require-dev": {"pestphp/pest": "^5.2", "larastan/larastan": "^3.12"},
            }))
            write(root, "phpstan.neon", "parameters:\n    level: max\n")
            write(root, "pint.json", "{}\n")
            write(root, "app/Providers/AppServiceProvider.php", CLEAN_PROVIDER)
            write(root, "app/Models/Invoice.php", "<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Models;\n\n#[\\Illuminate\\Database\\Eloquent\\Attributes\\Fillable(['number'])]\nfinal class Invoice extends \\Illuminate\\Database\\Eloquent\\Model {}\n")
            write(root, "app/Http/Controllers/Api/InvoiceController.php", """<?php

declare(strict_types=1);

namespace App\\Http\\Controllers\\Api;

use App\\Models\\Invoice;
use Illuminate\\Support\\Facades\\Gate;

final class InvoiceController
{
    public function show(Invoice $invoice): Invoice
    {
        Gate::authorize('view', $invoice);

        return $invoice;
    }
}
""")
            write(root, "database/migrations/2026_01_01_000000_create_invoices.php",
                  "<?php\nSchema::create('invoices', function ($table) {\n    $table->foreignId('account_id')->index()->constrained();\n});\n")
            write(root, "tests/ArchTest.php", "<?php\narch()->preset()->laravel();\n")
            code, findings = self.findings(root)
        self.assertEqual(code, 0)
        self.assertEqual(findings, [])

    def test_after_commit_class_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "composer.json", json.dumps({"require": {"laravel/framework": "^13.0"}}))
            write(root, "app/Events/InvoicePaid.php",
                  "<?php\nfinal class InvoicePaid implements \\Illuminate\\Contracts\\Events\\ShouldDispatchAfterCommit {}\n")
            write(root, "app/Actions/RecordPayment.php",
                  "<?php\nfinal readonly class RecordPayment { public function handle(): void { DB::transaction(function () { InvoicePaid::dispatch(); SendMail::dispatch(); }); } }\n")
            _, findings = self.findings(root, "--fail-on", "none")
        flagged = [f["message"] for f in findings if f["check"] == "side-effect-in-transaction"]
        self.assertEqual(len(flagged), 1)
        self.assertIn("SendMail", flagged[0])

    def test_fail_on_levels_and_bad_input(self):
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "none").returncode, 0)
        self.assertEqual(run(AUDIT, FLAWED, "--fail-on", "bogus").returncode, 2)
        self.assertEqual(run(AUDIT, "/definitely/not/here").returncode, 2)
        self.assertEqual(run(AUDIT, "--nope").returncode, 2)
        helped = run(AUDIT, "--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("Usage:", helped.stdout)

    def test_text_report(self):
        res = run(AUDIT, FLAWED)
        self.assertIn("HIGH (", res.stdout)
        self.assertIn("[mass-assignment-all]", res.stdout)


@unittest.skipUnless(PHP, "php not installed")
class ScaffoldTests(unittest.TestCase):
    def app(self, tmp):
        root = Path(tmp)
        (root / "artisan").write_text("<?php\n")
        return root

    def test_writes_slice_and_lints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.app(tmp)
            res = run(SCAFFOLD, "Catalog", "Product", "--root", root)
            self.assertEqual(res.returncode, 0, res.stderr)
            expected = [
                "app/Actions/Catalog/CreateProduct.php",
                "app/Http/Requests/Catalog/StoreProductRequest.php",
                "app/Policies/ProductPolicy.php",
                "app/Http/Resources/ProductResource.php",
                "app/Http/Controllers/Api/ProductController.php",
                "tests/Feature/Catalog/ProductApiTest.php",
            ]
            for rel in expected:
                path = root / rel
                self.assertTrue(path.is_file(), rel)
                self.assertEqual(run("-l", path).returncode, 0, rel)
                self.assertIn("declare(strict_types=1);", path.read_text())
            self.assertIn("Route::apiResource('products'", res.stdout)
            self.assertIn("return $account->products()->create($attributes);",
                          (root / expected[0]).read_text())
            # generated code passes our own audit
            audit = json.loads(run(AUDIT, root, "--json", "--fail-on", "none").stdout)
            bad = [f for f in audit["findings"] if f["severity"] in ("high", "medium") and f["check"] != "no-composer-json"]
            self.assertEqual(bad, [])

    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.app(tmp)
            self.assertEqual(run(SCAFFOLD, "Billing", "Invoice", "--root", root).returncode, 0)
            self.assertEqual(run(SCAFFOLD, "Billing", "Invoice", "--root", root).returncode, 1)
            self.assertEqual(run(SCAFFOLD, "Billing", "Invoice", "--root", root, "--force").returncode, 0)

    def test_dry_run_and_pluralization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.app(tmp)
            res = run(SCAFFOLD, "Catalog", "Category", "--root", root, "--dry-run")
            self.assertEqual(res.returncode, 0)
            self.assertIn("would write app/Actions/Catalog/CreateCategory.php", res.stdout)
            self.assertIn("'categories'", res.stdout)
            self.assertFalse((root / "app").exists())

    def test_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.app(tmp)
            self.assertEqual(run(SCAFFOLD, "catalog", "Product", "--root", root).returncode, 2)
            self.assertEqual(run(SCAFFOLD, "Catalog", "--root", root).returncode, 2)
            self.assertEqual(run(SCAFFOLD, "Catalog", "Product", "--root", tmp + "/missing").returncode, 2)
            self.assertEqual(run(SCAFFOLD, "--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
