# I/O, networking, and concurrency in Zig 0.16

0.16 made I/O an **interface**: anything that blocks or is nondeterministic (files,
sockets, time, randomness, child processes, mutexes) goes through an `std.Io` value. The
snippets here compiled and ran on 0.16.0, and `assets/server.zig` is tested over a real
socket.

## Contents
- Getting an Io: Juicy Main
- Readers and writers
- Files and directories
- Environment, args, and time
- Networking and the HTTP server
- HTTP client
- Concurrency: async, concurrent, Group, cancelation
- Synchronization
- Choosing the Io implementation
- Pitfalls

## Getting an Io: Juicy Main

```zig
pub fn main(init: std.process.Init) !void {
    const gpa = init.gpa;          // general allocator (leak-checked in Debug)
    const io = init.io;            // Io.Threaded, chosen for the target
    const arena = init.arena.allocator();                 // process-lifetime allocations
    const args = try init.minimal.args.toSlice(arena);    // []const [:0]const u8
    const port = init.environ_map.get("PORT");            // ?[]const u8
    ...
}
```

`main` can take nothing, `std.process.Init.Minimal` (raw args and environ only), or
`std.process.Init`. **`main` is the only place that constructs an `Io`**; everything
below takes `io: std.Io` as a parameter (or stores it in a context struct), exactly like
an allocator. In tests, use `std.testing.io`. When upgrading old code with no `Io` in
reach, `var t: Io.Threaded = .init_single_threaded; const io = t.io();` works, but it's a
stopgap, like reaching for `page_allocator`.

## Readers and writers

`std.Io.Reader` and `std.Io.Writer` are concrete, non-generic interfaces, and **the buffer
lives in the interface**:

```zig
var buf: [4096]u8 = undefined;
var fw: std.Io.File.Writer = .init(.stdout(), io, &buf);
const out = &fw.interface;                 // *std.Io.Writer
try out.print("{d} items\n", .{n});
try out.flush();                           // nothing reaches the fd until you flush

var fr = file.reader(io, &read_buf);       // std.Io.File.Reader
while (try fr.interface.takeDelimiter('\n')) |line| { ... }   // null at end of stream
```

- **Functions take `*std.Io.Writer` / `*std.Io.Reader`**, never a concrete file or
  socket. Tests then pass `std.Io.Reader.fixed(bytes)` / `std.Io.Writer.fixed(&buf)`, or
  `std.Io.Writer.Allocating` (`.init(gpa)`, `.written()`, `.toOwnedSlice()`).
- Line and delimiter reads return slices **into the reader's buffer**. They're valid until
  the next read, and a line longer than the buffer returns `error.StreamTooLong`. Size the
  buffer to your maximum record, or copy out.
- `error.ReadFailed` / `error.WriteFailed` are deliberately opaque. The concrete reader
  keeps the real cause (`file_reader.err.?`, `net_reader.err`).
- To read a whole bounded input: `try reader.allocRemaining(gpa, .limited(max))`
  (`error.StreamTooLong` past `max`), or
  `std.Io.Dir.cwd().readFileAlloc(io, path, gpa, .limited(max))`.
- One unbuffered write: `try std.Io.File.stdout().writeStreamingAll(io, bytes)`.

## Files and directories

`std.fs.cwd()`, `std.fs.File`, and `std.fs.Dir` became `std.Io.Dir` / `std.Io.File`, and
every call takes `io`: `std.Io.Dir.cwd().openFile(io, path, .{})`, `file.close(io)`,
`dir.createDirPath(io, "a/b")` (was `makePath`), `dir.walk(gpa)` + `walker.next(io)`.
`std.fs.path` still works but is deprecated in favor of `std.Io.Dir.path`. For atomic
replace-on-write, use `std.Io.File.Atomic` (temp file, then rename).

## Environment, args, and time

- The environment and argv aren't global any more (`std.os.getenv`,
  `std.process.getEnvVarOwned`, and `std.process.argsAlloc` are gone). Read them in `main`
  and pass the values (or `*const std.process.Environ.Map`) down, which makes config
  testable: `Config.fromEnv(&map)` in `assets/server.zig`.
- Time: `std.Io.Timestamp.now(io, .awake)` (monotonic), `.real` (wall clock),
  `ts.untilNow(io, .awake)` returns an `Io.Duration` (print it with `{f}`).
  `io.sleep(.fromMilliseconds(n), .awake)`. `std.time.sleep`, `milliTimestamp`, `Instant`,
  and `Timer` were removed. `std.time.ns_per_ms` and friends remain.
- Randomness: `io.random(&buf)` (fast; may keep CSPRNG state in process memory) or
  `try io.randomSecure(&buf)` (always a fresh syscall, for keys and tokens).
  `const src: std.Random.IoSource = .{ .io = io }; const rng = src.interface();` gives a
  `std.Random`. `std.crypto.random` is gone.
- Child processes: `std.process.spawn(io, .{ .argv = argv, .stdout = .pipe })`,
  `std.process.run(gpa, io, .{ .argv = argv })`. `Child.init` is gone.

## Networking and the HTTP server

```zig
const addr: std.Io.net.IpAddress = try .parse("0.0.0.0", port);
var listener = try addr.listen(io, .{ .reuse_address = true });
defer listener.deinit(io);
const stream = try listener.accept(io);          // std.Io.net.Stream
var r = stream.reader(io, &recv_buf);            // .interface: std.Io.Reader
var w = stream.writer(io, &send_buf);            // .interface: std.Io.Writer
var http_server: std.http.Server = .init(&r.interface, &w.interface);
var req = try http_server.receiveHead();         // error.HttpConnectionClosing on EOF
try req.respond("ok\n", .{ .status = .ok, .extra_headers = &.{...} });   // flushes
```

- `std.http.Server` speaks HTTP/1.1 only (keep-alive, chunked encoding, and WebSocket
  upgrade). There's no router and no TLS. Terminate TLS in kamal-proxy or Cloudflare.
- **Route before reading the body.** `request.readerExpectContinue(&buf)` and
  `readerExpectNone` invalidate every string in `request.head` (`target`, headers). Copy
  anything you need to log first.
- Bound everything: the receive buffer is the maximum header size
  (`error.HttpHeadersOversize` beyond it), check `head.content_length` before reading,
  and read bodies with `allocRemaining(arena, .limited(max))`. There are **no per-socket
  read timeouts** in `std.http.Server`, so keep a buffering proxy (kamal-proxy
  `buffering.requests: true`, Cloudflare) in front of it so slow clients never reach it.
- Port 0 picks a free port: `listener.socket.address.getPort()` (used by the socket test).
- The whole pattern, with one task per connection and one arena per request, is
  `assets/server.zig`. It mirrors the std build system's own web server
  (`lib/std/Build/WebServer.zig`).

Use a third-party HTTP framework only when you need routing, middleware, or performance
the std server lacks, and after checking that the package declares 0.16 support in its
`build.zig.zon`. Many Zig packages lag a release behind.

## HTTP client

```zig
var client: std.http.Client = .{ .allocator = gpa, .io = io };
defer client.deinit();
var body: std.Io.Writer.Allocating = .init(gpa);
defer body.deinit();
const res = try client.fetch(.{ .location = .{ .url = url }, .method = .POST,
    .payload = json_bytes, .response_writer = &body.writer });
if (res.status != .ok) return error.UpstreamFailed;
```

DNS resolution and connection attempts run concurrently through `io`. TLS uses the system
CA bundle.

## Concurrency: async, concurrent, Group, cancelation

| API | Meaning | Fails? |
|---|---|---|
| `io.async(f, args)` → `Future(T)` | f is *independent* of the caller; it may even run inline | Never |
| `io.concurrent(f, args)` → `Future(T)` | f *must* run at the same time (e.g. a producer the caller waits on) | `error.ConcurrencyUnavailable` |
| `var g: Io.Group = .init; g.async(io, f, args)` / `g.concurrent(...)` | Many tasks sharing one lifetime, O(1) per spawn | `concurrent` can fail |
| `Io.Queue(T)` | Bounded MPMC channel (`putOne`, `getOne`) | `error.Closed`, `error.Canceled` |
| `Io.Select`, `Io.Batch` | Wait for the first of several tasks; batch low-level ops | |

```zig
var task = io.async(fetchUser, .{ io, id });
defer if (task.cancel(io)) |user| user.deinit(gpa) else |_| {};  // always release the task
const user = try task.await(io);
```

- **Always pair a task with `defer ...cancel(io)`.** Cancel is idempotent and equals await
  plus a cancel request. It frees the task and handles the case where the task finished
  successfully anyway (release its resources).
- Group tasks return `Io.Cancelable!void` (errors other than `Canceled` must be handled
  inside the task). `defer group.cancel(io);` before spawning, and `try group.await(io);`
  to join.
- **Cancelation:** most I/O returns `error.Canceled` once cancel is requested. Propagate
  it. Only the code that requested cancelation may swallow it. CPU-bound loops can add
  `try io.checkCancel();`.
- `std.Thread.Pool` and `std.Thread.WaitGroup` were removed: use `Io.Group`.
  `std.Thread.spawn` still exists, but tasks spawned outside `Io` don't participate in
  cancelation.

## Synchronization

`std.Thread.Mutex/Condition/ResetEvent/Semaphore/RwLock/Futex` became `std.Io.Mutex`
(`.init`, `try m.lock(io)`, `m.unlock(io)`), `Io.Condition`, `Io.Event`, `Io.Semaphore`,
`Io.RwLock`, and `Io.Futex`, so blocking integrates with the Io implementation and with
cancelation. Lock-free code (`std.atomic.Value`) needs no Io. `std.once` was removed:
avoid globals.

Default design: **share nothing across tasks**. Give each connection or job its own
arena and data, and communicate through `Io.Queue`. Add a mutex only around genuinely
shared state, and keep the critical section free of I/O.

## Choosing the Io implementation

- `Io.Threaded` (what Juicy Main uses) is feature-complete, supports cancelation, and is
  the production choice. `io.concurrent` adds a thread per concurrent task with
  **no limit by default**, so a thread-per-connection server grows with load. To cap it,
  take `main(init: std.process.Init.Minimal)` and build your own:
  `var t: Io.Threaded = .init(gpa, .{ .environ = init.environ, .concurrent_limit =
  .limited(256) }); defer t.deinit(); const io = t.io();` (verified). Then
  `group.concurrent` returns `error.ConcurrencyUnavailable` at the cap, and the server
  should close that connection.
- `Io.Evented` (green threads), `Io.Uring`, `Io.Kqueue`, and `Io.Dispatch` are
  experimental or proof-of-concept in 0.16. `Io.Evented` has no networking yet. Don't
  ship them.
- `-fsingle-threaded` builds still work: `async` runs inline, and `concurrent` fails.

## Pitfalls
- A missing `flush()`: output silently vanishes.
- Keeping a `takeDelimiter` slice after the next read (it points into the buffer).
- Logging `request.head.target` after reading the body (invalidated).
- Spawning with `io.async` and never calling `await` or `cancel` (leaks the task).
- Treating `error.Canceled` as a normal failure and retrying.
- Mixing `std.Thread.Mutex`-style code into Io tasks (it doesn't exist in 0.16; use
  `Io.Mutex`).
