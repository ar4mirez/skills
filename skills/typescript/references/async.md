# Async: promises, cancellation, concurrency

## Contents
- The model
- No floating promises
- Deadlines with AbortSignal
- Retries
- Bounded concurrency
- Errors in async code
- Shutdown and cleanup
- Pitfalls

## The model

One thread runs your JavaScript; I/O happens concurrently underneath.
Anything slow and CPU-bound (hashing, image work, big JSON) blocks every
request: move it to a `Worker` (`node:worker_threads`), a separate process,
or a job. Everything else is `async`/`await` over promises.

## No floating promises

Every promise is awaited, returned, or explicitly handed off:

```ts
await save(x)                        // normal
return save(x)                       // caller awaits
void sendMetrics().catch((error) => logger.warn({ err: error }, 'metrics failed')) // fire-and-forget, on purpose
```

A floating promise's rejection becomes an `unhandledRejection`, which
**crashes Node by default** (`--unhandled-rejections=throw`), and its work
isn't ordered with anything. Common forms:
- `items.forEach(async (x) => …)`: forEach ignores the promises. Use
  `for … of` with `await` (sequential) or `Promise.all(items.map(…))`
  (concurrent, bounded; see below).
- An async function passed where a sync callback is expected
  (`setTimeout(async () => …)`, event emitters, `if (promise)`).
- Calling an async method without `await` in a loop.

Enforce it: Biome's `nursery/noFloatingPromises` and
`nursery/noMisusedPromises` catch calls to functions it can infer in your
own code; oxlint's type-aware `typescript/no-floating-promises` also sees
functions from dependencies (see `quality-and-security.md`).

## Deadlines with AbortSignal

Every outbound call has a deadline, and cancellation propagates:

```ts
const res = await fetch(url, {
  signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(2_000)]) : AbortSignal.timeout(2_000),
})
```

- `AbortSignal.timeout(ms)` aborts with a `TimeoutError` DOMException;
  a manual `controller.abort()` gives `AbortError` (or your reason).
- `AbortSignal.any([...])` combines the caller's signal with a local
  deadline.
- Functions that do I/O accept `signal?: AbortSignal` as their last
  parameter or an option, pass it to every `fetch`/driver call, and call
  `signal?.throwIfAborted()` between steps.
- Hono gives the request's signal as `c.req.raw.signal`; pass it down so a
  client disconnect stops the work.
- A timeout is a *budget*: when a handler has 5 s, its three calls don't
  each get 5 s.

## Retries

Retry only idempotent operations, only on transient failures (5xx,
network errors, 429 with `Retry-After`), with capped exponential backoff
and full jitter, and never after an abort. `assets/retry.ts` implements
exactly that (with `shouldRetry` and the caller's signal). Put the retry
around the whole attempt, including body parsing.

## Bounded concurrency

`Promise.all(items.map(fn))` over 5 000 items opens 5 000 sockets. Bound
it:

```ts
const results = await mapLimit(urls, 8, (url, signal) => check(url, signal))
```

`assets/pool.ts` (`mapLimit`) keeps order, caps in-flight work, and
aborts siblings on the first failure. Alternatives: `p-limit` if you
already depend on it; a stream pipeline for unbounded input.
`Promise.allSettled` when every result matters and failures are data.

## Errors in async code

- `await` inside `try` catches rejections; `return promise` without
  `await` inside `try` does not (use `return await` there).
- Wrap with `cause` when crossing a layer:
  `throw new Error(\`fetch preview ${url}\`, { cause: error })`.
- `Promise.all` rejects on the first error but the other promises keep
  running; pass them a shared signal and abort it (as `mapLimit` does).
- `process.on('unhandledRejection')` is a last-resort logger in `main`, not
  error handling.

## Shutdown and cleanup

- `using`/`await using` for scoped resources (verified on Node 24 and
  Bun 1.4); `try/finally` otherwise.
- Services: on SIGTERM stop accepting, finish in-flight work, close pools,
  then let the process exit; force-exit after a deadline shorter than the
  orchestrator's kill timeout (see `services-and-deploy.md`).
- Timers that must not keep the process alive: `.unref()`.

## Pitfalls

- `async` functions without `await` (Biome `useAwait`) usually mean a
  missing `await` or a function that shouldn't be async.
- `await` in a loop is sequential; fine for ordered work, slow for
  independent calls.
- `setTimeout`-based sleeps without a signal can't be cancelled; use
  `sleep(ms, signal)` (in `assets/retry.ts`) or
  `node:timers/promises` `setTimeout(ms, undefined, { signal })`.
- Mixing callbacks and promises: wrap once with `util.promisify` or the
  `node:` promise APIs (`node:fs/promises`, `node:stream/promises`).
- Top-level `await` is fine in ESM entry points; avoid it in library
  modules (it blocks every importer).
