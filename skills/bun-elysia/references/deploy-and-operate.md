# Deploy, operate, secure

## Contents
- Compiled binaries
- Docker
- Kamal 2
- Migrations on deploy
- Cloudflare in front
- Observability
- Security checklist
- Performance and scaling

## Compiled binaries

```bash
bun build --compile --format=esm --minify-whitespace --minify-syntax --sourcemap --bytecode \
  --target=bun-linux-x64 --outfile dist/server src/index.ts
bun build --compile --format=esm --minify-whitespace --minify-syntax --sourcemap --bytecode \
  --target=bun-linux-x64 --outfile dist/worker src/worker.ts
```

Verified in the reference monorepo: both binaries compile, and `./server`
answers `/up`.
- **Why a binary:** the source, `node_modules`, and the Bun runtime become a
  single file. Memory drops about 2–3× compared with running `.ts`, there's
  no install step on the server, and startup is fast (`--bytecode`).
- **`--format=esm` is required with `--bytecode`** whenever the code uses
  top-level `await`, which `worker.ts` and `index.ts` do. Without it, the
  build fails: `"await" can only be used inside an "async" function`.
- **`--sourcemap`** embeds a compressed map, so stack traces point at `.ts`
  lines. Keep it on.
- **Avoid `--minify` when using OpenTelemetry,** because it renames
  functions. Instrumented libraries (for example `pg`) must be marked
  `--external` and installed with `bun install --production` next to the
  binary.
- **Targets:** `bun-linux-x64`/`arm64` (glibc), `bun-linux-x64-musl`/`arm64-musl`
  (Alpine), and `-baseline` variants for CPUs without AVX2 (a binary that
  prints garbled "random Chinese" errors on start means no AVX2).
- Compiled binaries auto-load `.env` from the working directory. Disable that
  with `--no-compile-autoload-dotenv` if production must use only the real
  environment.

## Docker

See `assets/Dockerfile`. Build from the monorepo root with `docker build -f
apps/api/Dockerfile .`.
- **Build stage** (`oven/bun:1.4`):
  1. Copy the manifests first (root plus each needed workspace), then run
     `bun install --frozen-lockfile --filter '@acme/api'` for layer caching.
  2. Copy the sources and compile both binaries.
- **Runtime stage:** `gcr.io/distroless/base-debian12:nonroot`, with glibc,
  no shell, and a non-root user. Copy in only the binaries and the
  `migrations/` folder. Use `CMD ["./server"]` and `EXPOSE 3000`.
- For Alpine instead, compile with `--target=bun-linux-x64-musl`. The audit
  flags Alpine images without a musl target.
- Next.js (`apps/web`) ships in its own image (`output: 'standalone'`) or on
  Vercel. Don't bundle it into the API image.

## Kamal 2

See `assets/deploy.yml`:
- **One image with two roles:** `web` runs `cmd: ./server`, and `worker` runs
  `cmd: ./worker`.
- **The proxy needs `app_port: 3000`** (kamal-proxy defaults to 80) and a
  health check at `path: /up`. The app must serve `.get('/up', () => 'ok')`.
- **Secrets** go in `.kamal/secrets` (from a password manager or CI
  secrets), never in the repo: `DATABASE_URL`, `DATABASE_DIRECT_URL`,
  `BETTER_AUTH_SECRET`, `SENTRY_DSN`.
- **Hosting:** Hetzner, DigitalOcean, or EC2, as plain VMs or bare metal. Use
  managed Postgres once the data matters more than the savings, or run it as
  a Kamal accessory with backups (`pg_dump` plus WAL archiving, with restores
  tested quarterly).
- **Scaling:** add hosts to `web` (kamal-proxy balances across them), and add
  worker hosts independently. Each container runs one Bun process. For more
  cores per host, run more containers or a `node:cluster` entrypoint.
  `reusePort` is on by default on Linux.
- **Graceful shutdown:** Kamal stops containers with a 30-second timeout.
  The worker stops pg-boss gracefully (`queue.stop({ graceful: true, timeout:
  25_000 })`), and in-flight requests finish.

## Migrations on deploy

- Run `drizzle-kit migrate` **before** switching traffic. Either:
  - a CI step against `DATABASE_DIRECT_URL` before `kamal deploy`; or
  - a Kamal `pre-deploy` hook that runs a one-off container with Bun and the
    `packages/db` workspace.
- Migrations must be backward compatible with the currently running version
  (expand, then contract). See `data-and-jobs.md` for the rules.

## Cloudflare in front

- Set **SSL/TLS to Full (strict)**. Never use Flexible.
- With proxied DNS (the orange cloud), or more than one web host, use a
  **Cloudflare Origin CA certificate** in Kamal's
  `proxy.ssl.certificate_pem`/`private_key_pem` (loaded from secrets)
  instead of Let's Encrypt. Set `forward_headers: true`.
- **The real client IP** arrives in `CF-Connecting-IP`, so read it in a
  request-context plugin for logging and rate limiting. Trust it only when
  the origin firewall accepts traffic from Cloudflare's IP ranges alone.
- **Caching:** let Cloudflare cache static and immutable assets. API
  responses send `Cache-Control: private, no-store` unless a route is
  deliberately public.
- WebSockets and SSE work through Cloudflare. Check your plan's idle
  timeouts for long streams.

## Observability

- **Tracing:** `@elysia/opentelemetry` (`.use(opentelemetry({ spanProcessors:
  [...] }))` in `app.ts`, applied globally), exported over OTLP to your
  backend (Grafana, Honeycomb, Datadog). Add spans around external calls, and
  job handlers in the worker.
- **Errors:** `@sentry/bun`. Initialize it first in `index.ts` and
  `worker.ts`, and report from the global `onError` for 5xx responses and from
  job failures. Set `release` to the git SHA.
- **Logs:** JSON lines to stdout (Kamal collects them), each with
  `requestId`, `accountId`, route, status, and duration. Don't log bodies or
  secrets.
- **Metrics:** p95 latency per route, error rate, pg-boss queue depth and
  failed jobs, database pool saturation. Alert on symptoms.

## Security checklist

- [ ] Every query is scoped by tenant (`accountId`). Request tests prove
      account A gets 404 for account B's resources.
- [ ] Every route that accepts input has a `body`/`query`/`params` schema,
      and responses have `response` schemas (which also strip leaked fields).
- [ ] Auth is Better Auth behind the `auth` macro, with a strong
      `BETTER_AUTH_SECRET` and `trustedOrigins` set. There's no hand-rolled
      session crypto.
- [ ] CORS lists explicit origins, with `credentials: true` only for them.
- [ ] Brute-force-prone routes (sign-in, OTP, password reset) are
      rate-limited, for example with `elysia-rate-limit` backed by Redis when
      running multiple hosts.
- [ ] Cookies are `httpOnly`, `secure`, and `sameSite=lax` or `strict`, and
      signed (`cookie.secrets`) when custom.
- [ ] Config is validated at boot, and secrets come only from the
      environment. `.env` is never committed, and no secret goes into client
      bundles (`NEXT_PUBLIC_*`/`EXPO_PUBLIC_*` are public).
- [ ] `bun audit` is clean in CI. `trustedDependencies` is reviewed, and
      lifecycle scripts are allowed only where needed.
- [ ] Uploads are validated (`t.File` type and size) and stored in S3/R2 via
      presigned URLs.
- [ ] OpenAPI docs are disabled or protected in production. Validation
      details are hidden in production, which is Elysia's default.
- [ ] The container runs as non-root (distroless `:nonroot`), and the origin
      firewall allows only Cloudflare and SSH.

## Performance and scaling

- **Order of wins:**
  1. Fix N+1 queries (use Drizzle relational queries).
  2. Add indexes (tenant id first).
  3. Select only the needed columns.
  4. Add `response` schemas (fast serialization).
  5. Cache hot reads (`Bun.redis`).
  6. Move work to jobs.
- **Don't touch `aot`** (it's already on), and don't chase framework
  benchmarks. Profile real routes with OpenTelemetry spans.
- **CPU-heavy work** (image processing, PDFs, crypto loops) goes to pg-boss
  jobs, or a `Worker`, never the request thread.
- **Horizontal scaling is the default.** Run more containers and hosts
  behind kamal-proxy, with the database sized behind PgBouncer. The app stays
  stateless, so sessions live in the database via Better Auth.
