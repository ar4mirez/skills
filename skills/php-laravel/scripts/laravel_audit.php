<?php

declare(strict_types=1);

/*
 * Static health check of a Laravel app: security holes, correctness traps,
 * design drift, and missing quality tooling. Standard library only (PHP 8.1+).
 *
 * Exit codes: 0 = nothing at/above --fail-on, 1 = findings at/above --fail-on,
 * 2 = bad input (missing directory, unknown option).
 */

const USAGE = <<<'TXT'
Usage: php scripts/laravel_audit.php [APP_DIR] [--json] [--fail-on high|medium|low|none]

Static health check of a Laravel app (mass assignment, raw SQL, authorization,
env() misuse, Livewire tampering, N+1 guards, queues, migrations, tooling).

Examples:
  php scripts/laravel_audit.php .
  php scripts/laravel_audit.php ~/code/acme --json --fail-on medium

Options:
  --json          Print machine-readable JSON
  --fail-on LVL   Exit 1 when a finding at/above LVL exists (default: high)
  -h, --help      Show this help

TXT;

const LEVELS = ['high' => 3, 'medium' => 2, 'low' => 1, 'none' => 99];
const RESOURCE_ACTIONS = ['__construct', '__invoke', 'index', 'show', 'create', 'store', 'edit', 'update', 'destroy', 'middleware'];

final class Audit
{
    /** @var list<array{severity: string, check: string, location: string, message: string}> */
    public array $findings = [];

    /** @var array<string, string> */
    public array $facts = [];

    /** @var array<string, string> path => contents */
    private array $php = [];

    /** @var array<string, string> */
    private array $blade = [];

    public function __construct(private readonly string $root) {}

    public function run(): void
    {
        $this->load();
        $this->composer();
        $this->envFiles();
        $this->massAssignment();
        $this->rawSql();
        $this->dangerousCalls();
        $this->envOutsideConfig();
        $this->unescapedBlade();
        $this->debugLeftovers();
        $this->controllers();
        $this->livewire();
        $this->strictModels();
        $this->csrf();
        $this->transactions();
        $this->migrations();
        $this->octane();
        $this->uploadsAndRedirects();
        $this->tooling();
        $this->strictTypes();

        usort($this->findings, fn (array $a, array $b): int => LEVELS[$b['severity']] <=> LEVELS[$a['severity']]);
    }

    private function add(string $severity, string $check, string $location, string $message): void
    {
        $this->findings[] = compact('severity', 'check', 'location', 'message');
    }

    private function load(): void
    {
        $skip = '#/(vendor|node_modules|storage|bootstrap/cache|public/build|\.git)/#';
        $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($this->root, FilesystemIterator::SKIP_DOTS));
        foreach ($it as $file) {
            $path = $file->getPathname();
            $rel = ltrim(substr($path, strlen($this->root)), '/');
            if (preg_match($skip, '/'.$rel)) {
                continue;
            }
            if (str_ends_with($rel, '.blade.php')) {
                $this->blade[$rel] = (string) file_get_contents($path);
                $this->php[$rel] = $this->blade[$rel]; // SFCs carry PHP too
            } elseif (str_ends_with($rel, '.php')) {
                $this->php[$rel] = (string) file_get_contents($path);
            }
        }
        ksort($this->php);
    }

    /** @return array<string, string> */
    private function in(string ...$prefixes): array
    {
        return array_filter($this->php, function (string $rel) use ($prefixes): bool {
            foreach ($prefixes as $p) {
                if (str_starts_with($rel, $p)) {
                    return true;
                }
            }

            return false;
        }, ARRAY_FILTER_USE_KEY);
    }

    /** Source with comments blanked (strings kept), same offsets and lines. */
    private static function code(string $src): string
    {
        $out = '';
        foreach (@token_get_all($src) as $t) {
            if (is_array($t) && in_array($t[0], [T_COMMENT, T_DOC_COMMENT], true)) {
                $out .= preg_replace('/[^\n]/', ' ', $t[1]);
            } else {
                $out .= is_array($t) ? $t[1] : $t;
            }
        }

        return $out;
    }

    private static function line(string $src, int $offset): int
    {
        return substr_count($src, "\n", 0, max(0, $offset)) + 1;
    }

    /** @return list<array{0: string, 1: int}> [match, offset] */
    private static function matches(string $pattern, string $src): array
    {
        preg_match_all($pattern, $src, $m, PREG_OFFSET_CAPTURE);

        return $m[0];
    }

    /** @return list<array{name: string, params: string, body: string, offset: int, public: bool}> */
    private static function methods(string $code): array
    {
        $out = [];
        preg_match_all('/((?:public|protected|private|static|final|\s)*)function\s+(\w+)\s*\(/', $code, $m, PREG_OFFSET_CAPTURE | PREG_SET_ORDER);
        foreach ($m as $hit) {
            $start = $hit[0][1] + strlen($hit[0][0]);
            $depth = 1;
            $i = $start;
            for (; $i < strlen($code) && $depth > 0; $i++) {
                $depth += $code[$i] === '(' ? 1 : ($code[$i] === ')' ? -1 : 0);
            }
            $params = substr($code, $start, $i - $start - 1);
            $open = strpos($code, '{', $i);
            $semi = strpos($code, ';', $i);
            if ($open === false || ($semi !== false && $semi < $open)) {
                continue; // abstract/interface
            }
            $depth = 1;
            for ($j = $open + 1; $j < strlen($code) && $depth > 0; $j++) {
                $depth += $code[$j] === '{' ? 1 : ($code[$j] === '}' ? -1 : 0);
            }
            $mods = $hit[1][0];
            $out[] = [
                'name' => $hit[2][0],
                'params' => $params,
                'body' => substr($code, $open, $j - $open),
                'offset' => $hit[2][1],
                'public' => ! str_contains($mods, 'private') && ! str_contains($mods, 'protected'),
            ];
        }

        return $out;
    }

    private function composer(): void
    {
        $file = $this->root.'/composer.json';
        if (! is_file($file)) {
            $this->add('medium', 'no-composer-json', 'composer.json', 'No composer.json found. Is this the Laravel app root?');

            return;
        }
        $json = json_decode((string) file_get_contents($file), true) ?: [];
        $require = ($json['require'] ?? []) + ($json['require-dev'] ?? []);
        $fw = $json['require']['laravel/framework'] ?? null;
        $this->facts['laravel'] = $fw ?? 'not required';
        $this->facts['php'] = $json['require']['php'] ?? 'unconstrained';

        if ($fw !== null && preg_match('/(\d+)/', $fw, $m)) {
            $major = (int) $m[1];
            if ($major <= 11) {
                $this->add('high', 'laravel-eol', 'composer.json', "laravel/framework {$fw} is past security support (11.x ended March 2026). Upgrade to 13.x, one major at a time.");
            } elseif ($major === 12) {
                $this->add('low', 'laravel-outdated', 'composer.json', "laravel/framework {$fw}: 12.x gets security fixes only (until Feb 2027). Plan the 13.x upgrade; it's usually small.");
            }
        }
        if (isset($json['require']['php']) && preg_match('/(\d+)\.(\d+)/', $json['require']['php'], $m) && ((int) $m[1] * 100 + (int) $m[2]) < 803) {
            $this->add('medium', 'php-constraint', 'composer.json', "\"php\": \"{$json['require']['php']}\" allows PHP below 8.3, which Laravel 13 rejects. Require ^8.4 or ^8.5.");
        }
        if (! isset($require['larastan/larastan']) && ! isset($require['phpstan/phpstan'])) {
            $this->add('low', 'no-static-analysis', 'composer.json', 'No Larastan/PHPStan. Add larastan/larastan and run it at level max in CI (see assets/phpstan.neon).');
        }
        if (! isset($require['pestphp/pest'])) {
            $this->add('low', 'no-pest', 'composer.json', 'Pest isn\'t installed. The house default is Pest 5 with arch presets; keep PHPUnit only for an existing large suite.');
        }
        if (isset($require['laravel/telescope']) && ! isset($json['require-dev']['laravel/telescope'])) {
            $this->add('medium', 'telescope-in-production', 'composer.json', 'laravel/telescope is a production dependency. Move it to require-dev (and register it only locally) or it records requests, queries and payloads in production.');
        }
        $this->facts['octane'] = isset($require['laravel/octane']) ? 'yes' : 'no';
    }

    private function envFiles(): void
    {
        foreach (['.env.production', '.env.example', '.env.prod'] as $name) {
            $path = $this->root.'/'.$name;
            if (! is_file($path)) {
                continue;
            }
            $lines = file($path) ?: [];
            foreach ($lines as $i => $raw) {
                $l = trim($raw);
                $loc = $name.':'.($i + 1);
                if ($name !== '.env.example' && preg_match('/^APP_DEBUG\s*=\s*(true|1)\b/i', $l)) {
                    $this->add('high', 'debug-in-production', $loc, 'APP_DEBUG=true in a production env file leaks stack traces, env values and SQL. Set APP_DEBUG=false.');
                }
                if ($name !== '.env.example' && preg_match('/^QUEUE_CONNECTION\s*=\s*sync\b/i', $l)) {
                    $this->add('medium', 'sync-queue-in-production', $loc, 'QUEUE_CONNECTION=sync runs jobs inside the request. Use database (default) or redis with a worker role.');
                }
                if (preg_match('/^APP_KEY\s*=\s*base64:\S{20,}/', $l) && $name === '.env.example') {
                    $this->add('high', 'committed-app-key', $loc, 'A real-looking APP_KEY is committed in .env.example. Rotate it (php artisan key:generate) and leave APP_KEY= empty.');
                }
            }
        }
    }

    private function massAssignment(): void
    {
        foreach ($this->in('app/', 'routes/', 'resources/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/\b(create|update|fill|forceFill|insert|updateOrCreate|firstOrCreate|firstOrNew|make)\(\s*(\$request->all\(\)|request\(\)->all\(\)|\$request->input\(\)|Request::all\(\)|\$this->all\(\))/', $code) as [$hit, $off]) {
                $this->add('high', 'mass-assignment-all', "{$rel}:".self::line($code, $off), "`{$hit}...` writes every request field. Pass `\$request->validated()` (or a typed DTO) so only validated keys reach the model.");
            }
            foreach (self::matches('/(\$guarded\s*=\s*\[\s*\]|#\[Unguarded\]|Model::unguard\(\))/', $code) as [$hit, $off]) {
                $this->add('high', 'unguarded-model', "{$rel}:".self::line($code, $off), "`{$hit}` disables mass-assignment protection. List fields with #[Fillable([...])] and fill only from validated input.");
            }
        }
    }

    private function rawSql(): void
    {
        $raw = '(DB::raw|DB::select|DB::statement|DB::unprepared|DB::update|DB::delete|DB::insert|whereRaw|orWhereRaw|selectRaw|orderByRaw|havingRaw|groupByRaw|fromRaw|joinRaw)';
        foreach ($this->in('app/', 'routes/', 'database/', 'resources/') as $rel => $src) {
            $code = self::code($src);
            $pattern = '/'.$raw.'\(\s*("[^"]*\$[^"]*"|\'[^\']*\'\s*\.\s*\$|"[^"]*"\s*\.\s*\$|\$\w+\s*\.|sprintf\()/';
            foreach (self::matches($pattern, $code) as [$hit, $off]) {
                $this->add('high', 'raw-sql-interpolation', "{$rel}:".self::line($code, $off), "`{$hit}...` builds SQL from variables (SQL injection). Use bindings: whereRaw('col = ?', [\$value]), or the query builder.");
            }
        }
    }

    private function dangerousCalls(): void
    {
        foreach ($this->in('app/', 'routes/', 'resources/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/(?<![\w>:$])(eval|shell_exec|passthru|system|exec|popen|proc_open)\s*\(\s*[^)]*\$/', $code) as [$hit, $off]) {
                $this->add('high', 'command-execution', "{$rel}:".self::line($code, $off), "`{$hit}...` runs code or shell commands built from variables. Use Process::run([...]) with an argument array, never string commands with input.");
            }
            foreach (self::matches('/(?<![\w>:$])unserialize\s*\(\s*(\$request|request\(|\$_(GET|POST|COOKIE|REQUEST))/', $code) as [$hit, $off]) {
                $this->add('high', 'unserialize-input', "{$rel}:".self::line($code, $off), "`{$hit}...` unserializes user input (object injection). Use json_decode.");
            }
        }
    }

    private function envOutsideConfig(): void
    {
        foreach ($this->in('app/', 'routes/', 'resources/', 'database/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/(?<![\w>:$])env\s*\(/', $code) as [, $off]) {
                $this->add('high', 'env-outside-config', "{$rel}:".self::line($code, $off), '`env()` outside config/ returns null once `php artisan config:cache` (optimize) runs in production. Read it in a config file and use config(\'...\') here.');
            }
        }
    }

    private function unescapedBlade(): void
    {
        foreach ($this->blade as $rel => $src) {
            foreach (self::matches('/\{!!\s*(.+?)\s*!!\}/s', $src) as [$hit, $off]) {
                if (! str_contains($hit, '$') && ! str_contains($hit, 'request(') && ! str_contains($hit, 'old(')) {
                    continue;
                }
                $userish = preg_match('/request\(|\$request|old\(|->input\(|\$_(GET|POST)/', $hit) === 1;
                $this->add($userish ? 'high' : 'medium', 'unescaped-output', "{$rel}:".self::line($src, $off), "`{$hit}` prints unescaped HTML (XSS if the value is ever user-controlled). Use {{ }} or sanitize to an HtmlString you trust.");
            }
        }
    }

    private function debugLeftovers(): void
    {
        foreach ($this->in('app/', 'routes/', 'resources/', 'database/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/(?<![\w>:$])(dd|dump|ray|var_dump|print_r|die|ddd)\s*\(|@(dd|dump)\b/', $code) as [$hit, $off]) {
                $this->add('medium', 'debug-leftover', "{$rel}:".self::line($code, $off), "`{$hit}` is a debugging leftover. Remove it (an arch test `->not->toBeUsed()` keeps it out).");
            }
        }
    }

    private function controllers(): void
    {
        foreach ($this->in('app/Http/Controllers/') as $rel => $src) {
            $code = self::code($src);
            if (preg_match('/abstract\s+class/', $code)) {
                continue;
            }
            if (preg_match('/\bDB::/', $code, $m, PREG_OFFSET_CAPTURE)) {
                $this->add('medium', 'db-in-controller', "{$rel}:".self::line($code, $m[0][1]), 'Controller uses the DB facade. Move queries and transactions into an action (app/Actions) or a model scope.');
            }
            foreach (self::matches('/(\$request->validate\(|Validator::make\(|\$this->validate\()/', $code) as [$hit, $off]) {
                $this->add('low', 'inline-validation', "{$rel}:".self::line($code, $off), "`{$hit}` validates inline. Use a Form Request: it authorizes, validates, and keeps the controller one call long.");
            }
            foreach (self::matches('/\b[A-Z]\w*::all\(\)/', $code) as [$hit, $off]) {
                $this->add('medium', 'unbounded-query', "{$rel}:".self::line($code, $off), "`{$hit}` loads the whole table. Paginate (paginate/cursorPaginate) and scope to the tenant.");
            }
            foreach (self::methods($code) as $m) {
                if (! $m['public'] || str_starts_with($m['name'], '__')) {
                    continue;
                }
                $loc = "{$rel}:".self::line($code, $m['offset']);
                if (! in_array($m['name'], RESOURCE_ACTIONS, true)) {
                    $this->add('medium', 'non-resourceful-action', $loc, "Public action `{$m['name']}` isn't a resource action. Model the verb as its own resource controller (e.g. InvoicePaymentController@store).");
                }
                $this->controllerAuthorization($rel, $code, $m, $loc);
            }
        }
    }

    /** @param array{name: string, params: string, body: string, offset: int, public: bool} $m */
    private function controllerAuthorization(string $rel, string $code, array $m, string $loc): void
    {
        $models = [];
        preg_match_all('/\b([A-Z]\w*)\s+\$(\w+)/', $m['params'], $pm, PREG_SET_ORDER);
        foreach ($pm as [, $type]) {
            if (! preg_match('/(Request|User|Action|Service|Command|Query|Data|Dto|Factory|Manager|Collection|Builder|Closure|Carbon\w*|Create\w+|Record\w+|Update\w+|Delete\w+)$/', $type)
                && ! in_array($type, ['Request', 'string', 'int', 'array', 'bool', 'float', 'mixed', 'self'], true)) {
                $models[] = $type;
            }
        }
        $formRequest = preg_match('/\b\w+Request\s+\$/', $m['params']) === 1 && ! preg_match('/\bRequest\s+\$/', $m['params']);
        $hasAuth = preg_match('/authorize\(|Gate::|->can\(|->cannot\(|policy\(|abort_(if|unless)\(/', $m['body']) === 1;
        $attr = preg_match('/#\[(Authorize|Can|Middleware\([\'"]can:)/', substr($code, max(0, $m['offset'] - 300), 300)) === 1;
        $classAttr = preg_match('/#\[(Authorize|Middleware\([\'"]can:)[^\]]*\]\s*(final\s+)?class/', $code) === 1;
        if ($models !== [] && ! $formRequest && ! $hasAuth && ! $attr && ! $classAttr) {
            $this->add('medium', 'missing-authorization', $loc, '`'.$m['name'].'` receives '.implode(', ', $models).' but never authorizes. Add Gate::authorize(\'...\', $model), a Form Request with authorize(), or #[Authorize(...)].');
        }
        if (preg_match('/\b([A-Z]\w*)::(find|findOrFail|where)\(\s*\$(request|id|\w+Id)\b/', $m['body'], $fm) && ! $hasAuth && ! $formRequest) {
            $this->add('medium', 'unscoped-find', $loc, "`{$fm[0]}...` loads by an id from the request without tenant scoping or a policy check (IDOR). Scope through the owner (\$user->account->invoices()->findOrFail(...)) and authorize.");
        }
    }

    private function livewire(): void
    {
        foreach ($this->php as $rel => $src) {
            if (! preg_match('/extends\s+Component\b/', $src) || ! str_contains($src, 'Livewire')) {
                continue;
            }
            $code = self::code($src);
            foreach (self::methods($code) as $m) {
                if (! $m['public'] || str_starts_with($m['name'], '__') || in_array($m['name'], ['mount', 'render', 'boot', 'hydrate', 'dehydrate', 'rules'], true)) {
                    continue;
                }
                $takesId = preg_match('/\$(id|\w+Id)\b/', $m['params']) === 1;
                $loads = preg_match('/::(find|findOrFail|whereKey)\(|->find(OrFail)?\(/', $m['body']) === 1;
                $auth = preg_match('/authorize\(|Gate::|->can\(|abort_(if|unless)\(/', $m['body']) === 1;
                if ($takesId && $loads && ! $auth) {
                    $this->add('high', 'livewire-unauthorized-action', "{$rel}:".self::line($code, $m['offset']), "Livewire action `{$m['name']}` loads a record from a browser-supplied id without authorizing. Any user can call it with any id: re-query and \$this->authorize(...) first.");
                }
            }
            foreach (self::matches('/public\s+(int|string|\?int|\?string)\s+\$(\w*[iI]d)\b/', $code) as [$hit, $off]) {
                $before = substr($code, max(0, $off - 80), 80);
                if (! str_contains($before, '#[Locked]')) {
                    $this->add('medium', 'livewire-unlocked-id', "{$rel}:".self::line($code, $off), "`{$hit}` is a public id the browser can change. Mark it #[Locked] (and still authorize in actions).");
                }
            }
        }
    }

    private function strictModels(): void
    {
        $providers = implode("\n", $this->in('app/Providers/', 'bootstrap/'));
        if ($this->in('app/Models/') !== [] && ! preg_match('/shouldBeStrict\(|preventLazyLoading\(/', $providers)) {
            $this->add('medium', 'no-strict-models', 'app/Providers/AppServiceProvider.php', 'Eloquent strict mode is off. Add Model::shouldBeStrict(! $this->app->isProduction()) so N+1 queries, missing attributes and dropped mass-assignment fail in dev and tests.');
        }
        if ($this->in('app/Models/') !== [] && ! str_contains($providers, 'prohibitDestructiveCommands')) {
            $this->add('low', 'destructive-commands-allowed', 'app/Providers/AppServiceProvider.php', 'Add DB::prohibitDestructiveCommands($this->app->isProduction()) so migrate:fresh / db:wipe can\'t run against production.');
        }
    }

    private function csrf(): void
    {
        foreach ($this->in('bootstrap/', 'app/Http/', 'routes/') as $rel => $src) {
            $code = self::code($src);
            if (preg_match('/(validateCsrfTokens|preventRequestForgery)\(\s*except:\s*\[[^\]]*[\'"]\*[\'"]/', $code, $m, PREG_OFFSET_CAPTURE)
                || preg_match('/\$except\s*=\s*\[[^\]]*[\'"]\*[\'"]/', $code, $m, PREG_OFFSET_CAPTURE)) {
                $this->add('high', 'csrf-disabled', "{$rel}:".self::line($code, $m[0][1]), 'CSRF protection is disabled for every route. Exclude only the specific webhook URIs (and verify their signatures).');
            }
            foreach (self::matches('/\b(VerifyCsrfToken|ValidateCsrfToken)\b/', $code) as [$hit, $off]) {
                $this->add('low', 'deprecated-csrf-middleware', "{$rel}:".self::line($code, $off), "`{$hit}` is a deprecated alias in Laravel 13. Reference PreventRequestForgery instead.");
            }
        }
    }

    private function transactions(): void
    {
        $afterCommitGlobally = false;
        $queueConfig = $this->root.'/config/queue.php';
        if (is_file($queueConfig)) {
            $afterCommitGlobally = preg_match('/[\'"]after_commit[\'"]\s*=>\s*true/', (string) file_get_contents($queueConfig)) === 1;
        }
        foreach ($this->in('app/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/DB::transaction\(/', $code) as [, $off]) {
                $open = strpos($code, '{', $off);
                if ($open === false) {
                    continue;
                }
                $depth = 1;
                for ($j = $open + 1; $j < strlen($code) && $depth > 0; $j++) {
                    $depth += $code[$j] === '{' ? 1 : ($code[$j] === '}' ? -1 : 0);
                }
                $body = substr($code, $open, $j - $open);
                preg_match_all('/\b([A-Z]\w*)::dispatch(Sync)?\(|\bdispatch\(\s*new\s+([A-Z]\w*)|\bevent\(\s*new\s+([A-Z]\w*)|\b(Mail|Notification)::(send|to)\b|->notify\(/', $body, $hits, PREG_SET_ORDER);
                foreach ($hits as $h) {
                    if (($h[2] ?? '') === 'Sync') {
                        continue;
                    }
                    $class = $h[1] ?: ($h[3] ?? '') ?: ($h[4] ?? '');
                    if ($class !== '' && ($afterCommitGlobally || $this->classCommitsAfter($class))) {
                        continue;
                    }
                    $what = $class !== '' ? $class : trim($h[0]);
                    $this->add('medium', 'side-effect-in-transaction', "{$rel}:".self::line($code, $off), "`{$what}` fires inside DB::transaction. If the transaction rolls back, the job/mail/event has already escaped, and workers may read uncommitted rows. Implement ShouldDispatchAfterCommit / ShouldQueueAfterCommit or call ->afterCommit().");
                }
            }
        }
    }

    private function classCommitsAfter(string $class): bool
    {
        foreach ($this->in('app/') as $rel => $src) {
            if (basename($rel) === $class.'.php') {
                return preg_match('/ShouldDispatchAfterCommit|ShouldQueueAfterCommit|afterCommit\s*=\s*true|->afterCommit\(\)/', $src) === 1;
            }
        }

        return false;
    }

    private function migrations(): void
    {
        foreach ($this->in('database/migrations/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/(foreignId|foreignUuid|foreignUlid|unsignedBigInteger|foreignIdFor)\(\s*([^)]*)\)([^;]*);/', $code) as [$hit, $off]) {
                preg_match('/(foreignId|foreignUuid|foreignUlid|unsignedBigInteger|foreignIdFor)\(\s*([^)]*)\)([^;]*);/', $hit, $p);
                $col = trim($p[2], " '\"");
                if ($p[1] === 'foreignIdFor') {
                    $col = strtolower((string) preg_replace('/(?<!^)[A-Z]/', '_$0', (string) preg_replace('/^.*\\\\|::class.*$/', '', $col))).'_id';
                }
                if ($p[1] === 'unsignedBigInteger' && ! str_ends_with($col, '_id')) {
                    continue;
                }
                if (str_contains($p[3], '->index(') || str_contains($p[3], '->unique(') || str_contains($p[3], '->primary(')) {
                    continue;
                }
                $quoted = preg_quote($col, '/');
                if (preg_match('/(index|unique|primary)\(\s*\[\s*[\'"]'.$quoted.'[\'"]|(index|unique)\(\s*[\'"]'.$quoted.'[\'"]/', $code)) {
                    continue;
                }
                $this->add('medium', 'unindexed-foreign-key', "{$rel}:".self::line($code, $off), "`{$col}` has no index starting with it. constrained() adds the FK but PostgreSQL doesn't index it: add ->index(), or lead a composite index with it.");
            }
            foreach (self::matches('/->(renameColumn|dropColumn|change)\(/', $code) as [$hit, $off]) {
                $this->add('low', 'risky-migration', "{$rel}:".self::line($code, $off), "`{$hit}` on a live table breaks running code during deploy. Expand/contract: add the new column, backfill in a job, switch reads, drop later.");
            }
        }
    }

    private function octane(): void
    {
        if (($this->facts['octane'] ?? 'no') !== 'yes') {
            return;
        }
        foreach ($this->in('app/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/(?:private|protected|public)\s+static\s+(?:\??[\w\\\\]+\s+)?\$\w+\s*=\s*\[|\bstatic\s+\$\w+\s*(=|;)/', $code) as [$hit, $off]) {
                $this->add('medium', 'octane-static-state', "{$rel}:".self::line($code, $off), "`".trim($hit)."` keeps state across requests under Octane (it leaks between users). Use request-scoped bindings (\$this->app->scoped()) or Context.");
            }
            foreach (self::matches('/->singleton\([^;]*?(request\(\)|Request::|auth\(\)|Auth::)/s', $code) as [, $off]) {
                $this->add('medium', 'octane-singleton-request', "{$rel}:".self::line($code, $off), 'A singleton captures the request or auth user. Under Octane the first request\'s value is reused forever. Use scoped() or resolve per call.');
            }
        }
    }

    private function uploadsAndRedirects(): void
    {
        foreach ($this->in('app/', 'routes/') as $rel => $src) {
            $code = self::code($src);
            foreach (self::matches('/(storeAs|move|putFileAs)\([^;]*getClientOriginalName\(\)/', $code) as [, $off]) {
                $this->add('medium', 'upload-client-filename', "{$rel}:".self::line($code, $off), 'Stores an upload under the client-supplied filename (overwrites, path tricks, stored XSS via .html). Use store() (random name) and keep the original name as data.');
            }
            foreach (self::matches('/(redirect\(\)->(to|away)\(|redirect\()\s*(\$request->(input|get|query)|request\()/', $code) as [$hit, $off]) {
                $this->add('medium', 'open-redirect', "{$rel}:".self::line($code, $off), "`{$hit}...` redirects to a user-supplied URL (open redirect). Use redirect()->intended() or validate against an allow-list.");
            }
        }
    }

    private function tooling(): void
    {
        $has = fn (string ...$names): bool => array_reduce($names, fn (bool $c, string $n): bool => $c || file_exists($this->root.'/'.$n), false);
        if (! $has('phpstan.neon', 'phpstan.neon.dist', 'phpstan.dist.neon')) {
            $this->add('low', 'no-phpstan-config', 'phpstan.neon', 'No PHPStan config. Copy assets/phpstan.neon (Larastan, level max) and gate CI on it.');
        }
        if (! $has('pint.json')) {
            $this->add('low', 'no-pint-config', 'pint.json', 'No pint.json. Copy assets/pint.json (laravel preset + strict types, final classes, strict comparison).');
        }
        $tests = implode("\n", $this->in('tests/'));
        if ($tests !== '' && ! str_contains($tests, 'arch(')) {
            $this->add('low', 'no-arch-tests', 'tests/', 'No Pest arch tests. Add assets/ArchTest.php (php/security/laravel presets + layering rules) so conventions are enforced, not remembered.');
        }
        if ($tests !== '' && str_contains($tests, 'Http::fake') && ! str_contains($tests, 'preventStrayRequests')) {
            $this->add('low', 'stray-http-allowed', 'tests/Pest.php', 'Tests fake HTTP but allow stray requests. Call Http::preventStrayRequests() in tests/Pest.php so an unfaked call fails instead of hitting the network.');
        }
        if ($tests === '' && $this->in('app/') !== []) {
            $this->add('medium', 'no-tests', 'tests/', 'No tests found. Start with Pest feature tests for the HTTP contract and tenant isolation.');
        }
    }

    private function strictTypes(): void
    {
        $missing = [];
        foreach ($this->in('app/') as $rel => $src) {
            if (! str_ends_with($rel, '.blade.php') && ! preg_match('/declare\s*\(\s*strict_types\s*=\s*1\s*\)/', $src)) {
                $missing[] = $rel;
            }
        }
        if ($missing !== []) {
            $this->add('low', 'missing-strict-types', $missing[0], count($missing).' file(s) in app/ lack declare(strict_types=1) (first: '.$missing[0].'). Pint\'s declare_strict_types rule adds it everywhere.');
        }
    }
}

// ---- CLI -------------------------------------------------------------------

$args = array_slice($argv, 1);
$json = false;
$failOn = 'high';
$dir = null;
for ($i = 0; $i < count($args); $i++) {
    $a = $args[$i];
    if ($a === '-h' || $a === '--help') {
        fwrite(STDOUT, USAGE);
        exit(0);
    } elseif ($a === '--json') {
        $json = true;
    } elseif ($a === '--fail-on' || str_starts_with($a, '--fail-on=')) {
        $failOn = str_contains($a, '=') ? substr($a, 10) : ($args[++$i] ?? '');
        if (! isset(LEVELS[$failOn])) {
            fwrite(STDERR, "Error: --fail-on must be one of high, medium, low, none (got '{$failOn}').\n");
            exit(2);
        }
    } elseif (str_starts_with($a, '-')) {
        fwrite(STDERR, "Error: unknown option {$a}\n\n".USAGE);
        exit(2);
    } else {
        $dir = $a;
    }
}
$dir ??= '.';
$root = realpath($dir);
if ($root === false || ! is_dir($root)) {
    fwrite(STDERR, "Error: {$dir} is not a directory.\n");
    exit(2);
}

$audit = new Audit($root);
$audit->run();

if ($json) {
    echo json_encode(['facts' => $audit->facts, 'findings' => $audit->findings], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
} else {
    echo "Laravel audit: {$root}\n";
    echo 'laravel/framework '.($audit->facts['laravel'] ?? '?').' · php '.($audit->facts['php'] ?? '?').' · octane '.($audit->facts['octane'] ?? 'no')."\n";
    if ($audit->findings === []) {
        echo "\nNo findings.\n";
    }
    foreach (['high', 'medium', 'low'] as $level) {
        $group = array_filter($audit->findings, fn (array $f): bool => $f['severity'] === $level);
        if ($group === []) {
            continue;
        }
        echo "\n".strtoupper($level).' ('.count($group).")\n";
        foreach ($group as $f) {
            echo "  [{$f['check']}] {$f['location']}: {$f['message']}\n";
        }
    }
}

$threshold = LEVELS[$failOn];
foreach ($audit->findings as $f) {
    if (LEVELS[$f['severity']] >= $threshold) {
        exit(1);
    }
}
exit(0);
