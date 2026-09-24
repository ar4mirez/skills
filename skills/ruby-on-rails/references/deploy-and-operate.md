# Deploy, operate, secure

## Deploy with Kamal 2 (the default)

Rails 8 ships a production Dockerfile, `config/deploy.yml`, and
`.kamal/secrets`. Kamal turns any Linux box into an app server
(`kamal setup`), and deploys with zero downtime behind `kamal-proxy`,
including automatic TLS via Let's Encrypt.

- Start from the template in `assets/deploy.yml`.
- **Secrets:** `.kamal/secrets` reads them from Rails credentials
  (`$(bin/rails credentials:fetch kamal.registry_password)`, Rails 8.1) or
  from a password manager. Never commit raw values.
- **Registry:** Kamal 2.8+ can deploy without a remote registry for simple
  setups. Use a real registry (GHCR) once you have more than one server or CI
  deploys.
- **Roles:** `web` runs Puma plus Thruster. Add a `job` role (`cmd:
  bin/jobs`) when job load grows; until then, keep `SOLID_QUEUE_IN_PUMA=true`.
- **Hosting:** Hetzner, DigitalOcean, or AWS EC2, as plain VMs or bare
  metal. Kamal doesn't care which.
- **Accessories:** run the database on the same host or its own via Kamal
  accessories, or use a managed PostgreSQL. PgBouncer and OpenSearch can
  also run as accessories on their own hosts. Managed is worth it once data
  matters more than the savings.
- **Commands:**
  - `kamal deploy` deploys;
  - `kamal app logs -f` follows logs;
  - `kamal console` (an alias) opens a Rails console;
  - `kamal rollback <version>` rolls back.
- **Health:** `/up` (`rails/health#show`) is the health check. Keep it cheap.

A PaaS (Heroku, Render, Fly) is fine when the team would rather not run
servers. The same Dockerfile works. Don't adopt Kubernetes for a Rails
monolith unless a platform team already runs it.

## The Solid stack in production

- **Databases:** separate `queue`, `cache`, and `cable` databases, or SQLite
  files, as in the generated `config/database.yml`. They can live on the same
  PostgreSQL server at first.
- **Solid Queue:** the dashboard is `mission_control-jobs`. Mount it at
  `/jobs` behind admin authentication. Watch failed jobs and queue latency.
- **Solid Cache:** set a size limit (`max_size`) in `config/cache.yml`. It's
  disk-backed, so it can be large.
- **Solid Cable:** this is the production real-time adapter. Messages are
  kept for a day by default, and it polls the database. Action Cable's
  `async` adapter is for development and test only. Move to a Redis- or
  KeyDB-backed cable only at very high fan-out, and measure first.

## Observability

- **Errors: Sentry,** via `sentry-ruby` and `sentry-rails`, covering Ruby,
  background jobs, and the browser (`@sentry/browser` via importmap, pinned).
  Hook it into the Rails error reporter, so `Rails.error.report` and
  `Rails.error.handle` flow to Sentry. Set `release` to the git SHA (the
  Kamal `KAMAL_VERSION`), and filter PII with `send_default_pii = false` plus
  `filter_parameters`.
- **APM: Datadog or New Relic (pick one).** Use the `datadog` gem (2.x, the
  successor to `ddtrace`) with `Datadog.configure { |c| c.tracing.instrument
  :rails; c.tracing.instrument :active_record }` plus the Datadog agent as a
  Kamal accessory, or `newrelic_rpm` with `config/newrelic.yml`. Use it for
  slow-query traces, memory and allocation anomalies, and p95 per endpoint.
- **Structured events (Rails 8.1):** `Rails.event.notify("billing.payment_recorded",
  invoice_id:, amount_cents:)` with `Rails.event.set_context(request_id:,
  account_id:)`. Subscribers forward the events to logs or APM. Use these for
  business events instead of ad-hoc log strings.
- **Logs:** use JSON in production, one line per request, tagged with
  `request_id`, user, and account.
- **Alerts:** alert on symptoms (error rate, p95 latency, Solid Queue latency
  and failed jobs, database saturation), not on CPU.

## Cloudflare in front of Kamal

Cloudflare provides DNS, CDN and edge caching for assets, image
optimization, WAF, and DDoS protection. To configure it correctly:
- **SSL mode: Full (strict).** Never use Flexible, which leaves plain HTTP
  between Cloudflare and your server.
- **Certificates:** with Cloudflare proxying (the orange cloud), and
  *especially* with more than one web host, use a **Cloudflare Origin CA
  certificate** through Kamal's custom-certificate support instead of Let's
  Encrypt:
  ```yaml
  proxy:
    host: app.example.com
    ssl:
      certificate_pem: CERTIFICATE_PEM     # secret names, from .kamal/secrets
      private_key_pem: PRIVATE_KEY_PEM
    forward_headers: true                 # kamal-proxy drops X-Forwarded-* with ssl unless enabled
  ```
- **Real client IP:** add the `cloudflare-rails` gem, which trusts Cloudflare's
  IP ranges, so `request.remote_ip` (used by `rate_limit`, logs, and Sentry) is
  the visitor's IP, not Cloudflare's.
- **Caching:** let Cloudflare cache fingerprinted assets (`/assets/*`, which
  are immutable). Never cache HTML for signed-in users. Rails sends
  `Cache-Control: private` by default, so keep it that way.
- **WebSockets** (Solid Cable / Turbo Streams) work through Cloudflare. Check
  the plan's connection timeouts for long-lived sockets.
- Optionally, lock the origin firewall to Cloudflare IPs plus your SSH
  source.

## Security checklist

- [ ] `force_ssl` and `assume_ssl` (the Rails 8 production defaults, behind
      kamal-proxy)
- [ ] Every record lookup scoped through the tenant or user
      (`Current.account.invoices.find`)
- [ ] `params.expect` everywhere, with no `permit!`
- [ ] Brakeman is clean in CI (`--exit-on-warn`), and `bundler-audit` and
      `importmap audit` pass
- [ ] Rate limits on sign-in, password reset, and signup
      (`rate_limit to: 10, within: 3.minutes, only: :create`)
- [ ] Content Security Policy configured (`config/initializers/content_security_policy.rb`)
- [ ] Sensitive attributes use `encrypts` (Active Record encryption), and are
      listed in `filter_parameters` to keep them out of logs
- [ ] No `html_safe` or `raw` on user input. Use `sanitize` with an
      allow-list when HTML is needed
- [ ] Uploads have content-type and size validations, and are served from a
      separate domain or CDN
- [ ] Admin and job dashboards sit behind authentication and authorization
- [ ] Dependencies are updated regularly (Dependabot), and Ruby and Rails are
      on supported versions (the 8.1 series gets fixes until October 2026, so
      plan the next upgrade)

## Backups and data

- **PostgreSQL:** use managed point-in-time recovery, or `pg_dump` plus WAL
  archiving, and **test restores** quarterly.
- **SQLite:** use Litestream to S3-compatible storage, and test restores.
- **Active Storage:** use bucket versioning and lifecycle rules.

## Portability

- Use one Dockerfile for dev parity, CI, and production. Configuration comes
  from credentials and ENV, following the twelve-factor approach.
- Avoid database-specific SQL unless it earns its keep. When you use
  PostgreSQL features (JSONB, partial indexes, `ON CONFLICT`), use them
  deliberately and consistently.
- Keep the app free of host assumptions: no local file storage in production
  (use Active Storage services), and no cron on the host (use Solid Queue
  recurring tasks).
