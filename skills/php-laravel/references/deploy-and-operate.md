# Deploy and operate

**Default:** one Docker image (FrankenPHP + Octane, PHP 8.5, Alpine,
non-root), deployed with **Kamal 2** as web, worker, and scheduler roles on
your own VMs, behind **Cloudflare**. **Laravel Cloud** is the managed
alternative when the team would rather not run servers. All of it was
verified: the image builds (411 MB), boots, migrates Postgres, answers
`/up`, and passes Docker's healthcheck, and `kamal config` (Kamal 2.12)
accepts `assets/deploy.yml`.

## Contents
- Choosing where to run
- The image
- Boot sequence and migrations
- Kamal roles
- Cloudflare in front
- Zero-downtime details
- Laravel Cloud and Forge
- Observability
- Backups and recovery
- Release checklist

## Choosing where to run

| Situation | Choose |
|---|---|
| You want no servers, autoscaling, managed Postgres, queues, and Reverb | **Laravel Cloud** |
| You own VMs (Hetzner, DigitalOcean, EC2) and want one consistent tool across your stacks | **Kamal 2** + Docker (this reference) |
| Classic VMs with PHP-FPM, provisioned for you | **Forge** |
| A platform team already runs Kubernetes | Kubernetes with the same image |

## The image

`assets/Dockerfile` is a three-stage build:
1. **vendor:** `composer install --no-dev --no-scripts --no-autoloader`
   against the lock file (cached layer).
2. **assets:** `node:24-alpine`, `npm ci && npm run build` (needs a
   committed `package-lock.json`).
3. **runtime:** `dunglas/frankenphp:1.12-php8.5-alpine` with `intl opcache
   pcntl pdo_pgsql zip`, `php.ini-production` plus
   `assets/php-production.ini`, an authoritative classmap, the `app` user
   (uid 1000), port 8080, and a `/up` healthcheck.

Notes:
- Alpine cut the image from 982 MB (Debian trixie) to 411 MB.
- Run as non-root and listen on 8080 (binding 80 needs root or
  capabilities). Kamal's proxy maps to it via `proxy.app_port: 8080`.
- `assets/dockerignore` keeps `.env`, `vendor`, `node_modules`, tests, and
  the downloaded `frankenphp` binary out of the build context.
- Add `redis` to `install-php-extensions` when you move to Redis.

## Boot sequence and migrations

`assets/docker-entrypoint.sh`:
1. `php artisan optimize` caches config, routes, events, and views **with
   the runtime environment**. Never cache config at build time: the
   secrets aren't there yet.
2. If `RUN_MIGRATIONS=1`, `php artisan migrate --force`.
3. `exec "$@"` hands off to the role's command, so signals reach PHP.

**Only one host migrates.** `deploy.yml` tags one web host `migrator` and
sets `RUN_MIGRATIONS: "1"` only for that tag. Don't use `migrate --isolated`
on every host as the "fix": it takes its lock through the cache store,
and with the database cache on a fresh database the `cache_locks` table
doesn't exist yet, so the first deploy fails (verified). Migrations must
be backward compatible (expand/contract; see `eloquent-and-data.md`),
because old containers keep serving while new ones boot.

## Kamal roles

`assets/deploy.yml`:
- **web**: the FrankenPHP/Octane server, proxied by kamal-proxy, with the
  healthcheck on `/up` (Laravel's built-in health route: the framework
  boots and returns 200).
- **worker**: `php artisan queue:work --queue=default --sleep=1 --tries=3 --max-time=3600`
  (or `php artisan horizon` with Redis).
- **scheduler**: `php artisan schedule:work`, on exactly one host.
- **accessories**: Postgres 18 on its own host, bound to the **private
  interface** (`10.0.0.20:5432:5432`) and firewalled to app hosts.
  App containers reach it by that private IP. The accessory's container
  name (`billing-db`) only resolves on its own host.

Useful aliases (in the template): `kamal console` (tinker), `kamal logs`,
and `kamal migrate` (on the primary host).

Stop behavior: Kamal gives non-proxied roles (workers) `drain_timeout`, 30
seconds by default, before the kill. Proxied web containers get Docker's
default 10-second stop timeout; set `stop_timeout` if requests can run
longer.

## Cloudflare in front

- DNS proxied (orange cloud) and **SSL mode Full (strict)**.
- A **Cloudflare Origin CA certificate** on kamal-proxy:
  `proxy.ssl.certificate_pem` / `private_key_pem` as secrets. Kamal's
  `ssl: true` (Let's Encrypt) **only works with one web host**; `kamal config`
  rejects it for two.
- `proxy.forward_headers: true`, and trust the proxies in
  `bootstrap/app.php` (`$middleware->trustProxies(at: [...])`, with
  Cloudflare's ranges, or `'*'` when the origin is firewalled to Cloudflare
  only). Otherwise `$request->ip()`, rate limiting, and `isSecure()` see
  the proxy.
- Cache static assets at the edge (Vite filenames are hashed), bypass
  cache for HTML and `/livewire/*`, and allow WebSockets for Reverb.
- Firewall the origin so only Cloudflare and your admin IPs reach 443.

## Zero-downtime details

- kamal-proxy waits for `/up` to pass on the new container before
  switching traffic, then drains the old one.
- Sessions and cache in the database or Redis, never `file`, so any
  container can serve any user.
- Files on S3 or R2 (`FILESYSTEM_DISK=s3`), never the container disk.
- Queue workers restart with each deploy (new containers), so they pick
  up new code. On VMs without containers, run `php artisan queue:restart`.
- Maintenance mode is rarely needed. When it is, use
  `APP_MAINTENANCE_DRIVER=cache` so it applies across hosts.

## Laravel Cloud and Forge

- **Laravel Cloud:** push-to-deploy, managed Postgres (serverless),
  Valkey/Redis, queue clusters, Reverb, object storage, preview
  environments, and autoscaling (including hibernation). Octane and
  FrankenPHP are supported. The same app code applies; the Kamal files
  don't. The `laravel/cloud-cli` package drives it from a terminal.
- **Forge:** provisions and manages VMs (nginx + PHP-FPM, or Octane),
  zero-downtime deploys, queue daemons, and the scheduler. Choose it
  when you want VMs without writing deploy config.

## Observability

- **Errors and performance:** Nightwatch (first-party, Laravel-aware:
  requests, queries, jobs, mail, exceptions) or Sentry (`sentry/sentry-laravel`).
  Pick one and wire it on day one.
- **In-app dashboard:** Pulse (slow routes, queries, jobs, cache hit
  rates, heavy users), gated to admins.
- **Logs:** `LOG_CHANNEL=stderr` in containers (Kamal and Docker collect
  them), JSON format for aggregation, and `LOG_LEVEL=info`. `php artisan pail`
  tails logs locally.
- **Correlation:** `Context::add('request_id', ...)` and `Context::add('account_id', ...)`
  in middleware. Context flows into logs and queued jobs automatically.
- **Telescope** is a local debugging tool. Keep it in `require-dev`.
- Health: `/up` for the proxy. Add deeper checks (database, queue lag,
  disk) to a separate authenticated endpoint or your monitoring.

## Backups and recovery

- Postgres: automated nightly `pg_dump` to object storage plus WAL
  archiving or provider point-in-time recovery for anything serious.
  Test a restore every quarter.
- spatie/laravel-backup is a simple option for database plus storage
  backups on VMs.
- Keep `APP_KEY` backed up with the database: encrypted columns are
  unreadable without it.

## Release checklist

- [ ] `composer check` is green in CI (including `artisan optimize`).
- [ ] Migrations are backward compatible with the running release.
- [ ] New env vars and secrets exist in `.kamal/secrets` or Cloud before
      the deploy.
- [ ] `APP_DEBUG=false`, `APP_ENV=production`, and `LOG_LEVEL=info`.
- [ ] Workers and scheduler roles deploy with the web role (same image,
      same version).
- [ ] Error tracking shows the new release. Watch it for 15 minutes.
