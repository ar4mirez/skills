<?php

declare(strict_types=1);

namespace App\Providers;

use Carbon\CarbonImmutable;
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\Facades\URL;
use Illuminate\Support\ServiceProvider;
use Illuminate\Validation\Rules\Password;

final class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        //
    }

    public function boot(): void
    {
        $production = $this->app->isProduction();

        // Fail loudly outside production: N+1s, typos in attribute names, silent mass-assignment drops.
        // Don't add automaticallyEagerLoadRelationships(): it silently batches lazy loads, so N+1s never fail.
        Model::shouldBeStrict(! $production);

        // No `migrate:fresh` / `db:wipe` against production by accident.
        DB::prohibitDestructiveCommands($production);

        Date::use(CarbonImmutable::class);

        if ($production) {
            URL::forceHttps();
        }

        Password::defaults(fn () => $production
            ? Password::min(12)->uncompromised()
            : Password::min(8));

        RateLimiter::for('api', fn (Request $request) => Limit::perMinute(120)
            ->by((string) ($request->user()->id ?? $request->ip())));
    }
}
