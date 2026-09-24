# Performance

Measure, change one thing, and measure again. Most Go services are bound by
the database or the network, not the CPU, so profile before rewriting.

## Contents
- The workflow
- Profiling from benchmarks
- Profiling a running service
- Reading profiles
- Allocations and escape analysis
- Memory, GC, and GOMAXPROCS
- Profile-guided optimization (PGO)
- Common wins
- Things that are rarely worth it

## The workflow

1. Define the metric (p99 latency, throughput, RSS, allocs/op).
2. Reproduce it with a benchmark (`b.Loop`, `b.ReportAllocs`) or a load test
   against a production-like build.
3. Profile (CPU, heap, allocs, block, mutex, trace).
4. Fix the biggest item only.
5. Compare with benchstat (`-count 10` on both sides) and keep the benchmark
   as a regression guard.

## Profiling from benchmarks

```bash
go test -run '^$' -bench BenchmarkNormalizeURL -benchmem -count 10 ./internal/link > old.txt
go test -run '^$' -bench BenchmarkNormalizeURL -cpuprofile cpu.out -memprofile mem.out ./internal/link
go tool pprof -http=:0 cpu.out          # flame graph is the default view since 1.26
go tool pprof -sample_index=alloc_space -http=:0 mem.out
go run golang.org/x/perf/cmd/benchstat@latest old.txt new.txt
```

The template's `BenchmarkNormalizeURL` measured 581 ns/op, 192 B/op, 2
allocs/op on an M-series laptop. Use such numbers as a baseline for your
own hardware, not as a target.

## Profiling a running service

Mount pprof on a **separate, private** listener, never the public mux:

```go
import "net/http/pprof"

debug := http.NewServeMux()
debug.HandleFunc("/debug/pprof/", pprof.Index)       // also serves heap, goroutine, allocs, ...
debug.HandleFunc("/debug/pprof/profile", pprof.Profile)
debug.HandleFunc("/debug/pprof/trace", pprof.Trace)

var lc net.ListenConfig
debugLn, err := lc.Listen(ctx, "tcp", "127.0.0.1:6060")  // loopback only; reach it with ssh -L
if err != nil {
	return err
}
g.Go(func() error { return server.Serve(ctx, debugLn, debug, log, time.Second) }) // same errgroup as the main server
```

```bash
go tool pprof -http=:0 "http://127.0.0.1:6060/debug/pprof/profile?seconds=30"   # pprof extends the write deadline itself
go tool pprof http://127.0.0.1:6060/debug/pprof/heap
curl -o trace.out "http://127.0.0.1:6060/debug/pprof/trace?seconds=5" && go tool trace trace.out
```

- `goroutine?debug=2` shows every stack (find leaks and deadlocks).
  `goroutineleak` (1.27) shows only provably-stuck goroutines.
- `block` and `mutex` profiles need `runtime.SetBlockProfileRate` /
  `SetMutexProfileFraction`. Enable them briefly, not permanently.
- `runtime/trace.FlightRecorder` (1.25+) keeps a rolling in-memory trace
  window. Snapshot it when a slow request is detected.
- `go tool trace -http=:6060` now binds localhost only (1.27); pass
  `0.0.0.0:6060` explicitly to expose it.

## Reading profiles

- **flat** is time in the function itself; **cum** includes callees. Start
  from the widest flame-graph bars, not the top of `top10`.
- High `runtime.mallocgc`/`gcBgMarkWorker` means allocation pressure: go to
  the alloc profile.
- High `syscall`/`netpoll` means I/O-bound: look at queries, round trips,
  and connection pools, not Go code.
- In `list FuncName`, the per-line costs point at the exact expression.

## Allocations and escape analysis

```bash
go build -gcflags='-m' ./internal/link 2>&1 | grep -E 'escapes|moved to heap'
```

- Values escape to the heap when their address outlives the frame (returned
  pointers, stored in interfaces or closures, sent on channels). Returning
  values instead of pointers for small structs often avoids it.
- Preallocate: `make([]T, 0, n)` when `n` is known; `strings.Builder` with
  `Grow`; `slices.Grow`.
- Reuse buffers on hot paths with `sync.Pool` (for `*bytes.Buffer`, and
  `Reset` before `Put`). Measure first; pools add complexity.
- Avoid `[]byte` ↔ `string` conversions in loops; many stdlib APIs have
  both forms (`bytes.Cut`, `strings.Cut`).
- Converting a value to `any` (logging, `fmt`) allocates. Keep `fmt.Sprintf`
  out of hot loops; use `strconv.AppendInt` and friends.
- Go 1.27 made small allocations about 30% cheaper and Go 1.25/1.26 put more
  slice backing stores on the stack, so re-measure after upgrading before
  hand-optimizing.

## Memory, GC, and GOMAXPROCS

- The Green Tea GC (default since 1.26) cut GC CPU 10-40% for typical
  heaps. `GOEXPERIMENT=nogreenteagc` is the escape hatch while diagnosing.
- **Set `GOMEMLIMIT` in containers** to ~90% of the memory limit (for
  example `GOMEMLIMIT=460MiB` for a 512 MiB container). The GC works harder
  near the limit instead of getting OOM-killed. Keep `GOGC` at its default
  unless profiles show GC dominating CPU.
- `GOMAXPROCS` follows cgroup CPU limits automatically since 1.25; delete
  `go.uber.org/automaxprocs`.
- Maps never shrink. Rebuild a map that grew large and emptied, or bound it.
  For caches, bound size (LRU) or hold values via `weak.Pointer`.
- `runtime/metrics` exposes heap, GC, and scheduler metrics
  (`/sched/goroutines` since 1.26) for dashboards.

## Profile-guided optimization (PGO)

Grab a representative 30s CPU profile from production, save it as
`default.pgo` in the **main package directory** (`cmd/links/default.pgo`),
and commit it. `go build` picks it up automatically (`-pgo=auto`), and
typical gains are a few percent of CPU from better inlining and
devirtualization. Refresh it every few releases. It's harmless when stale.

## Common wins

1. **Database:** N+1 queries → one query with `= ANY($1)`, a missing index
   (check with `EXPLAIN ANALYZE`), and pool size vs. Postgres
   `max_connections`. `pgx.Batch` for many small statements.
2. **HTTP clients:** reuse one `http.Client` (connection pooling). Drain and
   close bodies so connections return to the pool. Raise
   `Transport.MaxIdleConnsPerHost` (default 2) for chatty single-host clients.
3. **JSON:** `encoding/json/v2` decodes substantially faster than v1.
   Stream with `UnmarshalRead`/`MarshalWrite` instead of buffering whole bodies.
4. **Concurrency:** bound parallelism to the real bottleneck (DB
   connections), and avoid global mutex contention (shard, or use
   `sync.Map` only for append-mostly caches).
5. **Logging:** check `log.Enabled(ctx, slog.LevelDebug)` before building
   expensive debug attributes.

## Things that are rarely worth it

`unsafe` string/byte tricks, hand-rolled assembly (look at the experimental
`simd` package first, with `GOEXPERIMENT=simd`), object pools for small
structs, and replacing `net/http` with fasthttp. Each gives up safety or
compatibility for gains a profile rarely justifies.

Sources: https://go.dev/doc/diagnostics, https://go.dev/doc/gc-guide,
https://go.dev/doc/pgo, https://pkg.go.dev/net/http/pprof,
https://pkg.go.dev/runtime/trace#FlightRecorder, https://go.dev/doc/go1.26
