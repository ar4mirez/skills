# Testing

## Contents
- Runner choice
- Layout and style
- Unit tests
- HTTP handlers (`app.request`)
- Outbound HTTP (msw)
- Type tests (`expectTypeOf` + tsc)
- Property tests (fast-check)
- Coverage
- Benchmarks
- Integration tests with real services
- Pitfalls

## Runner choice

- **Vitest 5** for Node projects and libraries (this skill's default).
  Runs `.ts` natively, fast watch mode, `vi` mocks, coverage via
  `@vitest/coverage-v8`, `expectTypeOf`.
- **`bun test`** in Bun projects (bun-elysia skill). Don't mix runners in
  one package.
- `node:test` is fine for zero-dependency packages, but you lose
  `expectTypeOf`, msw ergonomics, and coverage thresholds in one place.

Vitest needs no config for plain Node packages; add `vitest.config.ts`
only for coverage thresholds, setup files, or environments.

## Layout and style

- `foo.ts` + `foo.test.ts` side by side; included by the package tsconfig
  so `tsc --noEmit` checks tests too.
- `describe` per unit, `it('does X when Y')`, `it.each` for tables.
- Arrange data inline; tiny builder functions over fixture frameworks.
- Inject time, randomness, and I/O (`now: () => Date`, `random: () =>
  number`, `io.fetch`) instead of mocking modules. `vi.mock` of your own
  modules usually means a missing parameter.
- Fake timers (`vi.useFakeTimers()`) for backoff logic, or inject the
  delay function; the retry tests pass `random: () => 0` to make backoff
  zero.

## Unit tests

Test behavior through the public function, including error paths and
aborts:

```ts
it('stops when the signal aborts during backoff', async () => {
  const controller = new AbortController()
  const fn = vi.fn(() => { controller.abort(new Error('shutdown')); return Promise.reject(new Error('transient')) })
  await expect(retry(fn, { signal: controller.signal, baseDelayMs: 10_000 })).rejects.toThrow('transient')
  expect(fn).toHaveBeenCalledTimes(1)
})
```

## HTTP handlers (`app.request`)

Build the app with injected dependencies and call it without a socket:

```ts
const app = createApp({ store: memoryStore(), logger: pino({ level: 'silent' }) })
const res = await app.request('/links', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
expect(res.status).toBe(201)
```

Cover: happy path, validation (422 for each class of bad input: wrong
type, unknown key, dangerous URL scheme), conflicts, not found, and that
the error handler hides internals (500 with a generic body). Fastify's
equivalent is `app.inject()`.

## Outbound HTTP (msw)

msw intercepts `fetch` at the network layer, so the code under test runs
unchanged:

```ts
const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

server.use(http.get(`${BASE}/v1/preview`, () => new HttpResponse(null, { status: 503 })))
```

`onUnhandledRequest: 'error'` makes a forgotten handler a failure instead
of a real network call. Test: success, retry on 5xx, no retry on 4xx,
invalid body rejected by the schema, and the caller's abort. pnpm 11+
blocks msw's postinstall; set `allowBuilds: { msw: false }` (the script
only copies the browser service worker).

## Type tests (`expectTypeOf` + tsc)

Pick `expectTypeOf` (built into Vitest) over tsd. Write type assertions in
normal test files:

```ts
it('infers the result type from fn', () => {
  expectTypeOf(retry(() => Promise.resolve(42))).toEqualTypeOf<Promise<number>>()
})
```

**`vitest run` does not check types**: `expectTypeOf` is a no-op at run
time, so a wrong assertion passes the test run (verified). The assertion is
enforced by `tsc --noEmit` over the test files, which the gate runs
anyway. `vitest --typecheck` also works with TS 7 (verified) but is
labelled experimental; `tsc` is enough. Use `// @ts-expect-error: <why>`
to assert that something must *not* compile.

## Property tests (fast-check)

For pure functions with invariants (parsers, encoders, pools):

```ts
await fc.assert(fc.asyncProperty(fc.array(fc.integer()), fc.integer({ min: 1, max: 16 }), async (items, limit) => {
  expect(await mapLimit(items, limit, async (n) => n + 1)).toEqual(items.map((n) => n + 1))
}))
```

fast-check 4.x; failures print a shrunk counterexample and a seed to
replay.

## Coverage

```ts
// vitest.config.ts
coverage: { provider: 'v8', include: ['src/**/*.ts'], thresholds: { lines: 80, branches: 80, functions: 80, statements: 80 } }
```

Run `vitest run --coverage`; a miss fails the run (verified: 74% branches
failed the 80% gate until the error paths had tests). Thresholds are a
floor, not a goal; branch coverage finds untested error handling.

## Benchmarks

`vitest bench` with `bench()` blocks in `*.bench.ts` for micro-benchmarks,
run on a quiet machine and compared before/after. For services, measure
with a load tool against a production build (`autocannon`, `oha`, or `k6`)
and profile (see `services-and-deploy.md`) before optimizing.

## Integration tests with real services

- Postgres/Redis: a real instance in CI (a GitHub Actions service
  container), a database per test file or a transaction rolled back per
  test. No in-memory fakes for SQL semantics.
- Keep them in the same runner, tagged by file name (`*.int.test.ts`) and
  a separate script if they need infrastructure.
- Library runtime matrix: CI runs the library tests on Node 22, 24, 26 and
  a Bun smoke import (`assets/github-ci.yml`).

## Pitfalls

- Tests that pass because the promise under test was never awaited: always
  `await expect(p).rejects…` / `resolves…`.
- Shared mutable state between tests (module singletons): build fresh
  dependencies per test (`setup()` functions).
- Snapshot tests for logic: assert the values that matter instead.
- Real timers with long backoffs: inject randomness/delay or use fake
  timers.
- Mocking `fetch` with `vi.fn` in integration-style tests: use msw so
  headers, bodies, and status codes behave like the network.
