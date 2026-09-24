//! tallyd: a tiny HTTP service over the tally library, on std.http.Server.
//!
//!   GET  /up     -> 200 "ok"                      (kamal-proxy health check)
//!   POST /count  -> 200 {"total":..,"top":[..]}   (body: plain text, <= 1 MiB)
//!
//! Config comes from the environment once, in main: PORT (default 3000).
//! One task per connection via `Io.Group.concurrent`; one arena per request.
const std = @import("std");
const Io = std.Io;
const http = std.http;
const tally = @import("tally");

const log = std.log.scoped(.tallyd);

pub const max_body_len = 1024 * 1024;

pub const Config = struct {
    port: u16 = 3000,

    pub fn fromEnv(env: *const std.process.Environ.Map) error{InvalidPort}!Config {
        var c: Config = .{};
        if (env.get("PORT")) |p| c.port = std.fmt.parseUnsigned(u16, p, 10) catch return error.InvalidPort;
        return c;
    }
};

pub fn main(init: std.process.Init) !void {
    const cfg = try Config.fromEnv(init.environ_map);
    const io = init.io;

    // 0.0.0.0 so Docker's port mapping and kamal-proxy can reach it.
    const address: Io.net.IpAddress = try .parse("0.0.0.0", cfg.port);
    var listener = try address.listen(io, .{ .reuse_address = true });
    defer listener.deinit(io);
    log.info("listening on :{d}", .{cfg.port});

    try serve(init.gpa, io, &listener);
}

/// Accepts connections until canceled. Each connection runs concurrently.
pub fn serve(gpa: std.mem.Allocator, io: Io, listener: *Io.net.Server) Io.Cancelable!void {
    var group: Io.Group = .init;
    defer group.cancel(io);
    while (true) {
        const stream = listener.accept(io) catch |err| switch (err) {
            error.Canceled => |e| return e,
            else => |e| {
                log.err("accept: {t}", .{e});
                continue;
            },
        };
        group.concurrent(io, handleConnection, .{ gpa, io, stream }) catch |err| {
            log.err("spawn: {t}", .{err});
            stream.close(io);
        };
    }
}

fn handleConnection(gpa: std.mem.Allocator, io: Io, stream: Io.net.Stream) void {
    defer stream.close(io);
    var recv_buf: [8 * 1024]u8 = undefined; // also the max request-head size
    var send_buf: [8 * 1024]u8 = undefined;
    var conn_r = stream.reader(io, &recv_buf);
    var conn_w = stream.writer(io, &send_buf);
    var server: http.Server = .init(&conn_r.interface, &conn_w.interface);

    // Request-scoped memory: reset (not freed) between keep-alive requests.
    var arena: std.heap.ArenaAllocator = .init(gpa);
    defer arena.deinit();

    while (true) {
        _ = arena.reset(.retain_capacity);
        var request = server.receiveHead() catch |err| switch (err) {
            error.HttpConnectionClosing => return,
            else => return log.debug("receive head: {t}", .{err}),
        };
        // Copy what we log up front: reading the body invalidates head strings.
        const method = request.head.method;
        handleRequest(arena.allocator(), &request) catch |err|
            return log.err("{t} request failed: {t}", .{ method, err });
        if (!request.head.keep_alive) return;
    }
}

pub const Route = enum { up, count, not_found, method_not_allowed };

/// Pure routing, unit-tested without sockets.
pub fn route(method: http.Method, target: []const u8) Route {
    const path = if (std.mem.findScalar(u8, target, '?')) |q| target[0..q] else target;
    if (std.mem.eql(u8, path, "/up")) return if (method == .GET or method == .HEAD) .up else .method_not_allowed;
    if (std.mem.eql(u8, path, "/count")) return if (method == .POST) .count else .method_not_allowed;
    return .not_found;
}

fn handleRequest(arena: std.mem.Allocator, request: *http.Server.Request) !void {
    // Route BEFORE reading the body: reading it invalidates `request.head` strings.
    switch (route(request.head.method, request.head.target)) {
        .up => return request.respond("ok\n", .{ .extra_headers = &.{text_plain} }),
        .not_found => return request.respond("not found\n", .{ .status = .not_found, .extra_headers = &.{text_plain} }),
        .method_not_allowed => return request.respond("method not allowed\n", .{ .status = .method_not_allowed, .extra_headers = &.{text_plain} }),
        .count => {},
    }

    if (request.head.content_length) |len| if (len > max_body_len) {
        return request.respond("body too large\n", .{ .status = .payload_too_large, .keep_alive = false });
    };

    var body_buf: [4096]u8 = undefined;
    const body_reader = try request.readerExpectContinue(&body_buf);
    const body = body_reader.allocRemaining(arena, .limited(max_body_len)) catch |err| switch (err) {
        error.StreamTooLong => return request.respond("body too large\n", .{ .status = .payload_too_large, .keep_alive = false }),
        else => |e| return e,
    };

    var r: Io.Reader = .fixed(body);
    var t = tally.countWords(arena, &r, .{}) catch |err| switch (err) {
        error.WordTooLong => return request.respond("word too long\n", .{ .status = .bad_request }),
        else => |e| return e,
    };
    // No t.deinit: the arena frees everything at the end of the request.

    var out: Io.Writer.Allocating = .init(arena);
    try t.writeJson(arena, &out.writer, 10);
    try request.respond(out.written(), .{ .extra_headers = &.{.{ .name = "content-type", .value = "application/json" }} });
}

const text_plain: http.Header = .{ .name = "content-type", .value = "text/plain; charset=utf-8" };

test "route" {
    try std.testing.expectEqual(Route.up, route(.GET, "/up"));
    try std.testing.expectEqual(Route.up, route(.HEAD, "/up?probe=1"));
    try std.testing.expectEqual(Route.count, route(.POST, "/count"));
    try std.testing.expectEqual(Route.method_not_allowed, route(.GET, "/count"));
    try std.testing.expectEqual(Route.not_found, route(.GET, "/nope"));
}

test "Config.fromEnv" {
    var env: std.process.Environ.Map = .init(std.testing.allocator);
    defer env.deinit();
    try std.testing.expectEqual(@as(u16, 3000), (try Config.fromEnv(&env)).port);
    try env.put("PORT", "8080");
    try std.testing.expectEqual(@as(u16, 8080), (try Config.fromEnv(&env)).port);
    try env.put("PORT", "http");
    try std.testing.expectError(error.InvalidPort, Config.fromEnv(&env));
}

test "serves /up and /count over a real socket" {
    const io = std.testing.io;
    const gpa = std.testing.allocator;

    const address: Io.net.IpAddress = try .parse("127.0.0.1", 0); // port 0: pick a free one
    var listener = try address.listen(io, .{ .reuse_address = true });
    defer listener.deinit(io);
    const port = listener.socket.address.getPort();

    var server_task = try io.concurrent(serve, .{ gpa, io, &listener });
    defer server_task.cancel(io) catch {};

    var client: http.Client = .{ .allocator = gpa, .io = io };
    defer client.deinit();

    var url_buf: [64]u8 = undefined;
    var body: Io.Writer.Allocating = .init(gpa);
    defer body.deinit();

    const up = try client.fetch(.{
        .location = .{ .url = try std.fmt.bufPrint(&url_buf, "http://127.0.0.1:{d}/up", .{port}) },
        .response_writer = &body.writer,
    });
    try std.testing.expectEqual(http.Status.ok, up.status);
    try std.testing.expectEqualStrings("ok\n", body.written());

    body.clearRetainingCapacity();
    const counted = try client.fetch(.{
        .location = .{ .url = try std.fmt.bufPrint(&url_buf, "http://127.0.0.1:{d}/count", .{port}) },
        .method = .POST,
        .payload = "zig zig go",
        .response_writer = &body.writer,
    });
    try std.testing.expectEqual(http.Status.ok, counted.status);
    try std.testing.expectEqualStrings(
        \\{"total":3,"distinct":2,"top":[{"word":"zig","count":2},{"word":"go","count":1}]}
    , body.written());
}
