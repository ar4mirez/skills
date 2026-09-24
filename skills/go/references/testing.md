# Testing

Only the standard `testing` package: no assertion library and no mock
generator. Every pattern here is in the assets and passed `go test -race`,
including the Postgres integration test against a real database.

## Contents
- Layers: what to test where
- Table-driven tests and t.Parallel
- Fakes, not mocks
- HTTP tests
- Integration tests against Postgres
- Time and concurrency: testing/synctest
- Fuzzing
- Benchmarks
- Examples
- Coverage and the CI gate
- Pitfalls

## Layers: what to test where

| Layer | How | Share |
|---|---|---|
| Domain (`link.Service`, validation) | Plain calls with an in-memory fake store; table-driven | Most |
| HTTP contract | `httptest.NewRecorder` + the real mux: status codes, error mapping, limits | Some |
| Store/SQL | A real Postgres, one rolled-back transaction per test | Some |
| `main`/CLI | Call `run(ctx, args, getenv, stdout)` with fake args and env | Few |
| End to end | Start the binary, or `Serve` on `127.0.0.1:0`, and hit it | Very few |

## Table-driven tests and t.Parallel

```go
func TestNormalizeURL(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		in      string
		want    string
		wantErr bool
	}{
		{name: "https", in: "https://go.dev/doc", want: "https://go.dev/doc"},
		{name: "user info", in: "https://bank.com@evil.example/", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			got, err := link.NormalizeURL(tt.in)
			...
		})
	}
}
```

- Name cases; `go test -run 'TestNormalizeURL/user_info'` then runs one.
- Failure messages say `Func(input) = got, want want`, and use `t.Fatalf`
  when continuing is pointless.
- `t.Parallel()` in both the parent and the subtests. Parallel tests must
  not share mutable state: build a fresh fake per case.
- `t.Context()` (1.24+) is cancelled when the test ends. Use it instead of
  `context.Background()`.
- Use `t.Helper()` in helpers, `t.Cleanup` for teardown, `t.TempDir()` for
  files, `t.Setenv` (it forbids `t.Parallel`, so prefer injecting `getenv`),
  and `t.ArtifactDir()` (1.26) for outputs to keep with `-artifacts`.
- Compare structs with `==` or `reflect.DeepEqual`. For readable diffs of
  large values, `github.com/google/go-cmp/cmp` is the one test dependency
  worth adding.
- Black-box by default: `package link_test` tests the public API. Use an
  internal test (`package link`) only for unexported logic that can't be
  reached otherwise.

## Fakes, not mocks

The consumer-owned `Store` interface makes a 50-line in-memory fake
(`assets/fake_test.go`) possible. It's guarded by a mutex (so it's safe under
`-race`) and has an `err` field to inject failures. Fakes test behavior;
generated mocks test call sequences and break on every refactor.

## HTTP tests

```go
req := httptest.NewRequestWithContext(t.Context(), "POST", "/api/links", strings.NewReader(body))
rec := httptest.NewRecorder()
mux.ServeHTTP(rec, req)
if rec.Code != http.StatusCreated { ... }
```

- Test through the **real mux**, so patterns, 405s, and path values are
  covered.
- Cover each error mapping (400, 404, 409, 413, 422, 500), and assert that
  500 bodies don't leak internals (`http_test.go` plants
  `password=hunter2` in the error and checks it never reaches the client).
- For client code or full-stack tests, use `httptest.NewServer` (a real
  loopback) or `httptest.NewTestServer(t, h)` (1.27, in-memory network, and
  compatible with synctest).
- The graceful-shutdown test (`server_test.go`) holds a request open with a
  channel, cancels the server context, and asserts that the request still
  completes with 200 and `Serve` returns nil. It uses no sleeps.

## Integration tests against Postgres

`assets/postgres_test.go` skips unless `TEST_DATABASE_URL` is set. It
migrates with the same `db.Migrate` the binary uses, opens one transaction,
runs the store against it, and rolls back in `t.Cleanup`. That means no
truncation, no ordering dependencies, and it's safe to run in parallel.

```bash
TEST_DATABASE_URL=postgres://postgres:postgres@localhost:5432/links_test go test -race ./...
```

- CI provides Postgres as a service container (`assets/github-ci.yml`).
- A failed statement aborts the transaction, so assert the expected
  constraint violation (duplicate code → `ErrCodeTaken`) **last**.
- Locally, any Postgres works. testcontainers-go (v0.44) can start one per
  package when Docker is available, but it adds a heavy dependency; a CI
  service container plus an env var is simpler.

## Time and concurrency: testing/synctest

```go
synctest.Test(t, func(t *testing.T) {
	err := retry.Do(t.Context(), retry.Default, flakyOp)   // backoff sleeps take zero real time
	...
})
```

- Inside the bubble, `time` uses a fake clock that advances only when every
  goroutine is durably blocked. Timers, `time.Sleep`, and
  `context.WithTimeout` are deterministic and instant.
- `synctest.Wait()` blocks until the other goroutines in the bubble are
  blocked. `synctest.Sleep(d)` (1.27) is `time.Sleep(d)` followed by
  `Wait()`.
- Real network I/O isn't durably blocking. Use in-memory pipes (`net.Pipe`)
  or `httptest.NewTestServer`.
- Don't call `t.Parallel`/`t.Run` on the bubble's `t`. Parallelize the
  outer test instead (`retry_test.go` does this).
- Replace `time.Sleep` in tests with synctest or explicit synchronization
  (channels). The audit flags `time.Sleep` in `_test.go` files.

## Fuzzing

```go
func FuzzNormalizeURL(f *testing.F) {
	for _, seed := range []string{"https://go.dev", "javascript:x", "https://u:p@h/"} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, in string) {
		out, err := link.NormalizeURL(in)
		if err != nil {
			return
		}
		// properties, not examples: accepted output is absolute http(s), and normalizing is idempotent
	})
}
```

- `go test` runs the seeds as regular tests. Fuzz locally with
  `go test -run '^$' -fuzz FuzzNormalizeURL -fuzztime 30s ./internal/link`
  (one fuzz target per invocation).
- Failing inputs are written to `testdata/fuzz/FuzzXxx/`. Commit them; they
  become permanent regression cases.
- Fuzz parsers, validators, decoders, and anything that handles untrusted
  bytes. Assert invariants (round-trips, idempotence, no panic).

## Benchmarks

```go
func BenchmarkNormalizeURL(b *testing.B) {
	b.ReportAllocs()
	for b.Loop() {
		if _, err := link.NormalizeURL("https://go.dev/doc/go1.27?utm_source=x#top"); err != nil {
			b.Fatal(err)
		}
	}
}
```

- `b.Loop()` (1.24+) replaces `for i := 0; i < b.N; i++`: setup before the
  loop isn't timed, results aren't optimized away, and since 1.26 it doesn't
  inhibit inlining.
- Compare runs with benchstat, not by eyeballing:
  `go test -run '^$' -bench . -count 10 > old.txt`, change the code, repeat to
  `new.txt`, then `go run golang.org/x/perf/cmd/benchstat@latest old.txt new.txt`.
- See `performance.md` for profiling from benchmarks.

## Examples

`func ExampleDo()` with an `// Output:` comment is a test **and**
documentation on pkg.go.dev (`assets/retry_example_test.go`). Write one per
main entry point of a library.

## Coverage and the CI gate

```bash
go test -race -shuffle=on -coverprofile=cover.out ./...
go tool cover -func=cover.out | tail -1      # total
go tool cover -html=cover.out                # where the gaps are
```

- `-shuffle=on` randomizes test order and surfaces hidden dependencies
  between tests.
- Treat coverage as a map of untested code, not a target. Domain packages
  should be high (the template's `server` is ~90% and `link` ~74% without
  Postgres). Generated code and `main` wiring don't need 100%.
- Integration coverage across packages: `-coverpkg=./...`.
- `go build -cover` instruments a binary for end-to-end coverage
  (`GOCOVERDIR`).

## Pitfalls

- A test that only passes with `-count=1` is caching-dependent or stateful.
  `go test` caches passing results; `-count=1` forces a rerun.
- `t.Fatal` from a goroutine other than the test's doesn't stop the test
  correctly. Report with `t.Error` and return, or send the error back on a
  channel.
- `os.Exit` or `log.Fatal` in code under test kills the whole test binary.
- Tests relying on map iteration order are flaky; sort first.
- `init()` doing I/O runs for every test binary. Keep it out of code.

Sources: https://pkg.go.dev/testing, https://go.dev/doc/security/fuzz/,
https://pkg.go.dev/testing/synctest, https://go.dev/blog/testing-b-loop,
https://go.dev/wiki/TableDrivenTests, https://pkg.go.dev/golang.org/x/perf/cmd/benchstat
