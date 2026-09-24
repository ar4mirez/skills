# Concurrency

Go's model: goroutines are cheap, but each needs an **owner** that starts it,
can stop it, and waits for it. The snippets below were compiled and run
under `go test -race`.

## Contents
- Rules
- Fan-out with errgroup (bounded)
- A fixed worker pool
- sync.WaitGroup.Go
- Channels or mutexes?
- Cancellation and timeouts
- Background work in a service
- Leaks, races, and how to find them
- Pitfalls

## Rules

1. **Don't start a goroutine you can't stop.** Pass it a `ctx` or a done
   channel, and make the starter wait for it to exit.
2. **Bound the parallelism.** Unbounded fan-out (one goroutine per row or
   request) exhausts memory, file descriptors, and DB connections.
   `errgroup.SetLimit` or a fixed pool.
3. **Share memory by communicating, or guard it with a mutex, never
   neither.** Each shared variable has exactly one synchronization story.
4. **The sender closes a channel,** never the receiver, and only once.
5. **Keep APIs synchronous.** Let the caller choose concurrency;
   `retry.Do` blocks, and callers wrap it in a goroutine if they want.
6. **CPU-bound parallelism beyond GOMAXPROCS buys nothing.** Since Go 1.25,
   `GOMAXPROCS` follows the container's CPU quota automatically.

## Fan-out with errgroup (bounded)

```go
import "golang.org/x/sync/errgroup"

// FetchAll runs fetch for every id with at most limit in flight. The first
// error cancels ctx for the rest; results keep input order.
func FetchAll(ctx context.Context, ids []string, limit int, fetch func(context.Context, string) (string, error)) ([]string, error) {
	g, ctx := errgroup.WithContext(ctx)
	g.SetLimit(limit)
	out := make([]string, len(ids)) // each goroutine owns one index: no mutex needed
	for i, id := range ids {
		g.Go(func() error {
			v, err := fetch(ctx, id)
			if err != nil {
				return fmt.Errorf("fetch %s: %w", id, err)
			}
			out[i] = v
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return nil, err
	}
	return out, nil
}
```

- `g.Go` blocks once `limit` goroutines are running, which gives you
  backpressure for free.
- Writing to distinct slice indexes from different goroutines is race-free.
  Appending to a shared slice is not.
- Since Go 1.22, `i` and `id` are per-iteration, so the closure capture is
  correct without copies.
- `errgroup` returns only the first error. Collect all of them with a
  mutex-guarded slice and `errors.Join` when the caller needs them.

## A fixed worker pool

For a long-lived stream of jobs (a queue consumer), use N workers reading
one channel:

```go
func Pool(ctx context.Context, workers int, jobs <-chan int, handle func(context.Context, int)) {
	var wg sync.WaitGroup
	for range workers {
		wg.Go(func() {
			for {
				select {
				case <-ctx.Done():
					return
				case j, ok := <-jobs:
					if !ok { // the producer closed jobs: drain done
						return
					}
					handle(ctx, j)
				}
			}
		})
	}
	wg.Wait()
}
```

The producer owns `jobs` and closes it. `Pool` returns when either the
channel is drained or `ctx` is cancelled.

## sync.WaitGroup.Go

`wg.Go(f)` (1.25+) is `wg.Add(1); go func() { defer wg.Done(); f() }()`
in one call, and it can't get the `Add` placement wrong. `f` must not
panic. Call `Go` before `Wait` for the first batch. `go vet` reports
`wg.Add` inside the started goroutine (a race with `Wait`), and
`go fix` (`waitgroupgo`) rewrites the old three-line form.

## Channels or mutexes?

| Situation | Use |
|---|---|
| Protecting a map or counter touched by many goroutines | `sync.Mutex` (or `sync/atomic` types for a single number) |
| Handing ownership of data from one goroutine to another | an unbuffered or small buffered channel |
| Signalling "stop" to many goroutines | `ctx.Done()` or `close(done)` |
| Waiting for N goroutines | `sync.WaitGroup` / `errgroup` |
| Lazy one-time init | `sync.OnceValue(func() T { ... })` |
| Read-mostly config swapped at runtime | `atomic.Pointer[Config]` |

Keep the mutex next to the fields it guards, lock for the shortest time, and
never call out (I/O, callbacks) while holding it. Don't copy structs that
contain a mutex; `go vet` (copylocks) catches it.

## Cancellation and timeouts

- Every blocking call takes `ctx`: `db.Query(ctx, ...)`,
  `http.NewRequestWithContext(ctx, ...)`, and `select { case <-ctx.Done(): }`
  around channel operations.
- Add deadlines where the work starts: `ctx, cancel :=
  context.WithTimeout(ctx, 2*time.Second); defer cancel()` (the template's
  `/up` DB ping).
- Surface *why* it stopped: `context.Cause(ctx)`,
  `context.WithCancelCause`, and `context.WithTimeoutCause`. Since 1.26,
  `signal.NotifyContext`'s cause names the signal.
- `context.WithoutCancel(ctx)` keeps values but drops cancellation. The
  template uses it for the shutdown deadline, because the parent is already
  cancelled by SIGTERM.
- `time.After` in a loop allocates a timer per iteration. Use one
  `time.NewTimer` and `Stop`/`Reset` it (since 1.23, unstopped timers are
  collected, but reuse is still clearer).

## Background work in a service

Run long-lived loops under the same lifecycle as the server:

```go
g, ctx := errgroup.WithContext(ctx)           // ctx comes from signal.NotifyContext
g.Go(func() error { return server.Serve(ctx, ln, handler, log, 8*time.Second) })
g.Go(func() error { return janitor.Run(ctx) })  // returns nil on ctx.Done()
return g.Wait()
```

If either fails, the other is cancelled, and `main` exits non-zero. Don't
fire `go sendEmail()` from a handler: the request context dies with the
response, and shutdown won't wait for it. Enqueue a job (a Postgres table
polled with `FOR UPDATE SKIP LOCKED`, or River) or hand it to an owned
worker pool.

## Leaks, races, and how to find them

- **`go test -race ./...` in CI, always.** The detector finds races that
  actually execute, so tests must exercise the concurrent paths (and
  `t.Parallel` helps). Expect 5-10x memory and 2-20x CPU; don't ship
  `-race` builds.
- **Goroutine leaks:** the `goroutineleak` profile (GA in 1.27,
  `/debug/pprof/goroutineleak`) reports goroutines blocked on primitives
  nothing can unblock. In tests, `synctest.Test` waits for every goroutine
  in the bubble to exit and fails the test if they deadlock.
- `runtime/pprof` goroutine labels now appear in traceback headers (1.27;
  `GODEBUG=tracebacklabels=0` turns it off), so label worker goroutines with
  `pprof.Do` to see which pool is stuck.
- `runtime/trace.FlightRecorder` (1.25+) keeps the last seconds of execution
  trace in memory. Dump it when a latency SLO is violated.

## Pitfalls

- A send on an unbuffered channel with no receiver blocks forever (the
  classic leak when a caller times out). Give result channels a buffer of 1
  so the worker can always finish.
- `select` with `default` in a loop is a busy-wait; block on a channel
  instead.
- Closing a channel twice, or sending on a closed one, panics.
- A nil channel blocks forever. This is useful to disable a `select` case,
  and a bug anywhere else.
- Inside `synctest.Test`, don't call `t.Run`, `t.Parallel`, or
  `t.Deadline` on the bubble's `t`; call `t.Parallel` on the outer test.
- Maps aren't safe for concurrent writes: the runtime *crashes*
  ("concurrent map writes"); it doesn't just corrupt data.

Sources: https://go.dev/ref/mem, https://go.dev/doc/articles/race_detector,
https://pkg.go.dev/golang.org/x/sync/errgroup, https://pkg.go.dev/sync#WaitGroup.Go,
https://go.dev/blog/synctest, https://go.dev/doc/go1.27
