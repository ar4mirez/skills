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
- **Accessories:** run the database on the same host or its own via Kamal
  accessories, or use a managed PostgreSQL. Managed is worth it once data
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
- **Solid Cable:** messages are kept for a day by default, and it polls the
  database. That's fine for typical apps; move to Redis-backed Action Cable
  only at very high fan-out.

## Observability

- **Structured events (Rails 8.1):** use
  `Rails.event.notify("invoice.paid", invoice_id:, amount:)` with
  `Rails.event.set_context(request_id:, account_id:)`, plus a subscriber that
  emits JSON to your log pipeline. Prefer this over ad-hoc `Rails.logger.info`
  strings for business events.
- **Logs:** use one line per request, with request id and user or account ids
  tagged (`config.log_tags = [:request_id]`), in JSON in production.
- **Errors:** use the Rails error reporter (`Rails.error.report`,
  `Rails.error.handle`) with one provider (Sentry, Honeybadger, AppSignal),
  or self-hosted `solid_errors` for small apps.
- **APM:** watch p95 latency per endpoint, queue latency, and database time.
  Alert on symptoms (error rate, latency, queue backlog), not on CPU.

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
