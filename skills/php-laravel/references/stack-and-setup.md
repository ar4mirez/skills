# Stack and setup

Versions verified in September 2026 against Packagist and the Laravel 13.x
docs. Re-check with `composer show -l` before quoting them to a user.

## Contents
- Versions
- Support windows
- New app
- The package set (and what not to add)
- Configuration defaults
- Existing app: first hour
- Upgrading Laravel and PHP

## Versions

| Piece | Version | Notes |
|---|---|---|
| PHP | 8.5.x (8.4 minimum) | Laravel 13 needs ≥ 8.3; Pest 5 needs ≥ 8.4 |
| Laravel | 13.x (`laravel/framework` 13.33) | Released March 2026 |
| Composer | 2.10 | |
| Pest | 5.2 (+ `pest-plugin-laravel` 5, `pest-plugin-type-coverage` 5, `pest-plugin-browser` 5) | Built on PHPUnit 13 |
| Larastan | 3.12 (PHPStan 2.2) | |
| Pint | 1.32 | |
| Rector | 2.6 + `driftingly/rector-laravel` 2.6 | |
| Livewire | 4.4 (+ Flux 2.20 optional) | |
| Inertia | `inertiajs/inertia-laravel` 3.3 + Wayfinder 0.1 | |
| Filament | 5.8 | |
| Octane | 2.20 on FrankenPHP 1.12 | |
| Horizon / Reverb / Pulse | 5.50 / 1.12 / 1.8 | |
| Sanctum / Fortify / Socialite | 4.3 / 1.40 / 5.31 | |
| Scout | 11.8 | |
| Nightwatch / Sentry | 1.30 / `sentry/sentry-laravel` 4.28 | |
| Boost / MCP / AI SDK | 2.10 / 1.0 / `laravel/ai` 1.0 | |
| NativePHP | Mobile 4.5, Desktop 2.3 | Mobile embeds PHP 8.4 |
| PostgreSQL | 18 | |

## Support windows

| Laravel | PHP | Bug fixes until | Security fixes until |
|---|---|---|---|
| 11 | 8.2–8.4 | Sept 2025 | **March 12, 2026 (ended)** |
| 12 | 8.2–8.5 | Aug 13, 2026 | Feb 24, 2027 |
| 13 | 8.3–8.5 | Q3 2027 | March 17, 2028 |

Anything on 11 or older is a high-priority upgrade.

## New app

```bash
composer global require laravel/installer
laravel new acme          # pick the Livewire starter kit (or React/Vue for Inertia), Pest, PostgreSQL
cd acme

# Quality gate
composer require --dev larastan/larastan rector/rector driftingly/rector-laravel pestphp/pest-plugin-type-coverage
# copy assets/pint.json, assets/phpstan.neon, assets/rector.php, assets/composer-scripts.json (merge into composer.json)
# copy assets/Pest.php to tests/Pest.php and assets/ArchTest.php to tests/ArchTest.php

# API + tokens (only if you serve an API or mobile clients)
php artisan install:api                 # Sanctum + routes/api.php; add HasApiTokens to User

# Runtime (production)
composer require laravel/octane && php artisan octane:install --server=frankenphp
rm -f frankenphp                        # the installer downloads a ~160 MB binary; the Docker image already has it

# Agent tooling (development)
composer require --dev laravel/boost && php artisan boost:install

composer check
```

A fresh skeleton includes an `AGENTS.md` that tells agents to install
Boost. That's fine: Boost adds version-specific guidelines and an MCP
server with docs search, tinker, and schema tools. This skill's opinions
still apply on top.

Without the installer: `composer create-project laravel/laravel acme "^13"`.
The skeleton ships PHPUnit; replace it with `composer remove --dev
phpunit/phpunit && composer require --dev pestphp/pest pestphp/pest-plugin-laravel -W && vendor/bin/pest --init`.

## The package set (and what not to add)

**First-party first.** Add a package only when it removes real work and the
framework doesn't already cover it.

| Need | Use | Avoid |
|---|---|---|
| Admin panel | Filament | Nova for new apps (paid; Filament is the community default) |
| Roles as data | spatie/laravel-permission | Rolling your own RBAC tables |
| Activity log / audit | spatie/laravel-activitylog | |
| Query-string filters for APIs | spatie/laravel-query-builder | Hand-parsed `?filter[]` |
| Media / uploads | Laravel filesystem (S3/R2); spatie/laravel-medialibrary when you need conversions | |
| Money | integers in minor units + `Number::currency()`; brick/money for arithmetic across currencies | floats |
| Feature flags | Laravel Pennant | |
| Payments | Cashier: `laravel/cashier` (Stripe) or `laravel/cashier-paddle` | Hand-rolled webhook and subscription state |
| DTOs | plain `final readonly` classes | spatie/laravel-data unless you need its casting/TypeScript generation |
| Actions | plain classes (see architecture.md) | lorisleiva/laravel-actions (one class playing controller, job, and listener hides the boundaries) |
| Modules | folders + arch tests | nwidart/laravel-modules (a package-per-module build system for a problem folders solve) |
| Repositories | Eloquent directly | Repository interfaces over Eloquent |

## Configuration defaults

- `.env` for local only. Production values come from the deploy (Kamal
  secrets, Laravel Cloud env). Never commit `.env`; keep `.env.example`
  complete with empty secrets.
- `DB_CONNECTION=pgsql`, and `QUEUE_CONNECTION=database`,
  `CACHE_STORE=database`, `SESSION_DRIVER=database` (the skeleton
  defaults) until measured load says Redis.
- `LOG_CHANNEL=stderr` in containers; `LOG_LEVEL=info` in production.
- `APP_DEBUG=false` in every non-local environment.
- Everything lives in `bootstrap/app.php` (routing, middleware, exceptions)
  and `AppServiceProvider::boot()` (strictness, rate limits, password
  rules). Copy `assets/AppServiceProvider.php`.

## Existing app: first hour

1. `composer outdated -D`, `composer audit`, and read the Laravel and PHP
   constraints.
2. Run `php scripts/laravel_audit.php <app>` from this skill.
3. Install Larastan at the level that passes today, add a baseline
   (`--generate-baseline`), and ratchet up. Never lower it again.
4. Add Pint and run it once in its own commit.
5. Add `tests/ArchTest.php` with only the rules that pass, then tighten.

## Upgrading Laravel and PHP

- **One major at a time** (10 → 11 → 12 → 13), each in its own PR and deploy.
- Read the official upgrade guide's high-impact list. For 12 → 13 (about 10
  minutes): PHP ≥ 8.3, `VerifyCsrfToken` → `PreventRequestForgery`, cache
  prefix and session cookie naming, and `Container::call` nullable defaults.
- Let Rector do the mechanical part: `withComposerBased(laravel: true)`
  applies the version sets up to the installed version.
- Run the whole gate plus `php artisan optimize` after each step.
- Laravel Shift is worth it for multi-major jumps on large apps.
- For PHP bumps, set `config.platform.php` in composer.json to the
  production version, so the lock file can't pull packages that production
  can't run.
