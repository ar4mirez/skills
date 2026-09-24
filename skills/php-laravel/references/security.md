# Security

Laravel's defaults are good. Most Laravel vulnerabilities come from
opting out of them. Each item below lists the hole, why it matters, and
the fix. `scripts/laravel_audit.php` detects the ones marked (audit).

## Contents
- Input and mass assignment
- Authorization and tenant isolation
- SQL and command injection
- XSS and output
- CSRF, CORS, and sessions
- Secrets and configuration
- Files and uploads
- Redirects, URLs, and signed links
- Passwords, auth, and rate limits
- Dependencies and supply chain
- Headers and transport
- Logging and privacy

## Input and mass assignment

- **`Model::create($request->all())`** writes every field, including
  `is_admin` or `account_id` (audit). Use `$request->validated()` or a DTO.
- **`$guarded = []`, `#[Unguarded]`, `Model::unguard()`** (audit). Use
  `#[Fillable]` with the user-editable fields only, and change state fields
  through actions with `forceFill`.
- `Model::shouldBeStrict()` makes a non-fillable key throw in dev/test
  instead of being dropped silently.
- `unserialize()` on user input enables object injection (audit). Use
  `json_decode`. Laravel's encrypted cookies and sessions are already
  JSON, not serialized.

## Authorization and tenant isolation

- **Every controller action and Livewire action authorizes** (audit flags
  controller methods receiving a model without authorization, and
  Livewire actions loading a browser-supplied id).
- **IDOR:** `Invoice::findOrFail($id)` in a multi-tenant app lets anyone
  read anyone's invoice. Scope through the tenant *and* authorize with the
  policy.
- Validate foreign ids against the tenant:
  `Rule::exists('customers', 'id')->where('account_id', $accountId)`.
- Private broadcast channels authorize in `routes/channels.php`.
- Filament panels: implement `canAccessPanel()` on User.

## SQL and command injection

- The query builder and Eloquent bind parameters. The **raw methods
  don't**: `whereRaw("email like '%$q%'")`, `DB::select("... $id")`,
  `orderByRaw($request->sort)` (audit). Use bindings
  (`whereRaw('email ilike ?', ["%{$q}%"])`) and allow-lists for column
  names and sort directions.
- Column names are never bound. Allow-list them before
  `orderBy($request->input('sort'))`.
- Shell: `Process::run(['convert', $in, $out])` with an argument array.
  Never `exec`, `shell_exec`, `system`, or `passthru` with interpolated input
  (audit).

## XSS and output

- `{{ }}` escapes; `{!! !!}` doesn't (audit: high when the value comes
  straight from the request). Sanitize rich text server-side (for
  example, with symfony/html-sanitizer) before storing or rendering it.
- `@js($data)` / `Js::from()` for passing data to JavaScript. They escape
  correctly for script contexts (Laravel 13 leaves Unicode unescaped by
  default, which is still safe).
- Inertia and Livewire props are visible in the page source. Pass only
  what the user may see.
- Set a Content-Security-Policy (spatie/laravel-csp) once the app is
  stable. Livewire documents its CSP requirements.

## CSRF, CORS, and sessions

- Laravel 13's `PreventRequestForgery` middleware checks the CSRF token and
  the `Sec-Fetch-Site` origin header. Keep it on every web route.
  **Never `except: ['*']`** (audit). Exclude only specific webhook URIs, and
  verify their signatures instead.
- CORS (`config/cors.php`): list your origins explicitly, never `*` with
  credentials.
- Sessions: `SESSION_SECURE_COOKIE=true` in production, `http_only`, and
  `same_site=lax`. Regenerate the session on login (the starter kits do).
  `SESSION_ENCRYPT=true` if you store anything sensitive in it.

## Secrets and configuration

- **`APP_DEBUG=false`** outside local (audit checks `.env.production`).
  Debug pages expose environment variables and SQL.
- `APP_KEY` is secret, set per environment, and never committed (audit
  flags a real-looking key in `.env.example`). Rotating it invalidates
  sessions and encrypted data: use `APP_PREVIOUS_KEYS` for graceful
  rotation.
- `env()` only in `config/` (audit). Once config is cached, `env()`
  elsewhere returns null, and people "fix" it by hard-coding secrets.
- Keep secrets in the deploy's secret store (Kamal secrets from 1Password
  or your CI vault, or Laravel Cloud env). `php artisan env:encrypt` is
  acceptable for small teams.
- Telescope only in `require-dev` and local (audit flags it in `require`).

## Files and uploads

- Validate type and size: `['file', 'mimes:jpg,png,pdf', 'max:10240']`.
  `mimes` checks content, not just the extension.
- Store with generated names (`$file->store('avatars', 's3')`), never
  `getClientOriginalName()` as the path (audit). Keep the original name as
  data.
- Private files on a private disk, served through a controller that
  authorizes, or via `temporaryUrl()`. Never under `public/`.
- Serve user uploads from a separate domain or with
  `Content-Disposition: attachment` for HTML or SVG, so an uploaded file
  can't run script on your origin.

## Redirects, URLs, and signed links

- `redirect($request->input('next'))` is an open redirect (audit). Use
  `redirect()->intended()`, or validate against your own routes.
- Signed URLs for email links and downloads: `URL::temporarySignedRoute(...)`
  plus the `signed` middleware.
- `URL::forceHttps()` in production (in the provider template) so
  generated URLs are https behind a TLS-terminating proxy.

## Passwords, auth, and rate limits

- `Password::defaults(fn () => Password::min(12)->uncompromised())` in
  production (in the template). The `uncompromised()` check calls the HIBP
  k-anonymity API.
- Hashing: bcrypt (the default) or argon2id. Never your own.
- Rate-limit login, registration, password reset, 2FA, and anything that
  sends email or SMS. The starter kits limit login; add the rest.
- Sanctum tokens: set `expiration`, use abilities, prune expired tokens,
  and hash-compare only (Sanctum stores hashes).
- 2FA via Fortify (in the starter kits) for admin users at least.

## Dependencies and supply chain

- `composer audit` in CI (in `composer check`). Composer 2.10 blocks
  installing packages with known advisories (and abandoned ones) by
  default; don't reach for `--no-blocking`.
- Commit `composer.lock`, set `config.platform.php`, and review new
  packages (maintainer, downloads, recent releases) before adding them.
- `npm audit` for the frontend, and Dependabot or Renovate for both.

## Headers and transport

- TLS end to end: Cloudflare Full (strict) plus an Origin CA certificate
  on the proxy.
- Trust the proxy so `$request->ip()` and `isSecure()` are right:
  `$middleware->trustProxies(at: '*')` only when the app is reachable
  solely through your proxy, or list the proxy IPs (Cloudflare's ranges).
  Behind Cloudflare, read the visitor IP from `CF-Connecting-IP`.
- Add HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and
  `frame-ancestors` via middleware or at Cloudflare.
- `expose_php = Off` (in `assets/php-production.ini`).

## Logging and privacy

- Never log passwords, tokens, or full card or bank data. Laravel never
  flashes `password` fields back into the session after a validation
  failure; add other sensitive fields with `$exceptions->dontFlash([...])`.
- Encrypt sensitive columns with the `encrypted` cast. Note that you can't
  query or index them.
- Use `#[Hidden]` on models for anything that must never serialize.
- `Context::add()` for correlation ids and tenant ids; `Context::addHidden()`
  for values that should reach jobs but not logs.
