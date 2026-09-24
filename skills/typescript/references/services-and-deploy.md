# Node services, deploy, performance, interop

## Contents
- When this applies
- Framework: Hono by default, Fastify when
- Service anatomy
- Configuration
- Logging (pino)
- Graceful shutdown and `/up`
- Docker: distroless nodejs
- Kamal 2 and Cloudflare
- Bun-compiled binaries (CLIs and small tools)
- Performance and profiling
- Interop: WASM and native addons

## When this applies

New backends run on Bun + Elysia (bun-elysia skill). This file covers
existing Node services and services on platforms that require Node.

## Framework: Hono by default, Fastify when

**Hono 4** (+ `@hono/node-server` 2 on Node):
- Web-standard `Request`/`Response`, so the same app runs on Node, Bun,
  Deno, and Workers (verified: the reference service runs unchanged under
  `node` and `bun`), which keeps a later move to Bun cheap.
- `app.request()` tests without a socket; tiny dependency tree; Standard
  Schema validation via `@hono/standard-validator` (Zod 4 works directly).
- `c.req.raw.signal` aborts when the client disconnects (verified on
  node-server 2), so pass it to downstream calls.

**Fastify 5** when you need its ecosystem: mature plugins (auth, rate
limiting, multipart, swagger) for a large Node-only API, JSON-schema
response serialization for throughput, or an existing Fastify codebase.
Use its type providers (`fastify-type-provider-zod` or TypeBox) so schemas
type the handlers.

Express: keep only in legacy code; don't start with it. NestJS:
decorators aren't erasable and the DI layer rarely pays for itself.

## Service anatomy

`assets/app.ts`, `assets/server.ts`, `assets/links.ts`,
`assets/preview.ts`, `assets/env.ts`, `assets/result.ts`:
- `createApp({ store, logger })` returns the Hono app (routes chained so
  the app type carries every route for `hc` typed clients). No `listen`.
- Validation middleware returns 422 with issues; handlers call domain
  functions that return a `Result`; `switch` + `assertNever` maps errors to
  status codes.
- `app.onError` logs unexpected errors with context and returns a generic
  500; `HTTPException`s pass through.
- Outbound calls (`preview.ts`): per-attempt deadline combined with the
  caller's signal, retry on 5xx only, schema-validated body.
- Run it with `node src/server.ts` (type stripping; no build step, no
  ts-node/tsx). Development: `node --watch --env-file-if-exists=.env
  src/server.ts`.

## Configuration

Parse `process.env` once at boot with a Zod schema (`assets/env.ts`):
defaults for non-secrets, `z.coerce.number()` for ports, `z.url()` for
URLs, and `z.prettifyError` listing every problem. Nothing else reads
`process.env`. Local `.env` via `--env-file-if-exists` (built into Node;
no dotenv).

## Logging (pino)

- `pino({ level: env.LOG_LEVEL })` in `server.ts`, passed into
  `createApp`; JSON to stdout; the platform ships logs.
- Log errors as `{ err: error }` (pino serializes the stack and `cause`).
- `redact: ['req.headers.authorization', 'req.headers.cookie']` when
  logging requests. Request logging middleware: `hono-pino` or a 10-line
  middleware; include method, path, status, and duration.
- `pino-pretty` only in development, never in the production image.

## Graceful shutdown and `/up`

```ts
function shutdown(signal: NodeJS.Signals): void {
  logger.info({ signal }, 'shutting down')
  const force = setTimeout(() => process.exit(1), 8_000)
  force.unref()
  server.close((error) => { process.exitCode = error ? 1 : 0 })
}
process.once('SIGTERM', shutdown)
process.once('SIGINT', shutdown)
```

- `server.close()` stops accepting and waits for in-flight requests;
  close pools after it. Force-exit before Docker's 10 s stop timeout
  (kamal-proxy has already drained traffic before SIGTERM arrives).
- Set `process.exitCode`, don't call `process.exit()` on the happy path
  (it cuts off pending log writes).
- `GET /up` returns 200 when the app can serve (check the database if it
  has one); kamal-proxy's default health path is `/up`.
- Verified: SIGTERM logs "shutting down" and the process exits cleanly
  under both Node and Bun.

## Docker: distroless nodejs

`assets/Dockerfile` (multi-stage; **not built during verification, since
Docker wasn't available**, but each step was run locally):
1. `node:24-trixie-slim` build stage: install pnpm 12.6.0,
   `pnpm install --frozen-lockfile`, build the app's workspace
   dependencies (`pnpm --filter "${APP}^..." build`), then
   `pnpm --filter "${APP}" deploy --prod /out` (verified: produces a
   self-contained folder with only production dependencies and built
   workspace libraries, and `node src/server.ts` runs from it).
2. `gcr.io/distroless/nodejs24-debian13:nonroot` runtime (tag verified):
   no shell, no package manager, non-root; the entrypoint is already
   `node`, so `CMD ["src/server.ts"]`.

`.dockerignore` excludes `node_modules`, `dist`, `.git`, and `.env*`.
Debugging a distroless container: use the `:debug-nonroot` tag
temporarily.

## Kamal 2 and Cloudflare

`assets/deploy.yml`: `proxy.app_port: 3000` (kamal-proxy defaults to 80),
`healthcheck.path: /up`, secrets via `env.secret`, registry on ghcr.io.
Behind Cloudflare (proxied, SSL mode Full (strict)), use a Cloudflare
Origin CA certificate in `proxy.ssl` instead of Let's Encrypt HTTP
challenges. Run migrations in a `pre-deploy` hook or a one-off
`kamal app exec`, never on every container boot of a multi-instance
service.

## Bun-compiled binaries (CLIs and small tools)

`bun build --compile --minify --sourcemap --outfile dist/linkcheck
src/main.ts` produces one executable with the runtime inside (verified on
the reference CLI; `import.meta.main` holds in the binary). Cross-compile
with `--target=bun-linux-x64` (glibc) or `bun-linux-x64-musl` (Alpine).
Ship services as binaries only if they're Bun services (bun-elysia skill);
for Node services, ship the distroless image.

## Performance and profiling

Measure first:
1. Reproduce with load (`autocannon`/`oha`/`k6`) against the production
   start command.
2. CPU: `node --cpu-prof src/server.ts` writes a `.cpuprofile` on exit;
   open it in Chrome DevTools or speedscope. Live: `node --inspect` and
   the DevTools Performance panel.
3. Memory: `node --heap-prof`, or heap snapshots via `--inspect`;
   `--heapsnapshot-signal=SIGUSR2` for production snapshots on demand.
4. Event-loop stalls: `perf_hooks.monitorEventLoopDelay()`; stalls mean
   CPU work on the main thread.

Usual wins: stop awaiting independent calls sequentially; bound
concurrency instead of unbounded `Promise.all`; stream large bodies
(`node:stream/promises` `pipeline`) instead of buffering; cache parsed
schemas and compiled regexes at module level; move CPU-heavy work to
`worker_threads`; set `--max-old-space-size` to the container limit.
Avoid micro-optimizing before a profile says so.

## Interop: WASM and native addons

- **WASM** (`WebAssembly.instantiate`, or `import` of `.wasm` in
  bundlers) for portable compute kernels written in Rust/Zig/Go; works in
  Node, Bun, browsers, and Workers.
- **Native addons** (Node-API via `napi-rs` for Rust) only when WASM
  can't do it (system APIs, SIMD-heavy code); ship prebuilt binaries per
  platform as optional dependencies. Every native dependency complicates
  Docker, Alpine, and Bun compatibility.
- Calling other processes: `node:child_process` `execFile` (no shell) with
  arguments as an array; never interpolate user input into `exec`.
