# Elysia patterns

Sources: elysiajs.com (Key Concept, Best Practice, Plugin, Life Cycle, Macro,
Validation, Error Handling, Configuration, Deploy), verified against Elysia
1.4.30.

## Contents
- The three inference rules
- Lifecycle order and scope
- Plugins: dedup, scope, and explicit dependency
- Macros, guards, derive/resolve, decorate
- Validation (TypeBox, Standard Schema, coercion)
- Responses, status, errors
- OpenAPI
- WebSocket, SSE, and streaming
- Cookies and CORS
- Performance

## The three inference rules

1. **Always method-chain.** Each call returns a *new* type, so separate
   statements (`app.get(...)`) lose the state, decorators, and macros that
   came before.
2. **Always use inline handlers.** Destructure inside the arrow function and
   pass plain values out: `({ body }) => BillingService.createInvoice(body)`.
   Never `.get('/', Controller.method)` or `(ctx: Context) => ...`.
3. **One Elysia instance = one controller.** Split by feature, and compose
   with `.use()`. Don't build controller classes on top of Elysia.

## Lifecycle order and scope

The order is: request → parse → transform → **beforeHandle** → handler →
afterHandle → mapResponse → afterResponse, plus **onError** on any throw.
Macros and `resolve` run around beforeHandle.

- **Hooks apply only to routes registered after them.** Put `onError`,
  `derive`, and `onBeforeHandle` *before* the routes they should cover.
- **Hooks are local by default** (encapsulation), affecting only the instance
  that declares them. To export a hook:
  - `{ as: 'scoped' }` applies to the parent that `.use()`s the plugin;
  - `{ as: 'global' }` applies to every instance.

  Use `global` only for concerns no module should opt out of (CORS, tracing,
  request logging, security headers).
- `guard({ ... }, (app) => app.get(...))` applies schemas and hooks to a group
  of routes. It's clearer than repeating options.

## Plugins: dedup, scope, and explicit dependency

```ts
export const requestContext = new Elysia({ name: 'plugin.request-context' })
  .derive({ as: 'scoped' }, ({ request, server }) => ({
    requestId: request.headers.get('x-request-id') ?? crypto.randomUUID(),
    ip: server?.requestIP(request)?.address,
  }))
```

- **Give every reusable plugin a `name`** (plus `seed` if it's parameterized),
  so it runs once however many modules `.use()` it.
- **Declare dependencies explicitly.** Each module `.use()`s what it needs
  (`auth`, `requestContext`), which makes dependencies visible and types
  correct.
- Plugins that only add behavior, not types (CORS, compression, tracing), are
  fine as global plugins applied once in `app.ts`.

## Macros, guards, derive/resolve, decorate

| Tool | Use for | Example |
|---|---|---|
| `macro` with `resolve` | Opt-in, per-route behavior that adds typed context | `auth: true` → `{ user, account }`, or `role: 'admin'` |
| `derive` | Adding request-scoped values for every route in scope (runs before validation) | `requestId`, `ip` |
| `resolve` | Like derive, but after validation, with validated inputs | Loading the tenant from a validated header |
| `decorate` | Request-*independent* values that must be in context. **Rarely needed**; prefer imports | — |
| `state` | Mutable app-wide store. **Avoid**: use the db or Redis for shared state | — |

**Role checks:** put a route-level `beforeHandle` next to `auth: true`. It
sees the macro-resolved `user`. This was verified on Elysia 1.4.30.

```ts
const isAdmin = (user: { role?: string | null }) => user.role === 'admin'

.get('/admin/reports', ({ user }) => ReportsService.list(user.id), {
  auth: true,
  beforeHandle: ({ user, status }) => (isAdmin(user) ? undefined : status(403, 'Forbidden')),
})
```

- **Don't compose macros that rely on each other's resolved context.** For
  example, a `role` macro returning `{ auth: true, beforeHandle: ({ user })
  => ... }` fails type-checking in 1.4, because `user` isn't in the composed
  macro's hook context. If many routes need the same role check, write the
  predicate once (`isAdmin`) and use the route-level `beforeHandle`, or
  `guard` a group of routes.
- Put business-level permissions (can *this* user edit *this* invoice) in the
  service, because they need data. The route's `beforeHandle` should hold
  only coarse, role-based checks.

## Validation (TypeBox, Standard Schema, coercion)

- **Validate everything that crosses the boundary:** `params`, `query`,
  `body`, `headers`, `cookie`, and the `response` of each route.
- Elysia **coerces** query and params strings to the declared types
  (`t.Number()` accepts `"42"`), and `normalize: true` (the default) strips
  unknown fields on input *and output*. That's why response schemas also
  prevent data leaks.
- **Useful types:**
  - `t.UnionEnum([...])` for enums;
  - `t.Numeric()` for numeric strings;
  - `t.File({ type: 'image/*', maxSize: '5m' })` for uploads, which also
    checks magic numbers via `fileType`;
  - `t.Optional`, `t.Nullable`, `t.Partial`, `t.Pick`, `t.Omit`.
- **Custom messages:** `t.String({ error: 'Email is required' })`. Validation
  *details* are hidden when `NODE_ENV=production`, so write messages meant for
  users.
- **Standard Schema** (Zod 4, Valibot, ArkType) works anywhere a schema is
  accepted. Choose it only when the schemas are also used by a client stack
  that already standardized on one. Don't mix libraries within one API.
- **Reference models:** `.model({ 'billing.invoice': schema })`, then `body:
  'billing.invoice'`. This names schemas in OpenAPI and speeds type
  inference. Use it for large APIs, but direct schema objects are fine
  otherwise.

## Responses, status, errors

- A handler returns the value, or `status(code, body)` for non-200 codes.
  Declare each code in `response: { 201: ..., 409: ... }`, and Eden will
  narrow `error.status` and `error.value`.
- **Throwing:** Elysia maps a thrown error's `status` property to the HTTP
  status, which is how `DomainError` subclasses work (see `architecture.md`).
  Register custom errors with `.error({ PaymentDeclined })`, and handle them
  by `code` in `onError`.
- **One global `onError` in `app.ts`:**
  - log with the request id;
  - report 5xx errors to Sentry;
  - return a consistent problem body `{ error, message }`;
  - never leak stack traces in production.
- `NOT_FOUND`, `VALIDATION`, and `PARSE` are built-in codes. Handle
  `VALIDATION` to shape the error body if you need to.

## OpenAPI

```ts
.use(openapi({ enabled: env.NODE_ENV !== 'production', documentation: { info: { title: 'Acme API', version: '1.0.0' } } }))
```

- Docs live at `/openapi`, with JSON at `/openapi/json`. Route `detail: {
  summary, tags, hide }` enriches them.
- Better Auth routes can be merged in through its `openAPI()` plugin and
  `generateOpenAPISchema()` (see the elysiajs.com Better Auth integration).
- Keep docs off, or protected, in production unless the API is public.

## WebSocket, SSE, and streaming

- **WebSocket:** `.ws('/live', { body: t.Object(...), open, message, close
  })`. Bun's native pub/sub (`ws.subscribe(topic)`, `server.publish`) only
  works within one process. For several processes or hosts, fan out through
  Postgres `LISTEN/NOTIFY` or Redis (`Bun.redis` pub/sub).
- **SSE:** `function* () { yield sse({ event: 'tick', data }) }`. Eden
  consumes it as an async iterator.
- **Streaming:** use generator handlers for large payloads, or AI token
  streams.

## Cookies and CORS

- `cookie: { session }` is a reactive proxy. Set
  `session.value/httpOnly/secure/sameSite/maxAge` directly, and define a
  cookie schema so types aren't `undefined`. Sign cookies with
  `new Elysia({ cookie: { secrets: env.COOKIE_SECRET, sign: ['session'] } })`.
  Better Auth manages its own cookies.
- `@elysia/cors`: list origins explicitly, with `credentials: true` for
  cookie auth. **Never** use `origin: true` with credentials in production.

## Performance

- **AOT is already on** (`aot: true` unless `ELYSIA_AOT=false`). Don't
  configure it. `precompile: true` compiles every route at startup rather than
  on first request. Consider it for latency-sensitive services, not for
  development.
- `response` schemas let Elysia use Exact Mirror for fast serialization and
  leak-proof output.
- Static responses (`.get('/up', 'ok')` with a literal value) are
  pre-rendered.
- **The runtime is single-threaded.** Keep handlers I/O-bound, and move CPU
  work to jobs or `new Worker(...)`. Scale out with containers. On Linux,
  `reusePort` is on by default, so several processes can share a port.
- **Measure** with `@elysia/server-timing` in staging and OpenTelemetry
  spans in production. Don't micro-benchmark; profile the real route (N+1
  queries and missing indexes dominate).
