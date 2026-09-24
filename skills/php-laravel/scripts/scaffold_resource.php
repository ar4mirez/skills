<?php

declare(strict_types=1);

/*
 * Scaffold an opinionated, tenant-scoped API resource slice in a Laravel app:
 * action, form request, policy, JSON resource, controller, and Pest test.
 * The model (with account_id, a factory, and a migration) must already exist.
 * Standard library only (PHP 8.1+).
 *
 * Exit codes: 0 = files written (or would be, with --dry-run),
 * 1 = refused (a file exists; pass --force), 2 = bad input.
 */

const USAGE = <<<'TXT'
Usage: php scripts/scaffold_resource.php <Context> <Model> [--root DIR] [--dry-run] [--force]

Writes, under the app root (default: current directory):
  app/Actions/<Context>/Create<Model>.php
  app/Http/Requests/<Context>/Store<Model>Request.php
  app/Policies/<Model>Policy.php
  app/Http/Resources/<Model>Resource.php
  app/Http/Controllers/Api/<Model>Controller.php
  tests/Feature/<Context>/<Model>ApiTest.php
and prints the route line to add to routes/api.php.

Assumes App\Models\<Model> exists with an account_id column and a factory,
and that users belong to an account (App\Models\User::$account_id).

Examples:
  php scripts/scaffold_resource.php Catalog Product --root ~/code/acme
  php scripts/scaffold_resource.php Billing Invoice --dry-run

TXT;

$args = array_slice($argv, 1);
$root = '.';
$dryRun = false;
$force = false;
$positional = [];
for ($i = 0; $i < count($args); $i++) {
    $a = $args[$i];
    match (true) {
        $a === '-h' || $a === '--help' => (function (): never { fwrite(STDOUT, USAGE); exit(0); })(),
        $a === '--dry-run' => $dryRun = true,
        $a === '--force' => $force = true,
        $a === '--root' => $root = $args[++$i] ?? '',
        str_starts_with($a, '--root=') => $root = substr($a, 7),
        str_starts_with($a, '-') => (function () use ($a): never { fwrite(STDERR, "Error: unknown option {$a}\n\n".USAGE); exit(2); })(),
        default => $positional[] = $a,
    };
}

if (count($positional) !== 2) {
    fwrite(STDERR, "Error: expected <Context> <Model>.\n\n".USAGE);
    exit(2);
}
[$context, $model] = $positional;
foreach (['Context' => $context, 'Model' => $model] as $label => $value) {
    if (! preg_match('/^[A-Z][A-Za-z0-9]*$/', $value)) {
        fwrite(STDERR, "Error: {$label} must be StudlyCase (got '{$value}').\n");
        exit(2);
    }
}
$base = realpath($root);
if ($base === false || ! is_file($base.'/artisan')) {
    fwrite(STDERR, "Error: {$root} is not a Laravel app root (no artisan file).\n");
    exit(2);
}

$var = lcfirst($model);
$snake = strtolower((string) preg_replace('/(?<!^)[A-Z]/', '_$0', $model));
$plural = str_ends_with($snake, 'y') ? substr($snake, 0, -1).'ies' : (preg_match('/(s|x|ch|sh)$/', $snake) ? $snake.'es' : $snake.'s');
$uri = str_replace('_', '-', $plural);

$files = [];

$files["app/Actions/{$context}/Create{$model}.php"] = <<<PHP
<?php

declare(strict_types=1);

namespace App\\Actions\\{$context};

use App\\Models\\Account;
use App\\Models\\{$model};

final readonly class Create{$model}
{
    /** @param array<string, mixed> \$attributes validated input only */
    public function handle(Account \$account, array \$attributes): {$model}
    {
        return \$account->{$plural}()->create(\$attributes);
    }
}

PHP;

$files["app/Http/Requests/{$context}/Store{$model}Request.php"] = <<<PHP
<?php

declare(strict_types=1);

namespace App\\Http\\Requests\\{$context};

use App\\Models\\{$model};
use Illuminate\\Contracts\\Validation\\ValidationRule;
use Illuminate\\Foundation\\Http\\FormRequest;

final class Store{$model}Request extends FormRequest
{
    public function authorize(): bool
    {
        return \$this->user()?->can('create', {$model}::class) ?? false;
    }

    /** @return array<string, ValidationRule|array<mixed>|string> */
    public function rules(): array
    {
        return [
            // TODO: one rule per fillable attribute, e.g. 'name' => ['required', 'string', 'max:255'],
        ];
    }
}

PHP;

$files["app/Policies/{$model}Policy.php"] = <<<PHP
<?php

declare(strict_types=1);

namespace App\\Policies;

use App\\Models\\{$model};
use App\\Models\\User;

final class {$model}Policy
{
    public function viewAny(User \$user): bool
    {
        return \$user->account_id !== null;
    }

    public function view(User \$user, {$model} \${$var}): bool
    {
        return \$user->account_id === \${$var}->account_id;
    }

    public function create(User \$user): bool
    {
        return \$user->account_id !== null;
    }
}

PHP;

$files["app/Http/Resources/{$model}Resource.php"] = <<<PHP
<?php

declare(strict_types=1);

namespace App\\Http\\Resources;

use App\\Models\\{$model};
use Illuminate\\Http\\Request;
use Illuminate\\Http\\Resources\\Json\\JsonResource;

/** @mixin {$model} */
final class {$model}Resource extends JsonResource
{
    /** @return array<string, mixed> */
    public function toArray(Request \$request): array
    {
        return [
            'id' => \$this->id,
            // TODO: list the public fields explicitly; never return the raw model.
        ];
    }
}

PHP;

$files["app/Http/Controllers/Api/{$model}Controller.php"] = <<<PHP
<?php

declare(strict_types=1);

namespace App\\Http\\Controllers\\Api;

use App\\Actions\\{$context}\\Create{$model};
use App\\Http\\Controllers\\Controller;
use App\\Http\\Requests\\{$context}\\Store{$model}Request;
use App\\Http\\Resources\\{$model}Resource;
use App\\Models\\{$model};
use App\\Models\\User;
use Illuminate\\Container\\Attributes\\CurrentUser;
use Illuminate\\Http\\Resources\\Json\\AnonymousResourceCollection;
use Illuminate\\Support\\Facades\\Gate;

final class {$model}Controller extends Controller
{
    public function index(#[CurrentUser] User \$user): AnonymousResourceCollection
    {
        Gate::authorize('viewAny', {$model}::class);

        return {$model}Resource::collection(
            {$model}::query()->where('account_id', \$user->account_id)->latest('id')->cursorPaginate(25),
        );
    }

    public function store(Store{$model}Request \$request, #[CurrentUser] User \$user, Create{$model} \$create{$model}): {$model}Resource
    {
        return {$model}Resource::make(\$create{$model}->handle(\$user->account()->firstOrFail(), \$request->validated()));
    }

    public function show({$model} \${$var}): {$model}Resource
    {
        Gate::authorize('view', \${$var});

        return {$model}Resource::make(\${$var});
    }
}

PHP;

$files["tests/Feature/{$context}/{$model}ApiTest.php"] = <<<PHP
<?php

declare(strict_types=1);

use App\\Models\\{$model};
use App\\Models\\User;
use Laravel\\Sanctum\\Sanctum;

use function Pest\\Laravel\\getJson;

it('rejects guests', function (): void {
    getJson('/api/{$uri}')->assertUnauthorized();
});

it('lists only the current account\'s {$plural}', function (): void {
    \$user = User::factory()->create();
    {$model}::factory()->for(\$user->account)->count(2)->create();
    {$model}::factory()->create();

    Sanctum::actingAs(\$user);

    getJson('/api/{$uri}')->assertOk()->assertJsonCount(2, 'data');
});

it('forbids reading another account\'s {$snake}', function (): void {
    Sanctum::actingAs(User::factory()->create());

    getJson('/api/{$uri}/'.{$model}::factory()->create()->id)->assertForbidden();
});

it('creates a {$snake} from validated input', function (): void {
    // TODO: post a valid payload and assert the created resource.
})->todo();

PHP;

$conflicts = array_filter(array_keys($files), fn (string $rel): bool => is_file($base.'/'.$rel));
if ($conflicts !== [] && ! $force) {
    fwrite(STDERR, "Refusing to overwrite (pass --force):\n  ".implode("\n  ", $conflicts)."\n");
    exit(1);
}

foreach ($files as $rel => $contents) {
    $path = $base.'/'.$rel;
    echo ($dryRun ? 'would write ' : 'wrote ').$rel."\n";
    if ($dryRun) {
        continue;
    }
    if (! is_dir(dirname($path)) && ! mkdir(dirname($path), 0o755, true) && ! is_dir(dirname($path))) {
        fwrite(STDERR, "Error: cannot create ".dirname($path)."\n");
        exit(2);
    }
    file_put_contents($path, $contents);
}

$modelFile = $base."/app/Models/{$model}.php";
if (! is_file($modelFile)) {
    echo "\nnote: app/Models/{$model}.php doesn't exist yet: php artisan make:model {$model} -mf, with an account_id column.\n";
}

echo <<<TXT

Next:
  1. routes/api.php, inside the auth:sanctum group:
       Route::apiResource('{$uri}', \\App\\Http\\Controllers\\Api\\{$model}Controller::class)->only(['index', 'store', 'show']);
  2. Account model: public function {$plural}(): HasMany { return \$this->hasMany({$model}::class); }
  3. Fill the TODOs (rules, resource fields, the store test), then: composer check

TXT;
exit(0);
